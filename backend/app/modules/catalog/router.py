from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import AdminDep, SessionDep
from app.core.errors import error_responses
from app.modules.catalog import service
from app.modules.catalog.schemas import AdminCategoryOut, CategoryCreateIn, CategoryOut, CategoryUpdateIn

router = APIRouter(tags=["categories"])


@router.get("/categories", responses=error_responses(422), summary="Active service categories")
async def list_categories(session: SessionDep) -> list[CategoryOut]:
    return [CategoryOut.model_validate(category) for category in await service.list_categories(session)]


@router.post(
    "/admin/categories",
    status_code=status.HTTP_201_CREATED,
    tags=["admin"],
    responses=error_responses(400, 401, 403, 409, 422),
    summary="Create a service category (admin)",
)
async def create_category(data: CategoryCreateIn, admin: AdminDep, session: SessionDep) -> AdminCategoryOut:
    return AdminCategoryOut.model_validate(await service.create(session, admin, data))


@router.patch(
    "/admin/categories/{category_id}",
    tags=["admin"],
    responses=error_responses(400, 401, 403, 404, 422),
    summary="Update or disable a service category (admin)",
)
async def update_category(
    category_id: uuid.UUID, data: CategoryUpdateIn, admin: AdminDep, session: SessionDep
) -> AdminCategoryOut:
    return AdminCategoryOut.model_validate(await service.update(session, admin, category_id, data))
