"""Disputes: off-chain record → on-chain lock → evidence → arbiter resolution or a concession.

* Creating the record blocks ordinary release and refund preparation at once (payments guard),
  before the on-chain lock confirms.
* Only the arbiter (an admin whose verified wallet is the contract's arbiter) can resolve, and
  only the reconciler sets the outcome, from the confirmed chain event.
* There is no automatic settlement of disputed funds (P1 / F-A): overdue disputes escalate.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.container import Services
from app.core.db import violated_constraint
from app.core.errors import BadRequest, Conflict, Forbidden, NotFound
from app.modules.audit import service as audit
from app.modules.audit.models import ActorType
from app.modules.auth.context import AuthContext
from app.modules.bookings import service as bookings
from app.modules.bookings.models import BookingStatus, TimelineActor
from app.modules.chat import service as chat
from app.modules.completion import service as completion
from app.modules.disputes.models import (
    ACTIVE_DISPUTE,
    Dispute,
    DisputeEvidence,
    DisputeOutcome,
    DisputeStatus,
)
from app.modules.disputes.schemas import (
    DisputeBundle,
    DisputeOut,
    DisputePreparedOut,
    EvidenceIn,
    EvidenceOut,
    OpenDisputeIn,
    ResolveIn,
    SlaOut,
)
from app.modules.payments import repository as payments_repository
from app.modules.payments import service as payments
from app.modules.payments.models import Escrow, EscrowState, TxKind
from app.modules.payments.reconciler import ApplyContext
from app.modules.payments.schemas import EscrowOut
from app.modules.stellar import contract
from app.modules.stellar.context import StellarContext
from app.modules.stellar.contract import Function
from app.modules.uploads import repository as uploads_repository
from app.modules.uploads import service as uploads
from app.modules.uploads.models import FilePurpose
from app.modules.wallets import service as wallets

logger = logging.getLogger(__name__)

EVIDENCE_WINDOW = timedelta(hours=72)
DECISION_WINDOW = timedelta(days=7)
ESCALATIONS = (timedelta(days=7), timedelta(days=14))  # STELLAR_ESCROW_DESIGN §4.5 stages 3 and 4
_ACTIVE = [s.value for s in ACTIVE_DISPUTE]


def split_amount(asset_units: int, bps: int) -> int:
    """professional_amount = floor(asset_units * bps / 10000); the remainder goes to the customer."""
    if not 0 <= bps <= 10_000:
        raise ValueError("bps must be 0..10000")
    return asset_units * bps // 10_000


# ---------------------------------------------------------------- queries and presentation


async def _active(
    session: AsyncSession, booking_id: uuid.UUID, *, for_update: bool = False
) -> Dispute | None:
    statement = select(Dispute).where(Dispute.booking_id == booking_id, Dispute.status.in_(_ACTIVE))
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def has_active_dispute(session: AsyncSession, booking_id: uuid.UUID) -> bool:
    """Payments guard: an active record blocks ordinary release/refund preparation."""
    return await _active(session, booking_id) is not None


async def _get(session: AsyncSession, dispute_id: uuid.UUID, *, for_update: bool = False) -> Dispute:
    statement = select(Dispute).where(Dispute.id == dispute_id)
    if for_update:
        statement = statement.with_for_update()
    dispute = (await session.execute(statement)).scalar_one_or_none()
    if dispute is None:
        raise NotFound("Dispute not found.")
    return dispute


async def present(session: AsyncSession, services: Services, dispute: Dispute) -> DisputeOut:
    rows = (
        (
            await session.execute(
                select(DisputeEvidence)
                .where(DisputeEvidence.dispute_id == dispute.id)
                .order_by(DisputeEvidence.created_at, DisputeEvidence.id)
            )
        )
        .scalars()
        .all()
    )
    files = {
        f.id: f for f in await uploads_repository.get_many(session, [r.file_id for r in rows if r.file_id])
    }
    return DisputeOut(
        id=dispute.id,
        booking_id=dispute.booking_id,
        escrow_id=dispute.escrow_id,
        opened_by=dispute.opened_by,
        reason=dispute.reason,
        details=dispute.details,
        status=dispute.status,
        opened_at=dispute.created_at,
        locked_at=dispute.locked_at,
        outcome=dispute.outcome,
        sla=SlaOut(
            evidence_closes_at=dispute.evidence_closes_at,
            decision_due_at=dispute.decision_due_at,
            escalation_level=dispute.escalation_level,
            escalated_at=dispute.escalated_at,
        ),
        split_bps_to_professional=dispute.split_bps_to_professional,
        resolution_note=dispute.resolution_note,
        resolved_at=dispute.resolved_at,
        evidence=[
            EvidenceOut(
                id=r.id,
                submitted_by=r.submitted_by,
                note=r.note,
                file=uploads.file_ref(services, files[r.file_id]) if r.file_id in files else None,
                created_at=r.created_at,
            )
            for r in rows
        ],
    )


async def _visible(
    session: AsyncSession, services: Services, caller: AuthContext, dispute: Dispute
) -> tuple[TimelineActor, uuid.UUID]:
    """The caller's role in the dispute (404 for outsiders) and the professional's user id."""
    booking, professional_user_id = await bookings.visible_booking(
        session, services, caller, dispute.booking_id
    )
    if caller.user_id == booking.customer_id:
        return TimelineActor.CUSTOMER, professional_user_id
    if caller.user_id == professional_user_id:
        return TimelineActor.PROFESSIONAL, professional_user_id
    return TimelineActor.ADMIN, professional_user_id


async def bundle_extension(
    session: AsyncSession, services: Services, booking_id: uuid.UUID, actor: TimelineActor | None
) -> tuple[DisputeOut | None, list[str]]:
    """The booking bundle's ``dispute`` and dispute-related ``allowed_actions``."""
    dispute = (
        await session.execute(
            select(Dispute)
            .where(Dispute.booking_id == booking_id)
            .order_by(Dispute.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    escrow = await payments_repository.escrow_for_booking(session, booking_id)
    actions: list[str] = []
    now = int(services.clock.now().timestamp())
    if escrow is not None and actor in {TimelineActor.CUSTOMER, TimelineActor.PROFESSIONAL}:
        state = EscrowState(escrow.state)
        deadline = escrow.refund_after if state is EscrowState.FUNDED else escrow.review_deadline
        open_record = dispute is not None and dispute.status in _ACTIVE
        if state in {EscrowState.FUNDED, EscrowState.COMPLETION_SUBMITTED} and deadline and now < deadline:
            actions.append("OPEN_DISPUTE" if not open_record else "LOCK_DISPUTE")
        if state is EscrowState.DISPUTED:
            actions.append("CONCEDE_RELEASE" if actor is TimelineActor.CUSTOMER else "CONCEDE_REFUND")
    return (await present(session, services, dispute) if dispute else None), actions


# ---------------------------------------------------------------- opening and locking


def _party_wallet(escrow: Escrow, actor: TimelineActor) -> str:
    return escrow.customer_wallet if actor is TimelineActor.CUSTOMER else escrow.professional_wallet


async def _prepare_lock(
    session: AsyncSession,
    services: Services,
    stellar: StellarContext,
    caller: AuthContext,
    dispute: Dispute,
    escrow: Escrow,
    actor: TimelineActor,
) -> DisputePreparedOut:
    wallet = _party_wallet(escrow, actor)
    tx = await payments.prepare_tx(
        session, services, stellar, escrow=escrow, kind=TxKind.DISPUTE, source=wallet,
        function=Function.OPEN_DISPUTE, args=contract.open_dispute_args(escrow.escrow_key, wallet),
        requested_by=caller.user_id, data={"dispute_id": str(dispute.id)},
    )  # fmt: skip
    await session.commit()
    return DisputePreparedOut(
        dispute=await present(session, services, dispute),
        escrow=await payments.present(session, stellar, escrow),
        unsigned_xdr=tx.unsigned_envelope_xdr,
        tx_hash=tx.tx_hash,
        valid_until=tx.valid_until,
    )


async def open_dispute(
    session: AsyncSession,
    services: Services,
    stellar: StellarContext,
    caller: AuthContext,
    escrow_id: uuid.UUID,
    data: OpenDisputeIn,
) -> DisputePreparedOut:
    unlocked = await payments_repository.escrow(session, escrow_id)
    if unlocked is None:
        raise NotFound("Escrow not found.")
    booking, professional_user_id = await bookings.visible_booking(
        session, services, caller, unlocked.booking_id, for_update=True
    )
    if caller.user_id == booking.customer_id:
        actor = TimelineActor.CUSTOMER
    elif caller.user_id == professional_user_id:
        actor = TimelineActor.PROFESSIONAL
    else:
        raise Forbidden(
            "Only the booking's customer or professional can open a dispute.", code="ROLE_FORBIDDEN"
        )
    escrow = await payments_repository.escrow(session, escrow_id, for_update=True)
    assert escrow is not None
    allowed = {
        BookingStatus.FUNDED.value,
        BookingStatus.IN_PROGRESS.value,
        BookingStatus.COMPLETION_SUBMITTED.value,
    }
    state = EscrowState(escrow.state)
    if booking.status not in allowed or state not in {EscrowState.FUNDED, EscrowState.COMPLETION_SUBMITTED}:
        raise Conflict("A dispute can be opened on a funded booking only.", code="DISPUTE_NOT_ALLOWED")
    now = services.clock.now()
    deadline = escrow.refund_after if state is EscrowState.FUNDED else escrow.review_deadline
    if deadline is None or now.timestamp() >= deadline:
        raise Conflict(
            "The deadline for this stage has passed; its outcome is final.", code="DEADLINE_PASSED"
        )
    dispute = Dispute(
        booking_id=booking.id, escrow_id=escrow.id, opened_by=caller.user_id, reason=data.reason.value,
        details=data.details, status=DisputeStatus.OPEN.value,
    )  # fmt: skip
    session.add(dispute)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if violated_constraint(exc) == "uq_disputes_active_per_booking":
            raise Conflict("A dispute is already open for this booking.", code="DISPUTE_EXISTS") from exc
        raise
    await bookings.add_timeline_note(
        session, booking, label="Dispute opened", actor=actor, actor_user_id=caller.user_id, now=now,
        data={"reason": data.reason.value},
    )  # fmt: skip
    await chat.add_system_message(
        session, booking.conversation_id,
        "A dispute was opened. Release and refund are paused while it is locked on-chain.", now=now,
    )  # fmt: skip
    await audit.record(
        session, action="dispute.opened", entity_type="booking", entity_id=booking.id,
        actor_user_id=caller.user_id, data={"dispute_id": str(dispute.id), "reason": data.reason.value},
    )  # fmt: skip
    return await _prepare_lock(session, services, stellar, caller, dispute, escrow, actor)


async def lock(
    session: AsyncSession,
    services: Services,
    stellar: StellarContext,
    caller: AuthContext,
    dispute_id: uuid.UUID,
    signed_xdr: str | None,
) -> DisputePreparedOut | EscrowOut:
    dispute = await _get(session, dispute_id)
    actor, _ = await _visible(session, services, caller, dispute)
    if actor is TimelineActor.ADMIN:
        raise Forbidden("Only a party can lock the dispute on-chain.", code="ROLE_FORBIDDEN")
    if signed_xdr is not None:
        return await payments.submit_signed(
            session, services, stellar, caller, escrow_id=dispute.escrow_id, kind=TxKind.DISPUTE,
            signed_xdr=signed_xdr,
        )  # fmt: skip
    if dispute.status != DisputeStatus.OPEN.value:
        raise Conflict("This dispute is already locked on-chain.", code="DISPUTE_ALREADY_LOCKED")
    await bookings.visible_booking(session, services, caller, dispute.booking_id, for_update=True)
    escrow = await payments_repository.escrow(session, dispute.escrow_id, for_update=True)
    assert escrow is not None
    return await _prepare_lock(session, services, stellar, caller, dispute, escrow, actor)


async def get(
    session: AsyncSession, services: Services, caller: AuthContext, dispute_id: uuid.UUID
) -> DisputeOut:
    dispute = await _get(session, dispute_id)
    await _visible(session, services, caller, dispute)
    return await present(session, services, dispute)


async def add_evidence(
    session: AsyncSession, services: Services, caller: AuthContext, dispute_id: uuid.UUID, data: EvidenceIn
) -> DisputeOut:
    dispute = await _get(session, dispute_id, for_update=True)
    await _visible(session, services, caller, dispute)
    if dispute.status not in _ACTIVE:
        raise Conflict("This dispute is closed.", code="DISPUTE_CLOSED")
    if data.file_id is not None:
        await uploads.require_owned(session, caller, [data.file_id], FilePurpose.DISPUTE_EVIDENCE)
    session.add(DisputeEvidence(dispute_id=dispute.id, submitted_by=caller.user_id, note=data.note,
                                file_id=data.file_id))  # fmt: skip
    await audit.record(
        session, action="dispute.evidence_added", entity_type="dispute", entity_id=dispute.id,
        actor_user_id=caller.user_id, data={"file_id": str(data.file_id) if data.file_id else None},
    )  # fmt: skip
    await session.commit()
    return await present(session, services, dispute)


async def can_read_evidence(session: AsyncSession, caller: AuthContext, file: object) -> bool:
    """Upload read rule: dispute evidence is visible to the two parties and admins only."""
    file_id = getattr(file, "id", None)
    if file_id is None:
        return False
    if caller.is_admin:
        return True
    booking_ids: Sequence[uuid.UUID] = (
        (
            await session.execute(
                select(Dispute.booking_id)
                .join(DisputeEvidence, DisputeEvidence.dispute_id == Dispute.id)
                .where(DisputeEvidence.file_id == file_id)
            )
        )
        .scalars()
        .all()
    )
    for booking_id in booking_ids:
        if await bookings.is_party(session, caller, booking_id):
            return True
    return False


# ---------------------------------------------------------------- administration


async def admin_queue(
    session: AsyncSession, services: Services, stellar: StellarContext, status: DisputeStatus | None
) -> list[DisputeBundle]:
    statement = select(Dispute).order_by(Dispute.decision_due_at.asc().nulls_last(), Dispute.created_at)
    statement = (
        statement.where(Dispute.status == status.value)
        if status
        else statement.where(Dispute.status.in_(_ACTIVE))
    )
    result = []
    for dispute in (await session.execute(statement.limit(200))).scalars().all():
        escrow = await payments_repository.escrow(session, dispute.escrow_id)
        assert escrow is not None
        row = await bookings.booking_row(session, dispute.booking_id)
        result.append(
            DisputeBundle(
                dispute=await present(session, services, dispute),
                escrow=await payments.present(session, stellar, escrow),
                booking_title=row.title,
                customer_id=row.customer_id,
                professional_id=row.professional_id,
            )
        )
    return result


async def resolve(
    session: AsyncSession,
    services: Services,
    stellar: StellarContext,
    admin: AuthContext,
    dispute_id: uuid.UUID,
    data: ResolveIn,
) -> DisputePreparedOut | DisputeOut:
    """Two steps for the arbiter: prepare ``resolve`` for the arbiter wallet, then submit it signed."""
    gateway = stellar.require()
    dispute = await _get(session, dispute_id)
    if data.signed_xdr is not None:
        await payments.submit_signed(
            session, services, stellar, admin, escrow_id=dispute.escrow_id, kind=TxKind.RESOLVE,
            signed_xdr=data.signed_xdr,
        )  # fmt: skip
        dispute = await _get(session, dispute_id, for_update=True)
        if dispute.status == DisputeStatus.UNDER_REVIEW.value:
            dispute.status = DisputeStatus.AWAITING_SETTLEMENT.value
        await session.commit()
        return await present(session, services, dispute)
    if data.outcome is None or data.note is None:
        raise BadRequest("Provide outcome and note to prepare, or signed_xdr to submit.", code="INVALID_BODY")
    if data.outcome not in {DisputeOutcome.RELEASE, DisputeOutcome.REFUND, DisputeOutcome.SPLIT}:
        raise BadRequest("The arbiter decides RELEASE, REFUND or SPLIT.", code="INVALID_OUTCOME")
    if (data.outcome is DisputeOutcome.SPLIT) != (data.split_bps_to_professional is not None):
        raise BadRequest("split_bps_to_professional is required for SPLIT only.", code="INVALID_SPLIT")
    await bookings.lock_booking(session, dispute.booking_id)
    dispute = await _get(session, dispute_id, for_update=True)
    escrow = await payments_repository.escrow(session, dispute.escrow_id, for_update=True)
    assert escrow is not None
    if dispute.status not in {DisputeStatus.UNDER_REVIEW.value, DisputeStatus.AWAITING_SETTLEMENT.value}:
        raise Conflict("Only a dispute locked on-chain can be resolved.", code="DISPUTE_NOT_LOCKED")
    if escrow.state != EscrowState.DISPUTED.value:
        raise Conflict("The escrow is not disputed on-chain.", code="DISPUTE_NOT_LOCKED")
    assert services.settings.stellar_operator_address is not None
    arbiter = (await gateway.get_config(services.settings.stellar_operator_address)).arbiter
    wallet = await wallets.primary_address(session, admin.user_id, stellar.network)
    if wallet != arbiter:
        raise Forbidden("Your verified wallet is not the contract's arbiter.", code="ARBITER_WALLET_REQUIRED")
    units = int(escrow.asset_units)
    bps = {DisputeOutcome.RELEASE: 10_000, DisputeOutcome.REFUND: 0}.get(
        data.outcome, data.split_bps_to_professional or 0
    )
    professional_amount = split_amount(units, bps)
    if data.outcome is DisputeOutcome.SPLIT and not 0 < professional_amount < units:
        raise BadRequest(
            "This split rounds to a full release or refund; choose that outcome.", code="INVALID_SPLIT"
        )
    tx = await payments.prepare_tx(
        session, services, stellar, escrow=escrow, kind=TxKind.RESOLVE, source=wallet,
        function=Function.RESOLVE, args=contract.resolve_args(escrow.escrow_key, professional_amount),
        requested_by=admin.user_id,
        data={"outcome": data.outcome.value, "bps": bps, "professional_amount": str(professional_amount)},
        replace_prepared=True,
    )  # fmt: skip
    dispute.split_bps_to_professional = bps if data.outcome is DisputeOutcome.SPLIT else None
    dispute.resolution_note = data.note
    dispute.resolved_by = admin.user_id
    await audit.record(
        session, action="dispute.resolution_prepared", entity_type="dispute", entity_id=dispute.id,
        actor_user_id=admin.user_id,
        data={"outcome": data.outcome.value, "bps": bps, "professional_amount": str(professional_amount),
              "tx_hash": tx.tx_hash},
    )  # fmt: skip
    await session.commit()
    return DisputePreparedOut(
        dispute=await present(session, services, dispute),
        escrow=await payments.present(session, stellar, escrow),
        unsigned_xdr=tx.unsigned_envelope_xdr,
        tx_hash=tx.tx_hash,
        valid_until=tx.valid_until,
    )


# ---------------------------------------------------------------- reconciler hooks


async def on_locked(session: AsyncSession, c: ApplyContext) -> None:
    """``disputed`` confirmed: start the SLA clock (from the on-chain lock)."""
    dispute = await _active(session, c.booking.id, for_update=True)
    if dispute is None:  # opened outside UniFix (another wallet tool): record it
        opener = c.booking.customer_id
        if c.chain.disputed_by == c.escrow.professional_wallet:
            opener = await bookings.professional_user_id(session, c.booking)
        dispute = Dispute(
            booking_id=c.booking.id, escrow_id=c.escrow.id, opened_by=opener, reason="OTHER",
            details="Opened on-chain outside the UniFix app.", status=DisputeStatus.OPEN.value,
        )  # fmt: skip
        session.add(dispute)
    dispute.status = DisputeStatus.UNDER_REVIEW.value
    dispute.locked_at = c.now
    dispute.evidence_closes_at = c.now + EVIDENCE_WINDOW
    dispute.decision_due_at = c.now + DECISION_WINDOW
    await session.flush()
    await completion.on_disputed(session, c.booking.id, c.now)
    await audit.record(
        session, action="dispute.locked", entity_type="dispute", entity_id=dispute.id, actor_user_id=None,
        actor_type=ActorType.SYSTEM, data={"tx_hash": c.event.tx_hash},
    )  # fmt: skip


async def on_settled(session: AsyncSession, c: ApplyContext) -> None:
    """Any settlement: a locked dispute is RESOLVED with the outcome the chain records; a record
    whose lock never happened (the deadline settled the escrow first) is CLOSED."""
    dispute = await _active(session, c.booking.id, for_update=True)
    if dispute is None:
        return
    if dispute.status == DisputeStatus.OPEN.value:
        dispute.status = DisputeStatus.CLOSED.value
        dispute.resolved_at = c.now
        dispute.resolution_note = dispute.resolution_note or "Closed: the escrow settled before the lock."
        return
    payout, units = int(c.chain.professional_payout), int(c.chain.amount)
    outcome = {
        "CUSTOMER": DisputeOutcome.CONCEDED_RELEASE,
        "PROFESSIONAL": DisputeOutcome.CONCEDED_REFUND,
    }.get(c.chain.settled_by or "")
    if outcome is None:  # the arbiter
        outcome = (
            DisputeOutcome.RELEASE
            if payout == units
            else DisputeOutcome.REFUND
            if payout == 0
            else DisputeOutcome.SPLIT
        )
    if outcome is DisputeOutcome.SPLIT and (
        dispute.split_bps_to_professional is None
        or split_amount(units, dispute.split_bps_to_professional) != payout
    ):
        dispute.split_bps_to_professional = payout * 10_000 // units  # settled outside the prepared request
    if outcome is not DisputeOutcome.SPLIT:
        dispute.split_bps_to_professional = None
    dispute.status, dispute.outcome, dispute.resolved_at = DisputeStatus.RESOLVED.value, outcome.value, c.now
    await audit.record(
        session, action="dispute.resolved", entity_type="dispute", entity_id=dispute.id, actor_user_id=None,
        actor_type=ActorType.SYSTEM,
        data={"outcome": outcome.value, "professional_payout": str(payout), "tx_hash": c.event.tx_hash},
    )  # fmt: skip


async def escalate_overdue(services: Services) -> int:
    """Escalation ladder (no settlement): level 1 at day 7, level 2 at day 14 after the lock."""
    now = services.clock.now()
    changed = 0
    async with services.session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(Dispute)
                    .where(
                        Dispute.status.in_(
                            [DisputeStatus.UNDER_REVIEW.value, DisputeStatus.AWAITING_SETTLEMENT.value]
                        ),
                        Dispute.locked_at.is_not(None),
                        Dispute.escalation_level < len(ESCALATIONS),
                    )
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for dispute in rows:
            assert dispute.locked_at is not None
            level = sum(1 for after in ESCALATIONS if now >= dispute.locked_at + after)
            if level > dispute.escalation_level:
                dispute.escalation_level, dispute.escalated_at = level, now
                changed += 1
                await audit.record(
                    session, action="dispute.escalated", entity_type="dispute", entity_id=dispute.id,
                    actor_user_id=None, actor_type=ActorType.SYSTEM, data={"level": level},
                )  # fmt: skip
                await _notify_escalation(session, dispute, level)
        await session.commit()
    return changed


EscalationListener = Callable[[AsyncSession, Dispute, int], Awaitable[None]]
_escalation_listener: EscalationListener | None = None


def register_escalation_listener(listener: EscalationListener) -> None:
    """Notifications (Issue 8) subscribe to escalations."""
    global _escalation_listener
    _escalation_listener = listener


async def _notify_escalation(session: AsyncSession, dispute: Dispute, level: int) -> None:
    if _escalation_listener is not None:
        await _escalation_listener(session, dispute, level)
