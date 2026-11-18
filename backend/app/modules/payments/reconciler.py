"""The reconciler: the only path from chain data to financial state (STELLAR_ESCROW_DESIGN §10).

Delivery is at least once and application is idempotent, so the effect is exactly once:

1. **Ingest** — confirmed transactions and the cursor scan both read events through ``getEvents``
   and insert into ``chain_events`` with ``ON CONFLICT (tx_hash, event_index) DO NOTHING``. The
   scan's cursor advances in the same DB transaction as the page it covers.
2. **Apply** — one DB transaction per event: lock event → booking → escrow, re-read ``get_escrow``
   (authoritative), verify the full terms binding, apply the transition, ledger entries, receipt,
   timeline and audit, mark the event. A state never regresses; a crash rolls everything back.
3. **Keeper** — submits the permissionless ``finalize_expired`` for matured *undisputed*
   deadlines only (D16b). It never selects a disputed escrow.

Every piece of state lives in PostgreSQL. The advisory-lock leader election is an efficiency
measure: two overlapping reconcilers still apply each event once (row locks + unique keys).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import socket
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from stellar_sdk import TransactionEnvelope

from app.core.container import Services
from app.modules.audit import service as audit
from app.modules.audit.models import ActorType
from app.modules.bookings import service as bookings
from app.modules.bookings.models import Booking, BookingStatus, TimelineActor
from app.modules.chat import service as chat
from app.modules.payments import repository
from app.modules.payments import service as payments
from app.modules.payments.models import (
    ChainEvent,
    ChainTransaction,
    Escrow,
    EscrowState,
    EventSource,
    EventStatus,
    LedgerEntry,
    LedgerEntryType,
    Receipt,
    ReceiptKind,
    TxKind,
    TxStatus,
)
from app.modules.quotes import agreement as agreements
from app.modules.quotes import repository as quotes_repository
from app.modules.stellar import contract
from app.modules.stellar.context import StellarContext
from app.modules.stellar.contract import Function, OnchainEscrow, OnchainStatus
from app.modules.stellar.errors import ChainRejected, ChainUnavailable

logger = logging.getLogger(__name__)

RECONCILER_LOCK_ID = 0x554E4946  # "UNIF"
EXPIRY_MARGIN_SECONDS = 15  # timebounds + ~2 ledgers before NOT_FOUND means "never landed"
PAGE_LIMIT = 100

_RANK = {
    EscrowState.CREATED: 0,
    EscrowState.FUNDED: 1,
    EscrowState.COMPLETION_SUBMITTED: 2,
    EscrowState.DISPUTED: 3,
    EscrowState.RELEASED: 4,
    EscrowState.REFUNDED: 4,
    EscrowState.RESOLVED: 4,
}
_CHAIN_STATE = {
    OnchainStatus.FUNDED: EscrowState.FUNDED,
    OnchainStatus.COMPLETION_SUBMITTED: EscrowState.COMPLETION_SUBMITTED,
    OnchainStatus.DISPUTED: EscrowState.DISPUTED,
    OnchainStatus.RELEASED: EscrowState.RELEASED,
    OnchainStatus.REFUNDED: EscrowState.REFUNDED,
    OnchainStatus.RESOLVED: EscrowState.RESOLVED,
}

# Hooks wired in app.api.v1 (completion and disputes sit above payments in the module graph).
CompletionHook = Callable[[AsyncSession, uuid.UUID, str | None, datetime], Awaitable[None]]
_completion_submitted: CompletionHook | None = None
_completion_released: CompletionHook | None = None
DisputeHook = Callable[[AsyncSession, "ApplyContext"], Awaitable[None]]
_dispute_hooks: dict[str, DisputeHook] = {}


def register_completion_hooks(*, submitted: CompletionHook, released: CompletionHook) -> None:
    global _completion_submitted, _completion_released
    _completion_submitted, _completion_released = submitted, released


PeriodicJob = Callable[[Services], Awaitable[int]]
_periodic: list[PeriodicJob] = []


def register_periodic(job: PeriodicJob) -> None:
    """Idempotent jobs run once per leader tick (e.g. dispute escalation, deadline notifications)."""
    if job not in _periodic:
        _periodic.append(job)


def register_dispute_hook(event: str, hook: DisputeHook) -> None:
    """Issue 7: ``disputed`` (lock confirmed) and ``settled`` (a disputed escrow settled)."""
    _dispute_hooks[event] = hook


@dataclass
class ApplyContext:
    services: Services
    stellar: StellarContext
    event: ChainEvent
    escrow: Escrow
    booking: Booking
    chain: OnchainEscrow
    now: datetime
    outcome: str = EventStatus.APPLIED.value


class Conflicting(Exception):
    """The event contradicts the chain or the agreement: mark CONFLICT and alert, change nothing."""


# ---------------------------------------------------------------- the reconciler


class Reconciler:
    def __init__(self, services: Services, stellar: StellarContext, *, hub: Any = None) -> None:
        self.services = services
        self.stellar = stellar
        self.hub = hub

    @property
    def contract_id(self) -> str:
        return self.stellar.require().contract_id

    async def tick(self) -> None:
        """One full pass. Safe to run concurrently with itself and with request handlers."""
        await self.poll_transactions()
        await self.scan_events()
        await self.apply_pending()
        await self.run_keeper()
        for job in list(_periodic):
            await job(self.services)

    # ---- 1. our own transactions

    async def poll_transactions(self) -> None:
        async with self.services.session_factory() as session:
            ids = [t.id for t in await repository.txs_to_poll(session, PAGE_LIMIT)]
        for tx_id in ids:
            try:
                await self._poll_one(tx_id)
            except ChainUnavailable:
                await self._record_error("RPC unavailable while polling transactions")
                return

    async def _poll_one(self, tx_id: uuid.UUID) -> None:
        gateway = self.stellar.require()
        async with self.services.session_factory() as session:
            tx = await repository.tx(session, tx_id)
            if tx is None or tx.status not in {TxStatus.SUBMITTED.value, TxStatus.PENDING.value}:
                return
            tx_hash, signed, valid_until = tx.tx_hash, tx.signed_envelope_xdr, tx.valid_until
        status = await gateway.get_transaction(tx_hash)
        now = self.services.clock.now()
        if status.status == "SUCCESS":
            assert status.ledger is not None
            await self._ingest_ledger(status.ledger, only_tx=tx_hash, source=EventSource.TX_RESULT)
        elif status.status == "NOT_FOUND" and now.timestamp() <= valid_until.timestamp() and signed:
            # Unknown send outcome (e.g. RPC was down): resending is harmless (DUPLICATE).
            envelope = TransactionEnvelope.from_xdr(signed, self.stellar.passphrase)
            await payments.send(self.services, self.stellar, tx_id, envelope)
        async with self.services.session_factory() as session:
            tx = await repository.tx(session, tx_id, for_update=True)
            if tx is None or tx.status not in {TxStatus.SUBMITTED.value, TxStatus.PENDING.value}:
                return
            tx.last_checked_at = now
            if status.status == "SUCCESS":
                tx.status, tx.ledger, tx.ledger_closed_at = (
                    TxStatus.CONFIRMED.value,
                    status.ledger,
                    status.closed_at,
                )
                tx.fee_stroops = Decimal(status.fee_stroops) if status.fee_stroops is not None else None
                tx.confirmed_at = now
            elif status.status == "FAILED":
                tx.status, tx.ledger, tx.result_code = TxStatus.FAILED.value, status.ledger, "TX_FAILED"
                tx.error = status.error
            elif now.timestamp() > valid_until.timestamp() + EXPIRY_MARGIN_SECONDS:
                tx.status, tx.error = TxStatus.EXPIRED.value, "Never included before its time bounds expired"
            else:
                await session.commit()
                return
            escrow = await repository.escrow(session, tx.escrow_id, for_update=True)
            assert escrow is not None
            if tx.kind == TxKind.FUND.value and tx.status != TxStatus.CONFIRMED.value:
                escrow.failure_reason = f"The funding transaction {tx.status.lower()}; prepare it again."
            await payments.refresh_reconciliation(session, escrow)
            await session.commit()

    # ---- 2. ingestion

    async def _ingest_ledger(self, ledger: int, *, only_tx: str | None, source: EventSource) -> int:
        """Ingest our contract's events from one ledger (the fast path for a confirmed tx)."""
        gateway = self.stellar.require()
        page = await gateway.get_events(start_ledger=ledger, cursor=None, limit=PAGE_LIMIT)
        rows = [
            self._row(e, source) for e in page.events if e.ledger == ledger and (only_tx in {None, e.tx_hash})
        ]
        async with self.services.session_factory() as session:
            inserted = await repository.insert_events(session, [r for r in rows if r is not None])
            await session.commit()
        return len(inserted)

    def _row(self, raw: Any, source: EventSource) -> dict[str, Any] | None:
        decoded = contract.decode_event(raw.topics, raw.value)
        if decoded is None:
            return None
        return {
            "id": uuid.uuid4(),
            "contract_id": raw.contract_id,
            "ledger": raw.ledger,
            "ledger_closed_at": raw.ledger_closed_at,
            "tx_hash": raw.tx_hash,
            "tx_index": raw.tx_index,
            "event_index": raw.event_index,
            "event_type": decoded.name,
            "escrow_key": decoded.escrow_key,
            "payload": decoded.payload,
            "status": EventStatus.INGESTED.value,
            "source": source.value,
            "ingested_at": self.services.clock.now(),
        }

    async def scan_events(self, *, max_pages: int = 20) -> None:
        gateway = self.stellar.require()
        for _ in range(max_pages):
            async with self.services.session_factory() as session:
                state = await repository.sync_state(session, self.contract_id, self.services.clock.now())
                last_ledger, cursor = state.last_ledger, state.cursor
                try:
                    health = await gateway.health()
                    if health.oldest_ledger is None:
                        raise ChainUnavailable()
                    if last_ledger is not None and last_ledger < health.oldest_ledger:
                        # The RPC no longer holds events we have not seen (~7-day retention).
                        await session.rollback()
                        logger.warning("reconciler.retention_gap", extra={"last_ledger": last_ledger})
                        await self.full_sweep(reset_cursor_to=health.oldest_ledger)
                        return
                    if cursor is None:
                        start = max(health.oldest_ledger, self.services.settings.reconciler_start_ledger or 0)
                        page = await gateway.get_events(start_ledger=start, cursor=None, limit=PAGE_LIMIT)
                    else:
                        page = await gateway.get_events(start_ledger=None, cursor=cursor, limit=PAGE_LIMIT)
                except ChainUnavailable:
                    await session.rollback()
                    await self._record_error("RPC unavailable during the event scan")
                    return
                rows = [
                    r for r in (self._row(e, EventSource.EVENT_SCAN) for e in page.events) if r is not None
                ]
                await repository.insert_events(session, rows)
                state.cursor = page.cursor
                # Covered ledgers: up to the newest event seen, or to the tip once a page is empty.
                state.last_ledger = (
                    max(e.ledger for e in page.events)
                    if page.events
                    else max(page.latest_ledger, last_ledger or 0)
                )
                state.updated_at = self.services.clock.now()
                await session.commit()  # the cursor moves with the events it covers
            if not page.events:
                return

    # ---- 3. application

    async def apply_pending(self, *, limit: int = 500) -> int:
        async with self.services.session_factory() as session:
            ids = await repository.pending_events(session, limit)
        applied = 0
        for event_id in ids:
            try:
                applied += await self.apply_event(event_id)
            except ChainUnavailable:
                await self._record_error("RPC unavailable while applying events")
                break
        return applied

    async def apply_event(self, event_id: uuid.UUID) -> int:
        """Apply one ingested event in one DB transaction. Returns 1 if it changed anything."""
        gateway = self.stellar.require()
        async with self.services.session_factory() as session:
            event = await repository.event(session, event_id, for_update=True)
            if event is None or event.status != EventStatus.INGESTED.value:
                return 0  # already handled (by us earlier, or by a concurrent reconciler)
            now = self.services.clock.now()
            escrow = await repository.escrow_by_key(session, event.escrow_key) if event.escrow_key else None
            if escrow is None:
                event.status, event.applied_at = EventStatus.APPLIED_NOOP.value, now
                event.error = "Not a UniFix escrow (or a configuration event)"
                await session.commit()
                return 0
            handler = _HANDLERS.get(event.event_type)
            if handler is None or (
                event.event_type in {"disputed", "resolved"} and "disputed" not in _dispute_hooks
            ):
                event.error = f"No handler for '{event.event_type}' yet; left for a later release"
                await session.commit()
                return 0
            escrow_id = escrow.id
            booking = await bookings.lock_booking(session, escrow.booking_id)
            escrow = await repository.escrow(session, escrow_id, for_update=True)
            assert escrow is not None
            chain = await gateway.get_escrow(escrow.escrow_key)
            context = (
                ApplyContext(self.services, self.stellar, event, escrow, booking, chain, now)
                if chain
                else None
            )
            try:
                if context is None:
                    raise Conflicting("The escrow does not exist on-chain")
                await _verify_binding(session, context)
                await handler(session, context)
            except Conflicting as conflict:
                await session.rollback()
                return await self._mark_conflict(event_id, str(conflict), escrow_id=escrow_id)
            event.status, event.applied_at = context.outcome, now
            escrow.last_synced_ledger, escrow.last_synced_at = event.ledger, now
            await payments.refresh_reconciliation(session, escrow)
            await session.commit()
            changed = context.outcome == EventStatus.APPLIED.value
        if changed:
            await self._publish(context)
        return int(changed)

    async def _mark_conflict(self, event_id: uuid.UUID, reason: str, *, escrow_id: uuid.UUID) -> int:
        async with self.services.session_factory() as session:
            event = await repository.event(session, event_id, for_update=True)
            assert event is not None
            event.status, event.error, event.applied_at = (
                EventStatus.CONFLICT.value,
                reason,
                self.services.clock.now(),
            )
            escrow = await repository.escrow(session, escrow_id, for_update=True)
            assert escrow is not None
            if reason.startswith("FAILED_VERIFICATION"):
                escrow.verification_error = reason
                await payments.refresh_reconciliation(session, escrow)
            await audit.record(
                session,
                action="chain.event_conflict",
                entity_type="booking",
                entity_id=escrow.booking_id,
                actor_user_id=None,
                actor_type=ActorType.SYSTEM,
                data={"event": event.event_type, "tx_hash": event.tx_hash, "reason": reason},
            )
            await session.commit()
        logger.error("reconciler.conflict", extra={"event_id": str(event_id), "reason": reason})
        return 0

    async def _publish(self, context: ApplyContext) -> None:
        """After commit: tell connected clients to refetch the booking."""
        if self.hub is not None:
            await chat.publish_event(
                self.hub,
                context.booking.conversation_id,
                "BOOKING_UPDATED",
                {"booking_id": str(context.booking.id), "status": context.booking.status},
            )

    # ---- 4. keeper

    async def run_keeper(self) -> None:
        delay = self.services.settings.keeper_delay_seconds
        mature_before = int(self.services.clock.now().timestamp()) - delay
        async with self.services.session_factory() as session:
            candidates = [
                e.id
                for e in await repository.keeper_candidates(
                    session, mature_before=mature_before, limit=PAGE_LIMIT
                )
            ]
        for escrow_id in candidates:
            try:
                await self._finalize(escrow_id)
            except ChainUnavailable:
                await self._record_error("RPC unavailable while running the keeper")
                return

    async def _finalize(self, escrow_id: uuid.UUID) -> None:
        settings = self.services.settings
        operator = self.stellar.operator()
        async with self.services.session_factory() as session:
            escrow = await repository.escrow(session, escrow_id, for_update=True)
            if escrow is None or escrow.state not in {
                EscrowState.FUNDED.value,
                EscrowState.COMPLETION_SUBMITTED.value,
            }:
                return
            if await repository.in_flight(session, escrow.id, TxKind.FINALIZE) is not None:
                return
            lock = await repository.in_flight(session, escrow.id, TxKind.DISPUTE)
            if lock is not None and lock.status != TxStatus.PREPARED.value:
                return  # a signed dispute lock is landing; let the chain decide which comes first
            now = self.services.clock.now()
            try:
                prepared = await self.stellar.require().prepare_call(
                    source=operator.public_key,
                    function=Function.FINALIZE_EXPIRED,
                    args=contract.escrow_only_args(escrow.escrow_key),
                    valid_until=int(now.timestamp()) + settings.escrow_tx_valid_seconds,
                )
            except ChainRejected as rejected:  # e.g. NotExpired (ledger clock behind) or already settled
                logger.info(
                    "keeper.not_finalizable", extra={"escrow_id": str(escrow_id), "code": rejected.code}
                )
                return
            prepared.envelope.sign(operator)
            tx = ChainTransaction(
                escrow_id=escrow.id,
                kind=TxKind.FINALIZE.value,
                tx_hash=prepared.tx_hash,
                source_account=operator.public_key,
                unsigned_envelope_xdr=prepared.xdr,
                signed_envelope_xdr=prepared.envelope.to_xdr(),
                valid_until=datetime.fromtimestamp(prepared.valid_until, UTC),
                status=TxStatus.SUBMITTED.value,
                submitted_at=now,
                attempts=1,
                requested_by=None,
            )
            repository.add(session, tx)
            try:
                await session.flush()
            except IntegrityError:  # another keeper won the in-flight slot (partial unique index)
                await session.rollback()
                return
            await payments.refresh_reconciliation(session, escrow)
            await session.commit()
            tx_id = tx.id
        await payments.send(self.services, self.stellar, tx_id, prepared.envelope)

    # ---- full sweep (retention gap, or `app.cli reconcile --full`)

    async def full_sweep(self, *, reset_cursor_to: int | None = None) -> int:
        """Compare every open escrow with ``get_escrow`` and apply the differences as synthetic
        STATE_SYNC events through the same idempotent apply."""
        gateway = self.stellar.require()
        latest = await gateway.latest_ledger()
        async with self.services.session_factory() as session:
            escrows = list(await repository.open_escrows(session))
        rows: list[dict[str, Any]] = []
        for escrow in escrows:
            chain = await gateway.get_escrow(escrow.escrow_key)
            if chain is None:
                continue
            rows.extend(_synthetic_events(escrow, chain, latest, self.services.clock.now()))
        async with self.services.session_factory() as session:
            await repository.insert_events(session, rows)
            if reset_cursor_to is not None:
                state = await repository.sync_state(session, self.contract_id, self.services.clock.now())
                state.cursor, state.last_ledger = None, reset_cursor_to
            await session.commit()
        return await self.apply_pending()

    async def _record_error(self, message: str) -> None:
        logger.warning("reconciler.error", extra={"error": message})
        async with self.services.session_factory() as session:
            state = await repository.sync_state(session, self.contract_id, self.services.clock.now())
            state.last_error, state.last_error_at = message, self.services.clock.now()
            await session.commit()


def _synthetic_events(
    escrow: Escrow, chain: OnchainEscrow, ledger: int, now: datetime
) -> list[dict[str, Any]]:
    """The missing steps between the DB mirror and the chain, oldest first."""
    target = _CHAIN_STATE[chain.status]
    current = EscrowState(escrow.state)
    steps: list[tuple[str, dict[str, Any]]] = []
    if _RANK[current] < 1:
        steps.append(
            (
                "funded",
                {
                    "amount": chain.amount,
                    "refund_after": chain.refund_after,
                    "customer": chain.customer,
                    "professional": chain.professional,
                },
            )
        )
    if chain.review_deadline is not None and _RANK[current] < 2 and target is not EscrowState.DISPUTED:
        steps.append(
            (
                "completion_submitted",
                {"review_deadline": chain.review_deadline, "evidence_hash": chain.evidence_hash},
            )
        )
    if target is EscrowState.DISPUTED or (chain.disputed_at is not None and _RANK[current] < 3):
        steps.append(("disputed", {"disputed_at": chain.disputed_at, "disputed_by": chain.disputed_by}))
    if _RANK[target] == 4:
        name = {"ARBITER": "resolved", "TIMEOUT": "expired"}.get(chain.settled_by or "", target.value.lower())
        steps.append(
            (
                name,
                {
                    "professional_payout": chain.professional_payout,
                    "customer_refund": chain.customer_refund,
                    "settled_by": chain.settled_by,
                },
            )
        )
    rows = []
    for index, (name, payload) in enumerate(steps):
        seed = f"state-sync|{escrow.escrow_key.hex()}|{name}|{chain.status.value}|{chain.refund_after}"
        rows.append(
            {
                "id": uuid.uuid4(),
                "contract_id": escrow.contract_id,
                "ledger": ledger,
                "ledger_closed_at": now,
                "tx_hash": hashlib.sha256(seed.encode()).hexdigest(),
                "tx_index": 0,
                "event_index": index,
                "event_type": name,
                "escrow_key": escrow.escrow_key,
                "payload": payload,
                "status": EventStatus.INGESTED.value,
                "source": EventSource.STATE_SYNC.value,
                "ingested_at": now,
            }
        )
    return rows


# ---------------------------------------------------------------- verification and handlers


async def _verify_binding(session: AsyncSession, c: ApplyContext) -> None:
    """STELLAR_ESCROW_DESIGN §6: chain ↔ escrow row ↔ terms document ↔ agreement."""
    escrow, chain = c.escrow, c.chain
    problems = []
    if chain.customer != escrow.customer_wallet:
        problems.append("customer")
    if chain.professional != escrow.professional_wallet:
        problems.append("professional")
    if chain.amount != int(escrow.asset_units):
        problems.append("amount")
    if chain.review_window != escrow.review_window:
        problems.append("review_window")
    if (
        chain.terms_hash != escrow.terms_hash
        or agreements.digest(escrow.terms_canonical_json) != escrow.terms_hash
    ):
        problems.append("terms_hash")
    agreement = await quotes_repository.get_agreement(session, c.booking.agreement_id)
    if (
        agreement is None
        or payments.terms_document(escrow).get("agreement_hash") != agreement.agreement_hash
        or escrow.agreement_hash != agreement.agreement_hash
        or agreements.digest(agreement.canonical_json) != agreement.agreement_hash
    ):
        problems.append("agreement_hash")
    if c.event.event_type == "funded" and c.event.payload.get("refund_after") not in {
        None,
        escrow.refund_after,
    }:
        problems.append("refund_after")
    if problems:
        raise Conflicting("FAILED_VERIFICATION: on-chain escrow does not match " + ", ".join(problems))


def _advance(c: ApplyContext, target: EscrowState) -> bool:
    """True when the event moves the mirror forward; NOOP when the mirror is already there."""
    current = EscrowState(c.escrow.state)
    chain_rank = _RANK[_CHAIN_STATE[c.chain.status]]
    if _RANK[target] > chain_rank:
        raise Conflicting(
            f"Event '{c.event.event_type}' is ahead of the on-chain state {c.chain.status.value}"
        )
    if _RANK[current] >= _RANK[target]:
        c.outcome = EventStatus.APPLIED_NOOP.value
        return False
    return True


async def _booking_to(session: AsyncSession, c: ApplyContext, to: BookingStatus, label: str) -> None:
    if c.booking.status == to.value:
        return
    try:
        await bookings.transition(
            session,
            c.booking,
            to,
            actor=TimelineActor.CHAIN,
            actor_user_id=None,
            label=label,
            now=c.now,
            data={"tx_hash": c.event.tx_hash, "ledger": c.event.ledger},
        )
    except bookings.InvalidTransition as exc:
        raise Conflicting(f"Booking is {c.booking.status}; cannot apply '{c.event.event_type}'") from exc
    await chat.add_system_message(session, c.booking.conversation_id, label, now=c.now)


async def _confirm_tx(session: AsyncSession, c: ApplyContext) -> None:
    tx = await repository.tx_by_hash(session, c.event.tx_hash, for_update=True)
    if tx is not None and tx.status != TxStatus.CONFIRMED.value:
        tx.status, tx.ledger, tx.confirmed_at = TxStatus.CONFIRMED.value, c.event.ledger, c.now


def _ledger(c: ApplyContext, kind: LedgerEntryType, units: int, source: str, destination: str) -> LedgerEntry:
    return LedgerEntry(
        booking_id=c.booking.id,
        escrow_id=c.escrow.id,
        chain_event_id=c.event.id,
        type=kind.value,
        asset_units=Decimal(units),
        asset_code=c.escrow.asset_code,
        asset_issuer=c.escrow.asset_issuer,
        from_address=source,
        to_address=destination,
        tx_hash=c.event.tx_hash,
        ledger=c.event.ledger,
    )


async def _receipt(
    session: AsyncSession, c: ApplyContext, kind: ReceiptKind, units: int, extra: dict[str, Any]
) -> None:
    number = await repository.next_receipt_number(session, c.now.year)
    issued = c.now.replace(microsecond=0)
    payload = {
        "schema": "unifix.receipt.v1",
        "number": number,
        "kind": kind.value,
        "booking_id": str(c.booking.id),
        "escrow_id": c.escrow.escrow_key.hex(),
        "contract_id": c.escrow.contract_id,
        "asset": {
            "code": c.escrow.asset_code,
            "issuer": c.escrow.asset_issuer,
            "sac_contract_id": c.escrow.asset_sac_contract_id,
            "decimals": c.escrow.asset_decimals,
        },
        "asset_amount": str(units),
        "fiat": {"amount_minor": c.escrow.fiat_amount_minor, "currency": c.escrow.fiat_currency},
        "fx": {
            "rate": f"{c.escrow.fx_rate:.8f}",
            "source": c.escrow.fx_source,
            "is_demo_rate": c.escrow.is_demo_rate,
        },
        "terms_hash": c.escrow.terms_hash,
        "tx_hash": c.event.tx_hash,
        "ledger": c.event.ledger,
        "issued_at": issued.strftime("%Y-%m-%dT%H:%M:%SZ"),
        **extra,
    }
    canonical = agreements.canonicalize(payload)
    repository.add(
        session,
        Receipt(
            booking_id=c.booking.id,
            escrow_id=c.escrow.id,
            kind=kind.value,
            number=number,
            asset_units=Decimal(units),
            asset_code=c.escrow.asset_code,
            asset_issuer=c.escrow.asset_issuer,
            fiat_amount_minor=c.escrow.fiat_amount_minor,
            fiat_currency=c.escrow.fiat_currency,
            fx_rate=c.escrow.fx_rate,
            fx_source=c.escrow.fx_source,
            is_demo_rate=c.escrow.is_demo_rate,
            tx_hash=c.event.tx_hash,
            ledger=c.event.ledger,
            payload_canonical_json=canonical,
            payload_hash=agreements.digest(canonical),
            issued_at=issued,
        ),
    )


async def _on_funded(session: AsyncSession, c: ApplyContext) -> None:
    if not _advance(c, EscrowState.FUNDED):
        return
    c.escrow.state = EscrowState.FUNDED.value
    c.escrow.funded_at_chain = c.chain.funded_at
    c.escrow.failure_reason = None
    await _confirm_tx(session, c)
    repository.add(
        session,
        _ledger(
            c,
            LedgerEntryType.CUSTOMER_FUNDING,
            int(c.escrow.asset_units),
            c.escrow.customer_wallet,
            c.escrow.contract_id,
        ),
    )
    await _receipt(session, c, ReceiptKind.FUNDING, int(c.escrow.asset_units), {})
    await _booking_to(session, c, BookingStatus.FUNDED, "Payment confirmed on-chain; funds are in escrow")


async def _on_completion_submitted(session: AsyncSession, c: ApplyContext) -> None:
    if not _advance(c, EscrowState.COMPLETION_SUBMITTED):
        return
    c.escrow.state = EscrowState.COMPLETION_SUBMITTED.value
    c.escrow.review_deadline = c.chain.review_deadline
    c.escrow.evidence_hash = c.chain.evidence_hash
    await _confirm_tx(session, c)
    await _booking_to(
        session, c, BookingStatus.COMPLETION_SUBMITTED, "Completion submitted on-chain; review started"
    )
    if _completion_submitted is not None:
        await _completion_submitted(session, c.booking.id, c.chain.evidence_hash, c.now)


async def _on_extended(session: AsyncSession, c: ApplyContext) -> None:
    new = int(c.event.payload.get("refund_after") or 0)
    if new <= c.escrow.refund_after:
        c.outcome = EventStatus.APPLIED_NOOP.value
        return
    c.escrow.refund_after = new
    await _confirm_tx(session, c)
    await bookings.add_timeline_note(
        session,
        c.booking,
        label="Refund deadline extended",
        actor=TimelineActor.CHAIN,
        actor_user_id=None,
        now=c.now,
        data={"refund_after": new, "tx_hash": c.event.tx_hash},
    )


async def _on_settled(session: AsyncSession, c: ApplyContext) -> None:
    """released | refunded | expired | resolved: the terminal outcome, exactly as the chain records it."""
    target = _CHAIN_STATE[c.chain.status]
    if _RANK[target] != 4:
        raise Conflicting(f"'{c.event.event_type}' but the escrow is {c.chain.status.value} on-chain")
    if not _advance(c, target):
        return
    payout, refund = int(c.chain.professional_payout), int(c.chain.customer_refund)
    c.escrow.state = target.value
    c.escrow.settled_by = c.chain.settled_by
    c.escrow.professional_payout_units, c.escrow.customer_refund_units = Decimal(payout), Decimal(refund)
    await _confirm_tx(session, c)
    if payout:
        repository.add(
            session,
            _ledger(
                c,
                LedgerEntryType.PROFESSIONAL_PAYOUT,
                payout,
                c.escrow.contract_id,
                c.escrow.professional_wallet,
            ),
        )
    if refund:
        repository.add(
            session,
            _ledger(
                c, LedgerEntryType.CUSTOMER_REFUND, refund, c.escrow.contract_id, c.escrow.customer_wallet
            ),
        )
    split = {
        "professional_payout": str(payout),
        "customer_refund": str(refund),
        "settled_by": c.chain.settled_by,
    }
    if target is EscrowState.RELEASED:
        await _receipt(
            session,
            c,
            ReceiptKind.RELEASE if c.chain.settled_by != "ARBITER" else ReceiptKind.RESOLUTION,
            payout,
            split,
        )
        label = (
            "Payment released to the professional"
            if c.chain.settled_by != "TIMEOUT"
            else ("Review window ended; payment auto-released to the professional")
        )
        await _booking_to(session, c, BookingStatus.COMPLETED, label)
        await bookings.record_completed_job(session, c.booking)
        if _completion_released is not None:
            await _completion_released(session, c.booking.id, None, c.now)
    elif target is EscrowState.REFUNDED:
        await _receipt(
            session,
            c,
            ReceiptKind.REFUND if c.chain.settled_by != "ARBITER" else ReceiptKind.RESOLUTION,
            refund,
            split,
        )
        label = (
            "Refund deadline passed; customer refunded"
            if c.chain.settled_by == "TIMEOUT"
            else ("Customer refunded")
        )
        await _booking_to(session, c, BookingStatus.REFUNDED, label)
        if c.chain.settled_by == "PROFESSIONAL":
            await payments.accept_cancellation_on_refund(session, c.booking.id, c.now)
    else:
        await _receipt(session, c, ReceiptKind.RESOLUTION, payout + refund, split)
        await _booking_to(session, c, BookingStatus.RESOLVED, "Dispute resolved by the arbiter")
    if "settled" in _dispute_hooks:  # resolves a locked dispute, or closes a never-locked record
        await _dispute_hooks["settled"](session, c)


async def _on_disputed(session: AsyncSession, c: ApplyContext) -> None:
    if not _advance(c, EscrowState.DISPUTED):
        return
    c.escrow.state = EscrowState.DISPUTED.value
    c.escrow.disputed_at = c.chain.disputed_at
    await _confirm_tx(session, c)
    await _booking_to(
        session, c, BookingStatus.DISPUTED, "Dispute opened; the escrow is locked for arbitration"
    )
    await _dispute_hooks["disputed"](session, c)


_HANDLERS: dict[str, Callable[[AsyncSession, ApplyContext], Awaitable[None]]] = {
    "funded": _on_funded,
    "completion_submitted": _on_completion_submitted,
    "extended": _on_extended,
    "released": _on_settled,
    "refunded": _on_settled,
    "expired": _on_settled,
    "resolved": _on_settled,
    "disputed": _on_disputed,
}


# ---------------------------------------------------------------- the background loop


class ReconcilerLoop:
    """Every API process runs one; the PostgreSQL session advisory lock elects a single leader."""

    def __init__(self, reconciler: Reconciler) -> None:
        self.reconciler = reconciler
        self.instance = f"{socket.gethostname()}:{os.getpid()}"
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="unifix-reconciler")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task

    async def _run(self) -> None:
        services = self.reconciler.services
        # A dedicated, non-pooled connection: session advisory locks do not survive poolers.
        lock_engine = create_async_engine(
            services.settings.database_url, poolclass=NullPool, connect_args={"options": "-c timezone=UTC"}
        )
        connection: AsyncConnection | None = None
        interval = services.settings.reconciler_interval_seconds
        try:
            while not self._stop.is_set():
                try:
                    if connection is None:
                        connection = await lock_engine.connect()
                        leader = bool(
                            await connection.scalar(select(func.pg_try_advisory_lock(RECONCILER_LOCK_ID)))
                        )
                        if not leader:
                            await connection.close()
                            connection = None
                        else:
                            await self._claim_leadership()
                    if connection is not None:
                        await self.reconciler.tick()
                except Exception:
                    logger.exception("reconciler.tick_failed")
                    if connection is not None:
                        with contextlib.suppress(Exception):
                            await connection.close()
                        connection = None
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=interval)
        finally:
            if connection is not None:
                with contextlib.suppress(Exception):
                    await connection.close()
            await lock_engine.dispose()

    async def _claim_leadership(self) -> None:
        services = self.reconciler.services
        async with services.session_factory() as session:
            state = await repository.sync_state(session, self.reconciler.contract_id, services.clock.now())
            state.leader_instance, state.leader_since = self.instance, services.clock.now()
            await session.commit()
        logger.info("reconciler.leader", extra={"instance": self.instance})
