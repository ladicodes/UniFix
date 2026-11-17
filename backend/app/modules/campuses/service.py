from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import violated_constraint
from app.core.errors import BadRequest, Conflict, NotFound
from app.modules.audit import service as audit
from app.modules.audit.models import ActorType
from app.modules.auth.context import AuthContext
from app.modules.campuses import repository
from app.modules.campuses.models import Campus
from app.modules.campuses.schemas import CampusCreateIn, CampusUpdateIn


async def list_campuses(session: AsyncSession, *, country: str | None, q: str | None) -> Sequence[Campus]:
    return await repository.list_active(session, country=country, q=q)


async def get_active(session: AsyncSession, campus_id: uuid.UUID) -> Campus | None:
    campus = await repository.get(session, campus_id)
    return campus if campus is not None and campus.is_active else None


async def get_active_by_slug(session: AsyncSession, slug: str) -> Campus | None:
    campus = await repository.get_by_slug(session, slug)
    return campus if campus is not None and campus.is_active else None


def centroid(campus: Campus) -> tuple[float, float] | None:
    if campus.latitude is None or campus.longitude is None:
        return None
    return (float(campus.latitude), float(campus.longitude))


async def require_active(session: AsyncSession, campus_id: uuid.UUID) -> Campus:
    campus = await repository.get(session, campus_id)
    if campus is None or not campus.is_active:
        raise BadRequest("Unknown or inactive campus.", code="UNKNOWN_CAMPUS")
    return campus


async def require_active_many(session: AsyncSession, campus_ids: Sequence[uuid.UUID]) -> Sequence[Campus]:
    unique_ids = list(dict.fromkeys(campus_ids))
    campuses = await repository.get_many(session, unique_ids)
    if len(campuses) != len(unique_ids) or not all(campus.is_active for campus in campuses):
        raise BadRequest("Unknown or inactive campus.", code="UNKNOWN_CAMPUS")
    return campuses


async def create(session: AsyncSession, admin: AuthContext, data: CampusCreateIn) -> Campus:
    campus = Campus(**data.model_dump())
    repository.add(session, campus)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if violated_constraint(exc) == "uq_campuses_slug":
            raise Conflict("A campus with this slug already exists.", code="SLUG_TAKEN") from exc
        raise
    await audit.record(
        session,
        action="admin.campus_created",
        entity_type="campus",
        entity_id=campus.id,
        actor_user_id=admin.user_id,
        actor_type=ActorType.ADMIN,
        data={"slug": campus.slug},
    )
    await session.commit()
    await session.refresh(campus)
    return campus


async def update(
    session: AsyncSession, admin: AuthContext, campus_id: uuid.UUID, data: CampusUpdateIn
) -> Campus:
    campus = await repository.get(session, campus_id, for_update=True)
    if campus is None:
        raise NotFound("Campus not found.")
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if value is None and field in {"name", "short_name", "city", "is_active"}:
            continue
        setattr(campus, field, value)
    await audit.record(
        session,
        action="admin.campus_updated",
        entity_type="campus",
        entity_id=campus.id,
        actor_user_id=admin.user_id,
        actor_type=ActorType.ADMIN,
        data={"fields": sorted(changes)},
    )
    await session.commit()
    await session.refresh(campus)
    return campus
