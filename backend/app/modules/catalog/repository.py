from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import ServiceCategory


async def get(
    session: AsyncSession, category_id: uuid.UUID, *, for_update: bool = False
) -> ServiceCategory | None:
    statement = select(ServiceCategory).where(ServiceCategory.id == category_id)
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def get_by_slugs(session: AsyncSession, slugs: Sequence[str]) -> Sequence[ServiceCategory]:
    if not slugs:
        return []
    return (
        (await session.execute(select(ServiceCategory).where(ServiceCategory.slug.in_(slugs))))
        .scalars()
        .all()
    )


async def get_many(session: AsyncSession, ids: Sequence[uuid.UUID]) -> Sequence[ServiceCategory]:
    if not ids:
        return []
    return (await session.execute(select(ServiceCategory).where(ServiceCategory.id.in_(ids)))).scalars().all()


async def list_active(session: AsyncSession) -> Sequence[ServiceCategory]:
    statement = (
        select(ServiceCategory)
        .where(ServiceCategory.is_active.is_(True))
        .order_by(ServiceCategory.sort_order, ServiceCategory.name)
    )
    return (await session.execute(statement)).scalars().all()


async def child_ids(session: AsyncSession, parent_id: uuid.UUID) -> Sequence[uuid.UUID]:
    statement = select(ServiceCategory.id).where(ServiceCategory.parent_id == parent_id)
    return (await session.execute(statement)).scalars().all()


def add(session: AsyncSession, category: ServiceCategory) -> None:
    session.add(category)
