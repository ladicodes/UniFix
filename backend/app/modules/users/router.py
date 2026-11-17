from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import AdminDep, CallerDep, ServicesDep, SessionDep
from app.api.presenters import user_out
from app.core.errors import error_responses
from app.modules.users import service
from app.modules.users.schemas import AdminStatusChangeIn, UpdateMeIn, UserOut

router = APIRouter(tags=["users"])


@router.get("/auth/me", responses=error_responses(401, 403), summary="The current user")
async def get_me(caller: CallerDep, session: SessionDep) -> UserOut:
    return await user_out(session, caller.user)


@router.patch(
    "/auth/me", responses=error_responses(401, 403, 409, 422), summary="Update the current user's profile"
)
async def update_me(data: UpdateMeIn, caller: CallerDep, session: SessionDep) -> UserOut:
    return await user_out(session, await service.update_me(session, caller, data))


@router.patch(
    "/admin/users/{user_id}/status",
    tags=["admin"],
    responses=error_responses(401, 403, 404, 422),
    summary="Suspend, deactivate or reactivate a user (admin); suspension revokes all sessions",
)
async def change_user_status(
    user_id: uuid.UUID, data: AdminStatusChangeIn, admin: AdminDep, session: SessionDep, services: ServicesDep
) -> UserOut:
    return await user_out(session, await service.change_status(session, services, admin, user_id, data))
