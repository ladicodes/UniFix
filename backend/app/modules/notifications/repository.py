from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification


async def add(session: AsyncSession, values: dict[str, Any]) -> None:
    """Insert one row; a repeated ``dedupe_key`` for the same user is silently skipped."""
    statement = pg_insert(Notification).values(id=uuid.uuid4(), **values)
    if values.get("dedupe_key") is not None:
        statement = statement.on_conflict_do_nothing(
            index_elements=["user_id", "dedupe_key"], index_where=text("dedupe_key IS NOT NULL")
        )
    await session.execute(statement)


async def page(
    session: AsyncSession, user_id: uuid.UUID, *, unread: bool | None, limit: int, offset: int
) -> tuple[Sequence[Notification], int]:
    where = [Notification.user_id == user_id]
    if unread is True:
        where.append(Notification.read_at.is_(None))
    elif unread is False:
        where.append(Notification.read_at.is_not(None))
    total = (await session.execute(select(func.count()).select_from(Notification).where(*where))).scalar_one()
    rows = (
        (
            await session.execute(
                select(Notification)
                .where(*where)
                .order_by(Notification.created_at.desc(), Notification.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return rows, int(total)


async def has_unread(session: AsyncSession, user_id: uuid.UUID, type_: str, href: str) -> bool:
    statement = select(
        select(Notification.id)
        .where(
            Notification.user_id == user_id,
            Notification.type == type_,
            Notification.href == href,
            Notification.read_at.is_(None),
        )
        .exists()
    )
    return bool((await session.execute(statement)).scalar_one())


async def unread_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    statement = (
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
    )
    return int((await session.execute(statement)).scalar_one())


async def mark_read(
    session: AsyncSession, user_id: uuid.UUID, ids: Sequence[uuid.UUID] | None, now: datetime
) -> int:
    statement = (
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=now)
    )
    if ids is not None:
        statement = statement.where(Notification.id.in_(ids))
    result = await session.execute(statement)
    return int(getattr(result, "rowcount", 0) or 0)
