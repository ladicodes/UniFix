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
from app.modules.catalog import repository
from app.modules.catalog.models import ServiceCategory
from app.modules.catalog.schemas import CategoryCreateIn, CategoryUpdateIn


async def list_categories(session: AsyncSession) -> Sequence[ServiceCategory]:
    return await repository.list_active(session)


async def require_active_by_slugs(session: AsyncSession, slugs: Sequence[str]) -> list[ServiceCategory]:
    """Resolve slugs in the given order; unknown or inactive slugs are a client error."""
    unique = list(dict.fromkeys(slugs))
    found = {category.slug: category for category in await repository.get_by_slugs(session, unique)}
    missing = [slug for slug in unique if slug not in found or not found[slug].is_active]
    if missing:
        raise BadRequest(f"Unknown or inactive category: {', '.join(missing)}.", code="UNKNOWN_CATEGORY")
    return [found[slug] for slug in unique]


async def require_active_ids(session: AsyncSession, ids: Sequence[uuid.UUID]) -> list[ServiceCategory]:
    unique = list(dict.fromkeys(ids))
    found = {category.id: category for category in await repository.get_many(session, unique)}
    if any(cid not in found or not found[cid].is_active for cid in unique):
        raise BadRequest("Unknown or inactive category.", code="UNKNOWN_CATEGORY")
    return [found[cid] for cid in unique]


async def slugs_by_id(session: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
    return {category.id: category.slug for category in await repository.get_many(session, list(set(ids)))}


async def ids_including_children(session: AsyncSession, slug: str) -> list[uuid.UUID] | None:
    """Category id plus direct children (so filtering by a parent finds its sub-services)."""
    categories = await repository.get_by_slugs(session, [slug])
    if not categories:
        return None
    category = categories[0]
    return [category.id, *await repository.child_ids(session, category.id)]


async def _validate_parent(
    session: AsyncSession, parent_id: uuid.UUID | None, own_id: uuid.UUID | None
) -> None:
    if parent_id is None:
        return
    if parent_id == own_id:
        raise BadRequest("A category cannot be its own parent.", code="INVALID_PARENT")
    parent = await repository.get(session, parent_id)
    if parent is None:
        raise BadRequest("Parent category not found.", code="INVALID_PARENT")
    if parent.parent_id is not None:
        raise BadRequest("Categories support one level of nesting.", code="INVALID_PARENT")


async def create(session: AsyncSession, admin: AuthContext, data: CategoryCreateIn) -> ServiceCategory:
    await _validate_parent(session, data.parent_id, None)
    category = ServiceCategory(**data.model_dump())
    repository.add(session, category)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if violated_constraint(exc) == "uq_service_categories_slug":
            raise Conflict("A category with this slug already exists.", code="SLUG_TAKEN") from exc
        raise
    await audit.record(
        session,
        action="admin.category_created",
        entity_type="service_category",
        entity_id=category.id,
        actor_user_id=admin.user_id,
        actor_type=ActorType.ADMIN,
        data={"slug": category.slug},
    )
    await session.commit()
    await session.refresh(category)
    return category


async def update(
    session: AsyncSession, admin: AuthContext, category_id: uuid.UUID, data: CategoryUpdateIn
) -> ServiceCategory:
    category = await repository.get(session, category_id, for_update=True)
    if category is None:
        raise NotFound("Category not found.")
    changes = data.model_dump(exclude_unset=True)
    if "parent_id" in changes:
        await _validate_parent(session, changes["parent_id"], category.id)
    for field, value in changes.items():
        if value is None and field in {"name", "sort_order", "is_active"}:
            continue
        setattr(category, field, value)
    await audit.record(
        session,
        action="admin.category_updated",
        entity_type="service_category",
        entity_id=category.id,
        actor_user_id=admin.user_id,
        actor_type=ActorType.ADMIN,
        data={"fields": sorted(changes)},
    )
    await session.commit()
    await session.refresh(category)
    return category
