from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bookings.models import ACTIVE_STATUSES, Booking
from app.modules.quotes.models import Agreement, Quote, QuoteStatus


def add(session: AsyncSession, row: Quote | Agreement) -> None:
    session.add(row)


async def get(session: AsyncSession, quote_id: uuid.UUID, *, for_update: bool = False) -> Quote | None:
    statement = select(Quote).where(Quote.id == quote_id)
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def next_version(session: AsyncSession, conversation_id: uuid.UUID) -> int:
    current = await session.scalar(
        select(func.max(Quote.version)).where(Quote.conversation_id == conversation_id)
    )
    return int(current or 0) + 1


async def pending_in_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> Quote | None:
    statement = select(Quote).where(
        Quote.conversation_id == conversation_id, Quote.status == QuoteStatus.PENDING.value
    )
    return (await session.execute(statement.with_for_update())).scalar_one_or_none()


async def for_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> Sequence[Quote]:
    statement = select(Quote).where(Quote.conversation_id == conversation_id).order_by(Quote.version)
    return (await session.execute(statement)).scalars().all()


async def reject_other_pending(
    session: AsyncSession, service_request_id: uuid.UUID, keep: uuid.UUID, now: object
) -> int:
    result = await session.execute(
        update(Quote)
        .where(
            Quote.service_request_id == service_request_id,
            Quote.status == QuoteStatus.PENDING.value,
            Quote.id != keep,
        )
        .values(status=QuoteStatus.REJECTED.value, responded_at=now)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def agreements_by_quote(
    session: AsyncSession, quote_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, Agreement]:
    if not quote_ids:
        return {}
    rows = (await session.execute(select(Agreement).where(Agreement.quote_id.in_(quote_ids)))).scalars().all()
    return {row.quote_id: row for row in rows}


async def get_agreement(session: AsyncSession, agreement_id: uuid.UUID) -> Agreement | None:
    return await session.get(Agreement, agreement_id)


async def has_active_booking(session: AsyncSession, conversation_id: uuid.UUID) -> bool:
    statement = select(Booking.id).where(
        Booking.conversation_id == conversation_id, Booking.status.in_([s.value for s in ACTIVE_STATUSES])
    )
    return (await session.execute(statement.limit(1))).first() is not None
