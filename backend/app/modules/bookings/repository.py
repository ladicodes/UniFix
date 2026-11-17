from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bookings.models import ACTIVE_STATUSES, Booking, BookingEvent


def add(session: AsyncSession, row: Booking | BookingEvent) -> None:
    session.add(row)


async def get(session: AsyncSession, booking_id: uuid.UUID, *, for_update: bool = False) -> Booking | None:
    statement = select(Booking).where(Booking.id == booking_id)
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def list_for(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID | None,
    professional_id: uuid.UUID | None,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[Booking], int]:
    conditions = []
    participants = []
    if customer_id is not None:
        participants.append(Booking.customer_id == customer_id)
    if professional_id is not None:
        participants.append(Booking.professional_id == professional_id)
    if participants:
        conditions.append(or_(*participants))
    if status is not None:
        conditions.append(Booking.status == status)
    rows = (
        (
            await session.execute(
                select(Booking)
                .where(*conditions)
                .order_by(Booking.created_at.desc(), Booking.id)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    total = int(
        (await session.execute(select(func.count()).select_from(Booking).where(*conditions))).scalar_one()
    )
    return rows, total


async def timeline(
    session: AsyncSession, booking_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[BookingEvent]]:
    result: dict[uuid.UUID, list[BookingEvent]] = {bid: [] for bid in booking_ids}
    if not booking_ids:
        return result
    statement = (
        select(BookingEvent).where(BookingEvent.booking_id.in_(booking_ids)).order_by(BookingEvent.seq)
    )
    for event in (await session.execute(statement)).scalars().all():
        result[event.booking_id].append(event)
    return result


async def active_by_conversation(
    session: AsyncSession, conversation_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    if not conversation_ids:
        return {}
    statement = select(Booking.conversation_id, Booking.id).where(
        Booking.conversation_id.in_(conversation_ids), Booking.status.in_([s.value for s in ACTIVE_STATUSES])
    )
    return {row[0]: row[1] for row in (await session.execute(statement)).all()}
