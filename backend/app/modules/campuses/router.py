from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminDep, SessionDep
from app.core.errors import error_responses
from app.modules.campuses import service
from app.modules.campuses.schemas import AdminCampusOut, CampusCreateIn, CampusOut, CampusUpdateIn
from app.modules.users.models import Country

router = APIRouter(tags=["campuses"])


@router.get("/campuses", responses=error_responses(422), summary="Active campuses")
async def list_campuses(
    session: SessionDep,
    country: Country | None = None,
    q: Annotated[str | None, Query(max_length=80, description="Search name or short name")] = None,
) -> list[CampusOut]:
    campuses = await service.list_campuses(session, country=country.value if country else None, q=q)
    return [CampusOut.model_validate(campus) for campus in campuses]


@router.post(
    "/admin/campuses",
    status_code=status.HTTP_201_CREATED,
    tags=["admin"],
    responses=error_responses(401, 403, 409, 422),
    summary="Create a campus (admin)",
)
async def create_campus(data: CampusCreateIn, admin: AdminDep, session: SessionDep) -> AdminCampusOut:
    return AdminCampusOut.model_validate(await service.create(session, admin, data))


@router.patch(
    "/admin/campuses/{campus_id}",
    tags=["admin"],
    responses=error_responses(401, 403, 404, 422),
    summary="Update or deactivate a campus (admin)",
)
async def update_campus(
    campus_id: uuid.UUID, data: CampusUpdateIn, admin: AdminDep, session: SessionDep
) -> AdminCampusOut:
    return AdminCampusOut.model_validate(await service.update(session, admin, campus_id, data))
