from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.campuses.models import Campus


async def get(session: AsyncSession, campus_id: uuid.UUID, *, for_update: bool = False) -> Campus | None:
    statement = select(Campus).where(Campus.id == campus_id)
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def get_many(session: AsyncSession, campus_ids: Sequence[uuid.UUID]) -> Sequence[Campus]:
    if not campus_ids:
        return []
    return (await session.execute(select(Campus).where(Campus.id.in_(campus_ids)))).scalars().all()


async def get_by_slug(session: AsyncSession, slug: str) -> Campus | None:
    return (await session.execute(select(Campus).where(Campus.slug == slug))).scalar_one_or_none()


async def list_active(session: AsyncSession, *, country: str | None, q: str | None) -> Sequence[Campus]:
    statement = select(Campus).where(Campus.is_active.is_(True))
    if country:
        statement = statement.where(Campus.country == country)
    if q:
        pattern = f"%{q}%"
        statement = statement.where(or_(Campus.name.ilike(pattern), Campus.short_name.ilike(pattern)))
    return (await session.execute(statement.order_by(Campus.name))).scalars().all()


def add(session: AsyncSession, campus: Campus) -> None:
    session.add(campus)
