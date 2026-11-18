from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments.models import (
    IN_FLIGHT,
    TERMINAL_ESCROW_STATES,
    CancellationRequest,
    CancellationStatus,
    ChainEvent,
    ChainSyncState,
    ChainTransaction,
    Escrow,
    EscrowState,
    EventStatus,
    LedgerEntry,
    Receipt,
    TxKind,
    TxStatus,
)

_IN_FLIGHT = [s.value for s in IN_FLIGHT]
_TERMINAL = [s.value for s in TERMINAL_ESCROW_STATES]


def add(session: AsyncSession, row: Any) -> None:
    session.add(row)


def _lock(statement: Any, for_update: bool) -> Any:
    return statement.with_for_update() if for_update else statement


async def escrow_for_booking(
    session: AsyncSession, booking_id: uuid.UUID, *, for_update: bool = False
) -> Escrow | None:
    statement = _lock(select(Escrow).where(Escrow.booking_id == booking_id), for_update)
    return (await session.execute(statement)).scalar_one_or_none()


async def escrows_for_bookings(
    session: AsyncSession, booking_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, Escrow]:
    if not booking_ids:
        return {}
    rows = (await session.execute(select(Escrow).where(Escrow.booking_id.in_(booking_ids)))).scalars()
    return {row.booking_id: row for row in rows}


async def escrow(session: AsyncSession, escrow_id: uuid.UUID, *, for_update: bool = False) -> Escrow | None:
    statement = _lock(select(Escrow).where(Escrow.id == escrow_id), for_update)
    return (await session.execute(statement)).scalar_one_or_none()


async def escrow_by_key(session: AsyncSession, key: bytes, *, for_update: bool = False) -> Escrow | None:
    statement = _lock(select(Escrow).where(Escrow.escrow_key == key), for_update)
    return (await session.execute(statement)).scalar_one_or_none()


async def open_escrows(session: AsyncSession) -> Sequence[Escrow]:
    """Every escrow that exists or may exist on-chain and is not terminal (full sweep)."""
    return (await session.execute(select(Escrow).where(Escrow.state.not_in(_TERMINAL)))).scalars().all()


async def wallet_in_active_escrow(session: AsyncSession, address: str) -> bool:
    statement = select(Escrow.id).where(
        or_(Escrow.customer_wallet == address, Escrow.professional_wallet == address),
        Escrow.state.not_in(_TERMINAL),
    )
    return (await session.execute(statement.limit(1))).first() is not None


async def in_flight(
    session: AsyncSession, escrow_id: uuid.UUID, kind: TxKind, *, for_update: bool = False
) -> ChainTransaction | None:
    statement = select(ChainTransaction).where(
        ChainTransaction.escrow_id == escrow_id,
        ChainTransaction.kind == kind.value,
        ChainTransaction.status.in_(_IN_FLIGHT),
    )
    return (await session.execute(_lock(statement, for_update))).scalar_one_or_none()


async def any_in_flight(session: AsyncSession, escrow_id: uuid.UUID) -> Sequence[ChainTransaction]:
    statement = select(ChainTransaction).where(
        ChainTransaction.escrow_id == escrow_id, ChainTransaction.status.in_(_IN_FLIGHT)
    )
    return (await session.execute(statement)).scalars().all()


async def expire_stale_prepared(session: AsyncSession, escrow_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(ChainTransaction)
        .where(
            ChainTransaction.escrow_id == escrow_id,
            ChainTransaction.status == TxStatus.PREPARED.value,
            ChainTransaction.valid_until <= now,
        )
        .values(status=TxStatus.EXPIRED.value, error="Not signed before the transaction expired")
    )


async def tx(session: AsyncSession, tx_id: uuid.UUID, *, for_update: bool = False) -> ChainTransaction | None:
    statement = _lock(select(ChainTransaction).where(ChainTransaction.id == tx_id), for_update)
    return (await session.execute(statement)).scalar_one_or_none()


async def tx_by_hash(
    session: AsyncSession, tx_hash: str, *, for_update: bool = False
) -> ChainTransaction | None:
    statement = _lock(select(ChainTransaction).where(ChainTransaction.tx_hash == tx_hash), for_update)
    return (await session.execute(statement)).scalar_one_or_none()


async def transactions(session: AsyncSession, escrow_ids: Sequence[uuid.UUID]) -> Sequence[ChainTransaction]:
    if not escrow_ids:
        return []
    statement = (
        select(ChainTransaction)
        .where(ChainTransaction.escrow_id.in_(escrow_ids))
        .order_by(ChainTransaction.created_at, ChainTransaction.id)
    )
    return (await session.execute(statement)).scalars().all()


async def txs_to_poll(session: AsyncSession, limit: int) -> Sequence[ChainTransaction]:
    statement = (
        select(ChainTransaction)
        .where(ChainTransaction.status.in_([TxStatus.SUBMITTED.value, TxStatus.PENDING.value]))
        .order_by(ChainTransaction.last_checked_at.asc().nulls_first())
        .limit(limit)
    )
    return (await session.execute(statement)).scalars().all()


async def insert_events(session: AsyncSession, rows: list[dict[str, Any]]) -> list[uuid.UUID]:
    """``INSERT … ON CONFLICT (tx_hash, event_index) DO NOTHING RETURNING id``: only new rows."""
    if not rows:
        return []
    statement = (
        insert(ChainEvent)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["tx_hash", "event_index"])
        .returning(ChainEvent.id)
    )
    return list((await session.execute(statement)).scalars().all())


async def pending_events(session: AsyncSession, limit: int) -> Sequence[uuid.UUID]:
    statement = (
        select(ChainEvent.id)
        .where(ChainEvent.status == EventStatus.INGESTED.value)
        .order_by(ChainEvent.ledger, ChainEvent.tx_index, ChainEvent.event_index)
        .limit(limit)
    )
    return (await session.execute(statement)).scalars().all()


async def event(session: AsyncSession, event_id: uuid.UUID, *, for_update: bool = False) -> ChainEvent | None:
    statement = _lock(select(ChainEvent).where(ChainEvent.id == event_id), for_update)
    return (await session.execute(statement)).scalar_one_or_none()


async def sync_state(session: AsyncSession, contract_id: str, now: datetime) -> ChainSyncState:
    """The cursor row for a contract, locked for this transaction (created on first use)."""
    await session.execute(
        insert(ChainSyncState).values(contract_id=contract_id, updated_at=now).on_conflict_do_nothing()
    )
    statement = select(ChainSyncState).where(ChainSyncState.contract_id == contract_id).with_for_update()
    return (await session.execute(statement)).scalar_one()


async def read_sync_state(session: AsyncSession, contract_id: str) -> ChainSyncState | None:
    statement = select(ChainSyncState).where(ChainSyncState.contract_id == contract_id)
    return (await session.execute(statement)).scalar_one_or_none()


async def next_receipt_number(session: AsyncSession, year: int) -> str:
    value: int = (await session.execute(text("SELECT nextval('receipt_number_seq')"))).scalar_one()
    return f"UFX-{year}-{int(value):06d}"


async def receipts(session: AsyncSession, booking_id: uuid.UUID) -> Sequence[Receipt]:
    statement = (
        select(Receipt).where(Receipt.booking_id == booking_id).order_by(Receipt.issued_at, Receipt.number)
    )
    return (await session.execute(statement)).scalars().all()


async def ledger_entries(session: AsyncSession, booking_id: uuid.UUID) -> Sequence[LedgerEntry]:
    statement = (
        select(LedgerEntry).where(LedgerEntry.booking_id == booking_id).order_by(LedgerEntry.created_at)
    )
    return (await session.execute(statement)).scalars().all()


async def keeper_candidates(session: AsyncSession, *, mature_before: int, limit: int) -> Sequence[Escrow]:
    """Undisputed escrows whose deadline matured: never selects DISPUTED (D16b)."""
    statement = (
        select(Escrow)
        .where(
            or_(
                (Escrow.state == EscrowState.FUNDED.value) & (Escrow.refund_after <= mature_before),
                (Escrow.state == EscrowState.COMPLETION_SUBMITTED.value)
                & (Escrow.review_deadline <= mature_before),
            )
        )
        .limit(limit)
    )
    return (await session.execute(statement)).scalars().all()


async def open_cancellation(
    session: AsyncSession, booking_id: uuid.UUID, *, for_update: bool = False
) -> CancellationRequest | None:
    statement = select(CancellationRequest).where(
        CancellationRequest.booking_id == booking_id,
        CancellationRequest.status == CancellationStatus.OPEN.value,
    )
    return (await session.execute(_lock(statement, for_update))).scalar_one_or_none()


async def cancellation(
    session: AsyncSession, request_id: uuid.UUID, *, for_update: bool = False
) -> CancellationRequest | None:
    statement = _lock(select(CancellationRequest).where(CancellationRequest.id == request_id), for_update)
    return (await session.execute(statement)).scalar_one_or_none()


async def latest_cancellation(session: AsyncSession, booking_id: uuid.UUID) -> CancellationRequest | None:
    statement = (
        select(CancellationRequest)
        .where(CancellationRequest.booking_id == booking_id)
        .order_by(CancellationRequest.created_at.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalar_one_or_none()
