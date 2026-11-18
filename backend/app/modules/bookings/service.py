"""Bookings: quote acceptance into an immutable agreement, the state machine, and booking reads.

There is deliberately no API path into FUNDED or any other financial state: those
transitions belong to the CHAIN actor (the Batch 2 reconciler), after confirmed on-chain
events. Bookings wait in PENDING_PAYMENT until then.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.core.container import Services
from app.core.db import violated_constraint
from app.core.errors import Conflict, Forbidden, NotFound
from app.modules.audit import service as audit
from app.modules.audit.models import ActorType
from app.modules.auth.context import AuthContext
from app.modules.bookings import repository, state
from app.modules.bookings.models import Booking, BookingEvent, BookingStatus, TimelineActor
from app.modules.bookings.schemas import (
    AcceptQuoteIn,
    AgreementProof,
    BookingBundle,
    BookingOut,
    TimelineEvent,
)
from app.modules.chat import service as chat
from app.modules.chat.hub import ConversationHub
from app.modules.professionals import repository as professionals_repository
from app.modules.professionals import service as professionals
from app.modules.professionals.repository import SearchRow
from app.modules.quotes import agreement as agreements
from app.modules.quotes import repository as quotes_repository
from app.modules.quotes import service as quotes
from app.modules.quotes.models import Agreement, QuoteStatus
from app.modules.requests import service as requests
from app.modules.users.models import Role

PAYMENT_WINDOW = timedelta(days=7)

# Payments (Issue 6) sits above bookings in the module graph; it plugs in through these hooks,
# registered by the app factory.
PaymentExtension = Callable[
    [AsyncSession, Booking, TimelineActor | None, datetime], Awaitable[tuple[Any, list[str]]]
]
FundingGuard = Callable[[AsyncSession, uuid.UUID], Awaitable[bool]]
TermsLookup = Callable[[AsyncSession, uuid.UUID], Awaitable[tuple[str, str] | None]]
_payment_extension: PaymentExtension | None = None
_funding_in_flight: FundingGuard | None = None
_terms_lookup: TermsLookup | None = None


BundleAddon = Callable[
    [AsyncSession, Booking, TimelineActor | None, datetime], Awaitable[tuple[dict[str, Any], list[str]]]
]
_addons: list[BundleAddon] = []


def register_bundle_addon(addon: BundleAddon) -> None:
    """Disputes and reviews add their part of the booking bundle (fields + allowed actions)."""
    _addons[:] = [a for a in _addons if getattr(a, "__name__", None) != getattr(addon, "__name__", None)]
    _addons.append(addon)


def register_payment_hooks(
    *, extension: PaymentExtension, funding_guard: FundingGuard, terms: TermsLookup
) -> None:
    global _payment_extension, _funding_in_flight, _terms_lookup
    _payment_extension, _funding_in_flight, _terms_lookup = extension, funding_guard, terms


async def _funding_pending(session: AsyncSession, booking_id: uuid.UUID) -> bool:
    return _funding_in_flight is not None and await _funding_in_flight(session, booking_id)


class InvalidTransition(Conflict):
    code = "BOOKING_INVALID_TRANSITION"


async def transition(
    session: AsyncSession,
    booking: Booking,
    to: BookingStatus,
    *,
    actor: TimelineActor,
    actor_user_id: uuid.UUID | None,
    label: str,
    now: datetime,
    data: dict[str, Any] | None = None,
) -> None:
    """The only writer of ``bookings.status``: checks the transition table, writes timeline and audit."""
    current = BookingStatus(booking.status)
    rule = state.rule_for(current, to)
    if rule is None or actor not in rule.actors:
        raise InvalidTransition(f"A booking cannot move from {current.value} to {to.value}.")
    booking.status = to.value
    stamps = {
        BookingStatus.FUNDED: "funded_at",
        BookingStatus.IN_PROGRESS: "started_at",
        BookingStatus.COMPLETION_SUBMITTED: "completion_submitted_at",
        BookingStatus.COMPLETED: "completed_at",
        BookingStatus.RESOLVED: "completed_at",
        BookingStatus.CANCELLED: "cancelled_at",
    }
    if to in stamps:
        setattr(booking, stamps[to], now)
    repository.add(
        session,
        BookingEvent(
            booking_id=booking.id,
            from_status=current.value,
            to_status=to.value,
            label=label,
            actor_type=actor.value,
            actor_user_id=actor_user_id,
            data=data or {},
            created_at=now,
        ),
    )
    await audit.record(
        session,
        action="booking.transition",
        entity_type="booking",
        entity_id=booking.id,
        actor_user_id=actor_user_id,
        actor_type=ActorType.SYSTEM
        if actor in {TimelineActor.SYSTEM, TimelineActor.CHAIN}
        else ActorType.USER,
        data={"from": current.value, "to": to.value},
    )


def _actor_for(
    caller: AuthContext, booking: Booking, professional_user_id: uuid.UUID
) -> TimelineActor | None:
    if caller.user_id == booking.customer_id:
        return TimelineActor.CUSTOMER
    if caller.user_id == professional_user_id:
        return TimelineActor.PROFESSIONAL
    return None


# ---------------------------------------------------------------- acceptance


async def accept_quote(
    session: AsyncSession,
    services: Services,
    hub: ConversationHub,
    caller: AuthContext,
    quote_id: uuid.UUID,
    data: AcceptQuoteIn,
) -> BookingBundle:
    """One transaction: lock, validate, write the immutable agreement, create the booking."""
    if caller.role is not Role.CUSTOMER:
        raise Forbidden("Only customers can accept quotes.", code="ROLE_FORBIDDEN")
    now = services.clock.now()
    # Lock order everywhere: service request -> conversation -> quote. Competing acceptances
    # and new quotes therefore serialise instead of deadlocking.
    unlocked = await quotes_repository.get(session, quote_id)
    if unlocked is None or unlocked.customer_id != caller.user_id:
        raise NotFound("Quote not found.")
    service_request = None
    if unlocked.service_request_id is not None:
        service_request = await requests.require_open_for_quote(session, unlocked.service_request_id, now)
    await chat.lock_conversation(session, unlocked.conversation_id)
    quote = await quotes_repository.get(session, quote_id, for_update=True)
    assert quote is not None
    await session.refresh(quote)  # re-read under the lock
    if quote.status != QuoteStatus.PENDING.value:
        raise Conflict("This quote is no longer pending.", code="QUOTE_NOT_PENDING")
    if quotes.is_expired(quote, now):
        raise Conflict("This quote has expired; ask for a new one.", code="QUOTE_EXPIRED")
    if await quotes_repository.has_active_booking(session, quote.conversation_id):
        raise Conflict("This conversation already has an active booking.", code="ACTIVE_BOOKING_EXISTS")

    booking_id, agreement_id = uuid.uuid4(), uuid.uuid4()
    document = agreements.build_document(
        agreement_id=agreement_id,
        booking_id=booking_id,
        quote_id=quote.id,
        quote_version=quote.version,
        conversation_id=quote.conversation_id,
        service_request_id=quote.service_request_id,
        customer_id=quote.customer_id,
        professional_id=quote.professional_id,
        title=quote.title,
        description=quote.description,
        labour_minor=quote.labour_minor,
        materials_minor=quote.materials_minor,
        total_minor=quote.total_minor,
        currency=quote.currency,
        completion_date=quote.completion_date,
        service_method=quote.service_method,
        payment_terms=quote.payment_terms,
        milestones=quote.milestones,
        accepted_at=now,
    )
    canonical = agreements.canonicalize(document)
    agreement = Agreement(
        id=agreement_id,
        booking_id=booking_id,
        quote_id=quote.id,
        customer_id=quote.customer_id,
        professional_id=quote.professional_id,
        canonical_json=canonical,
        agreement_hash=agreements.digest(canonical),
        total_minor=quote.total_minor,
        currency=quote.currency,
        accepted_by=caller.user_id,
        accepted_at=now.replace(microsecond=0),
    )
    booking = Booking(
        id=booking_id,
        agreement_id=agreement_id,
        quote_id=quote.id,
        conversation_id=quote.conversation_id,
        service_request_id=quote.service_request_id,
        customer_id=quote.customer_id,
        professional_id=quote.professional_id,
        title=quote.title,
        service_address=data.service_address or (service_request.location_text if service_request else None),
        amount_minor=quote.total_minor,  # always from the agreement, never from client input
        currency=quote.currency,
        status=BookingStatus.PENDING_PAYMENT.value,
        payment_due_by=now + PAYMENT_WINDOW,
    )
    quote.status = QuoteStatus.ACCEPTED.value
    quote.responded_at = now
    quotes_repository.add(session, agreement)
    await session.flush()  # the booking references the agreement row
    repository.add(session, booking)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if violated_constraint(exc) in {
            "uq_bookings_active_per_conversation",
            "uq_bookings_per_service_request",
        }:
            raise Conflict("A booking already exists for this job.", code="ACTIVE_BOOKING_EXISTS") from exc
        raise
    repository.add(
        session,
        BookingEvent(
            booking_id=booking.id, to_status=BookingStatus.PENDING_PAYMENT.value, label="Quote accepted",
            actor_type=TimelineActor.CUSTOMER.value, actor_user_id=caller.user_id, created_at=now,
            data={"quote_id": str(quote.id), "agreement_hash": agreement.agreement_hash},
        ),
    )  # fmt: skip
    if service_request is not None:
        await quotes_repository.reject_other_pending(session, service_request.id, quote.id, now)
        await requests.mark_booked(session, service_request)
    system = await chat.add_system_message(
        session,
        quote.conversation_id,
        f"Quote v{quote.version} accepted. Booking created; awaiting payment.",
        now=now,
    )
    await audit.record(
        session,
        action="quote.accepted",
        entity_type="booking",
        entity_id=booking.id,
        actor_user_id=caller.user_id,
        data={
            "quote_id": str(quote.id),
            "agreement_hash": agreement.agreement_hash,
            "amount_minor": booking.amount_minor,
        },
    )
    await session.commit()
    bundle = (await bundles(session, services, caller, [booking]))[0]
    await chat.publish_message(session, services, hub, system)
    await chat.publish_event(
        hub, quote.conversation_id, "QUOTE_UPDATED", bundle.quote.model_dump(mode="json")
    )
    await chat.publish_event(
        hub,
        quote.conversation_id,
        "BOOKING_UPDATED",
        {"booking_id": str(booking.id), "status": booking.status},
    )
    return bundle


# ---------------------------------------------------------------- reads


async def _expire_if_due(session: AsyncSession, services: Services, booking: Booking) -> bool:
    now = services.clock.now()
    if (
        booking.status == BookingStatus.PENDING_PAYMENT.value
        and now >= booking.payment_due_by
        and not await _funding_pending(session, booking.id)
    ):
        await transition(
            session, booking, BookingStatus.CANCELLED, actor=TimelineActor.SYSTEM, actor_user_id=None,
            label="Payment window expired", now=now,
        )  # fmt: skip
        booking.cancellation_reason = "Payment not received within 7 days"
        if booking.service_request_id:
            await requests.reopen_if_booked(session, booking.service_request_id)
        return True
    return False


async def _visible_booking(
    session: AsyncSession,
    services: Services,
    caller: AuthContext,
    booking_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> tuple[Booking, uuid.UUID]:
    booking = await repository.get(session, booking_id, for_update=for_update)
    if booking is None:
        raise NotFound("Booking not found.")
    profile = await professionals_repository.get(session, booking.professional_id)
    assert profile is not None
    if not (caller.is_admin or caller.user_id in {booking.customer_id, profile.user_id}):
        raise NotFound("Booking not found.")
    if await _expire_if_due(session, services, booking):
        await session.commit()
    return booking, profile.user_id


def _booking_out(
    booking: Booking, agreement: Agreement, events: Sequence[BookingEvent], *, show_address: bool
) -> BookingOut:
    return BookingOut(
        id=booking.id,
        quote_id=booking.quote_id,
        agreement_id=booking.agreement_id,
        agreement_hash=agreement.agreement_hash,
        conversation_id=booking.conversation_id,
        service_request_id=booking.service_request_id,
        customer_id=booking.customer_id,
        professional_id=booking.professional_id,
        title=booking.title,
        address=booking.service_address if show_address else None,
        status=BookingStatus(booking.status),
        amount_minor=booking.amount_minor,
        currency=booking.currency,
        payment_due_by=booking.payment_due_by,
        created_at=booking.created_at,
        cancellation_reason=booking.cancellation_reason,
        timeline=[
            TimelineEvent(
                at=event.created_at,
                label=event.label,
                actor=TimelineActor(event.actor_type),
                from_status=BookingStatus(event.from_status) if event.from_status else None,
                to_status=BookingStatus(event.to_status) if event.to_status else None,
            )
            for event in events
        ],
    )


_ADDRESS_VISIBLE_TO_PROFESSIONAL = {
    BookingStatus.FUNDED, BookingStatus.IN_PROGRESS, BookingStatus.COMPLETION_SUBMITTED,
    BookingStatus.COMPLETED, BookingStatus.DISPUTED, BookingStatus.RESOLVED,
}  # fmt: skip


async def bundles(
    session: AsyncSession, services: Services, caller: AuthContext, bookings: Sequence[Booking]
) -> list[BookingBundle]:
    ids = [b.id for b in bookings]
    events = await repository.timeline(session, ids)
    quote_rows = {q.id: q for q in [await quotes_repository.get(session, b.quote_id) for b in bookings] if q}
    quote_outs = {q.id: q for q in await quotes.present(session, services, list(quote_rows.values()))}
    agreement_rows = {b.id: await quotes_repository.get_agreement(session, b.agreement_id) for b in bookings}
    rows: list[SearchRow] = []
    for booking in bookings:
        found = await professionals_repository.get_with_user(session, booking.professional_id)
        assert found is not None
        rows.append(SearchRow(profile=found[0], user=found[1], distance_km=None))
    professional_outs = {p.id: p for p in await professionals.present_many(session, rows)}
    professional_users = {row.profile.id: row.user.id for row in rows}
    customers = await chat.public_users(session, [b.customer_id for b in bookings])
    result = []
    for booking in bookings:
        agreement = agreement_rows[booking.id]
        assert agreement is not None
        is_professional = caller.user_id == professional_users[booking.professional_id]
        status = BookingStatus(booking.status)
        show_address = not is_professional or status in _ADDRESS_VISIBLE_TO_PROFESSIONAL
        actor = (
            TimelineActor.PROFESSIONAL
            if is_professional
            else TimelineActor.CUSTOMER
            if caller.user_id == booking.customer_id
            else None
        )
        actions = state.user_actions(status, actor) if actor else []
        escrow = None
        if _payment_extension is not None:
            escrow, extra = await _payment_extension(session, booking, actor, services.clock.now())
            if "CANCEL" in actions and await _funding_pending(session, booking.id):
                actions.remove("CANCEL")
            actions = sorted({*actions, *extra})
        fields: dict[str, Any] = {}
        for addon in _addons:
            extra_fields, extra_actions = await addon(session, booking, actor, services.clock.now())
            fields.update(extra_fields)
            actions = sorted({*actions, *extra_actions})
        result.append(
            BookingBundle(
                booking=_booking_out(booking, agreement, events[booking.id], show_address=show_address),
                quote=quote_outs[booking.quote_id],
                professional=professional_outs[booking.professional_id],
                customer=customers[booking.customer_id],
                escrow=escrow,
                allowed_actions=actions,
                **fields,
            )
        )
    return result


async def list_bookings(
    session: AsyncSession,
    services: Services,
    caller: AuthContext,
    *,
    status: BookingStatus | None,
    role: Role | None,
    limit: int,
    offset: int,
) -> tuple[list[BookingBundle], int]:
    profile = await professionals_repository.get_by_user(session, caller.user_id)
    as_customer = role in {None, Role.CUSTOMER}
    as_professional = role in {None, Role.PROFESSIONAL} and profile is not None
    if not as_customer and not as_professional:
        return [], 0
    rows, total = await repository.list_for(
        session,
        customer_id=caller.user_id if as_customer else None,
        professional_id=profile.id if as_professional and profile else None,
        status=status.value if status else None,
        limit=limit,
        offset=offset,
    )
    expired = [await _expire_if_due(session, services, booking) for booking in rows]
    if any(expired):
        await session.commit()
    return await bundles(session, services, caller, rows), total


async def get_bundle(
    session: AsyncSession, services: Services, caller: AuthContext, booking_id: uuid.UUID
) -> BookingBundle:
    booking, _ = await _visible_booking(session, services, caller, booking_id)
    return (await bundles(session, services, caller, [booking]))[0]


async def agreement_proof(
    session: AsyncSession, services: Services, caller: AuthContext, booking_id: uuid.UUID
) -> AgreementProof:
    booking, _ = await _visible_booking(session, services, caller, booking_id)
    agreement = await quotes_repository.get_agreement(session, booking.agreement_id)
    assert agreement is not None
    proof = AgreementProof(agreement_json=agreement.canonical_json, agreement_hash=agreement.agreement_hash)
    if _terms_lookup is not None and (found := await _terms_lookup(session, booking.id)) is not None:
        proof.escrow_terms_json, proof.terms_hash = found
    return proof


async def active_bookings_hook(
    session: AsyncSession, conversation_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    return await repository.active_by_conversation(session, conversation_ids)


# ---------------------------------------------------------------- participant actions


async def _act(
    session: AsyncSession,
    services: Services,
    hub: ConversationHub,
    caller: AuthContext,
    booking_id: uuid.UUID,
    to: BookingStatus,
    *,
    label: str,
    reason: str | None = None,
) -> BookingBundle:
    booking, professional_user_id = await _visible_booking(
        session, services, caller, booking_id, for_update=True
    )
    actor = _actor_for(caller, booking, professional_user_id)
    if actor is None:
        raise NotFound("Booking not found.")
    if to is BookingStatus.CANCELLED and await _funding_pending(session, booking.id):
        raise Conflict("A payment for this booking is being confirmed; it cannot be cancelled now.",
                       code="FUNDING_IN_PROGRESS")  # fmt: skip
    now = services.clock.now()
    await transition(session, booking, to, actor=actor, actor_user_id=caller.user_id, label=label, now=now)
    if to is BookingStatus.CANCELLED:
        booking.cancelled_by = caller.user_id
        booking.cancellation_reason = reason
        if booking.service_request_id:
            await requests.reopen_if_booked(session, booking.service_request_id)
    system = await chat.add_system_message(session, booking.conversation_id, label, now=now)
    try:
        await session.commit()
    except StaleDataError as exc:  # optimistic lock: someone changed it first
        await session.rollback()
        raise Conflict("The booking changed; reload and retry.", code="BOOKING_CHANGED") from exc
    await chat.publish_message(session, services, hub, system)
    await chat.publish_event(
        hub,
        booking.conversation_id,
        "BOOKING_UPDATED",
        {"booking_id": str(booking.id), "status": booking.status},
    )
    return (await bundles(session, services, caller, [booking]))[0]


async def start(
    session: AsyncSession,
    services: Services,
    hub: ConversationHub,
    caller: AuthContext,
    booking_id: uuid.UUID,
) -> BookingBundle:
    return await _act(
        session, services, hub, caller, booking_id, BookingStatus.IN_PROGRESS, label="Work started"
    )


async def cancel(
    session: AsyncSession,
    services: Services,
    hub: ConversationHub,
    caller: AuthContext,
    booking_id: uuid.UUID,
    reason: str,
) -> BookingBundle:
    return await _act(
        session,
        services,
        hub,
        caller,
        booking_id,
        BookingStatus.CANCELLED,
        label="Booking cancelled",
        reason=reason,
    )


# ---------------------------------------------------------------- helpers for payments (Issue 6)


async def visible_booking(
    session: AsyncSession,
    services: Services,
    caller: AuthContext,
    booking_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> tuple[Booking, uuid.UUID]:
    """The booking if the caller is a party or an admin (404 otherwise), plus the professional's user id."""
    return await _visible_booking(session, services, caller, booking_id, for_update=for_update)


async def lock_booking(session: AsyncSession, booking_id: uuid.UUID) -> Booking:
    booking = await repository.get(session, booking_id, for_update=True)
    assert booking is not None
    return booking


async def professional_user_id(session: AsyncSession, booking: Booking) -> uuid.UUID:
    profile = await professionals_repository.get(session, booking.professional_id)
    assert profile is not None
    return profile.user_id


async def add_timeline_note(
    session: AsyncSession,
    booking: Booking,
    *,
    label: str,
    actor: TimelineActor,
    actor_user_id: uuid.UUID | None,
    now: datetime,
    data: dict[str, Any] | None = None,
) -> None:
    """A timeline entry that does not change the status (append-only)."""
    repository.add(
        session,
        BookingEvent(
            booking_id=booking.id, label=label, actor_type=actor.value, actor_user_id=actor_user_id,
            data=data or {}, created_at=now,
        ),
    )  # fmt: skip


async def record_completed_job(session: AsyncSession, booking: Booking) -> None:
    """Called once, in the transaction that moves the booking to COMPLETED (a terminal state)."""
    await professionals_repository.increment_completed_jobs(session, booking.professional_id)


async def is_party(session: AsyncSession, caller: AuthContext, booking_id: uuid.UUID) -> bool:
    booking = await repository.get(session, booking_id)
    if booking is None:
        return False
    return caller.user_id == booking.customer_id or caller.user_id == await professional_user_id(
        session, booking
    )


async def booking_row(session: AsyncSession, booking_id: uuid.UUID) -> Booking:
    booking = await repository.get(session, booking_id)
    assert booking is not None
    return booking
