from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.deps import CallerDep, ServicesDep, SessionDep
from app.core.errors import error_responses
from app.core.pagination import PageDep, set_page_headers
from app.modules.notifications import service
from app.modules.notifications.schemas import MarkReadIn, NotificationOut, UnreadCountOut

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", responses=error_responses(401, 403, 422), summary="The caller's notifications, newest first")
async def list_notifications(
    caller: CallerDep,
    session: SessionDep,
    response: Response,
    page: PageDep,
    unread: Annotated[bool | None, Query(description="true = unread only, false = read only")] = None,
) -> list[NotificationOut]:
    items, total = await service.list_for(
        session, caller, unread=unread, limit=page.limit, offset=page.offset
    )
    set_page_headers(response, page=page, total=total, returned=len(items))
    return items


@router.get("/unread-count", responses=error_responses(401, 403), summary="Number of unread notifications")
async def unread_count(caller: CallerDep, session: SessionDep) -> UnreadCountOut:
    return UnreadCountOut(count=await service.unread_count(session, caller))


@router.post(
    "/read",
    status_code=204,
    responses=error_responses(401, 403, 422),
    summary="Mark the given notifications (or all of them) read",
)
async def mark_read(
    data: MarkReadIn, caller: CallerDep, session: SessionDep, services: ServicesDep
) -> Response:
    await service.mark_read(session, services, caller, data)
    return Response(status_code=204)
