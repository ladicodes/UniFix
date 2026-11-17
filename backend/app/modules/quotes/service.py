"""Quotes: versioned offers inside a conversation. Terms are never edited after creation."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.container import Services
from app.core.db import violated_constraint
from app.core.errors import BadRequest, Conflict, Forbidden, NotFound
from app.modules.audit import service as audit
from app.modules.auth.context import AuthContext
from app.modules.chat import service as chat
from app.modules.chat.hub import ConversationHub
from app.modules.chat.models import MessageKind
from app.modules.professionals import repository as professionals_repository
from app.modules.quotes import repository
from app.modules.quotes.models import Agreement, Quote, QuoteStatus
from app.modules.quotes.schemas import QuoteIn, QuoteOut
from app.modules.requests import service as requests
from app.modules.users.models import Role

DEFAULT_VALIDITY = timedelta(days=7)
MAX_VALIDITY = timedelta(days=30)


def is_expired(quote: Quote, now: datetime) -> bool:
    return quote.status == QuoteStatus.PENDING.value and quote.valid_until <= now


def quote_out(quote: Quote, agreement: Agreement | None, now: datetime) -> QuoteOut:
    return QuoteOut(
        id=quote.id,
        conversation_id=quote.conversation_id,
        service_request_id=quote.service_request_id,
        professional_id=quote.professional_id,
        customer_id=quote.customer_id,
        version=quote.version,
        status=QuoteStatus(quote.status),
        title=quote.title,
        description=quote.description,
        labour_minor=quote.labour_minor,
        materials_minor=quote.materials_minor,
        total_minor=quote.total_minor,
        currency=quote.currency,
        completion_date=quote.completion_date,
        payment_terms=quote.payment_terms,
        service_method=quote.service_method,
        milestones=quote.milestones,
        valid_until=quote.valid_until,
        expired=is_expired(quote, now),
        created_at=quote.created_at,
        accepted_at=agreement.accepted_at if agreement else None,
        agreement_hash=agreement.agreement_hash if agreement else None,
    )


async def present(session: AsyncSession, services: Services, quotes: Sequence[Quote]) -> list[QuoteOut]:
    agreements = await repository.agreements_by_quote(session, [q.id for q in quotes])
    now = services.clock.now()
    return [quote_out(q, agreements.get(q.id), now) for q in quotes]


def conversation_quotes_hook(services: Services) -> chat.QuotesLookup:
    async def lookup(session: AsyncSession, conversation_id: uuid.UUID) -> list[dict[str, Any]]:
        quotes = await repository.for_conversation(session, conversation_id)
        return [q.model_dump(mode="json") for q in await present(session, services, quotes)]

    return lookup


async def _publish(services: Services, hub: ConversationHub, event: str, out: QuoteOut) -> None:
    await chat.publish_event(hub, out.conversation_id, event, out.model_dump(mode="json"))


async def create(
    session: AsyncSession, services: Services, hub: ConversationHub, caller: AuthContext, data: QuoteIn
) -> QuoteOut:
    if caller.role is not Role.PROFESSIONAL:
        raise Forbidden("Only professionals can send quotes.", code="ROLE_FORBIDDEN")
    if caller.user.email_verified_at is None:
        raise Forbidden("Verify your email address before sending quotes.", code="EMAIL_NOT_VERIFIED")
    conversation, _ = await chat.require_member(session, caller, data.conversation_id)
    profile = await professionals_repository.get_by_user(session, caller.user_id)
    if profile is None or profile.id != conversation.professional_id:
        raise NotFound("Conversation not found.")
    now = services.clock.now()
    # Lock order everywhere: service request -> conversation -> quote (prevents deadlocks).
    if conversation.service_request_id is not None:
        await requests.require_open_for_quote(session, conversation.service_request_id, now)
    await chat.lock_conversation(session, conversation.id)
    if data.completion_date < now.date():
        raise BadRequest("completion_date cannot be in the past.", code="INVALID_COMPLETION_DATE")
    valid_until = data.valid_until or now + DEFAULT_VALIDITY
    if not now < valid_until <= now + MAX_VALIDITY:
        raise BadRequest("valid_until must be in the future and within 30 days.", code="INVALID_VALIDITY")
    if await repository.has_active_booking(session, conversation.id):
        raise Conflict("This conversation already has an active booking.", code="ACTIVE_BOOKING_EXISTS")

    previous = await repository.pending_in_conversation(session, conversation.id)
    if previous is not None:
        previous.status = QuoteStatus.SUPERSEDED.value
        previous.responded_at = now
        await session.flush()
    quote = Quote(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        service_request_id=conversation.service_request_id,
        professional_id=profile.id,
        customer_id=conversation.customer_id,
        version=await repository.next_version(session, conversation.id),
        status=QuoteStatus.PENDING.value,
        title=data.title,
        description=data.description,
        labour_minor=data.labour_minor,
        materials_minor=data.materials_minor,
        total_minor=data.labour_minor + data.materials_minor,
        currency=data.currency.value,
        completion_date=data.completion_date,
        payment_terms=data.payment_terms,
        service_method=data.service_method.value,
        milestones=[m.model_dump() for m in data.milestones],
        valid_until=valid_until,
        created_at=now,
    )
    repository.add(session, quote)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if violated_constraint(exc) in {
            "uq_quotes_conversation_version",
            "uq_quotes_one_pending_per_conversation",
        }:
            raise Conflict("Another quote was sent at the same time; retry.", code="QUOTE_CONFLICT") from exc
        raise
    message = await chat.insert_message(
        session, conversation.id, sender=caller, body=f"Quote v{quote.version}: {quote.title}",
        kind=MessageKind.QUOTE, now=now, quote_id=quote.id,
    )  # fmt: skip
    await audit.record(
        session,
        action="quote.created",
        entity_type="quote",
        entity_id=quote.id,
        actor_user_id=caller.user_id,
        data={"version": quote.version, "total_minor": quote.total_minor, "currency": quote.currency},
    )
    await session.commit()
    out = (await present(session, services, [quote]))[0]
    if previous is not None:
        await _publish(services, hub, "QUOTE_UPDATED", (await present(session, services, [previous]))[0])
    await _publish(services, hub, "QUOTE_CREATED", out)
    await chat.publish_message(session, services, hub, message)
    return out


async def _decide(
    session: AsyncSession,
    services: Services,
    hub: ConversationHub,
    caller: AuthContext,
    quote_id: uuid.UUID,
    *,
    as_role: Role,
    to: QuoteStatus,
    reason: str | None = None,
) -> QuoteOut:
    quote = await repository.get(session, quote_id, for_update=True)
    if quote is None:
        raise NotFound("Quote not found.")
    if as_role is Role.CUSTOMER and quote.customer_id != caller.user_id:
        raise NotFound("Quote not found.")
    if as_role is Role.PROFESSIONAL:
        profile = await professionals_repository.get_by_user(session, caller.user_id)
        if profile is None or profile.id != quote.professional_id:
            raise NotFound("Quote not found.")
    if quote.status != QuoteStatus.PENDING.value:
        raise Conflict("This quote is no longer pending.", code="QUOTE_NOT_PENDING")
    now = services.clock.now()
    quote.status = to.value
    quote.responded_at = now
    await audit.record(
        session,
        action=f"quote.{to.value.lower()}",
        entity_type="quote",
        entity_id=quote.id,
        actor_user_id=caller.user_id,
        data={"reason": reason} if reason else {},
    )
    await session.commit()
    out = (await present(session, services, [quote]))[0]
    await _publish(services, hub, "QUOTE_UPDATED", out)
    return out


async def reject(
    session: AsyncSession,
    services: Services,
    hub: ConversationHub,
    caller: AuthContext,
    quote_id: uuid.UUID,
    reason: str | None,
) -> QuoteOut:
    return await _decide(
        session,
        services,
        hub,
        caller,
        quote_id,
        as_role=Role.CUSTOMER,
        to=QuoteStatus.REJECTED,
        reason=reason,
    )


async def withdraw(
    session: AsyncSession, services: Services, hub: ConversationHub, caller: AuthContext, quote_id: uuid.UUID
) -> QuoteOut:
    return await _decide(
        session, services, hub, caller, quote_id, as_role=Role.PROFESSIONAL, to=QuoteStatus.WITHDRAWN
    )
