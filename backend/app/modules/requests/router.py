from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import CallerDep, HubDep, ServicesDep, SessionDep
from app.core.errors import error_responses
from app.core.pagination import PageDep, set_page_headers
from app.modules.chat import service as chat
from app.modules.chat.schemas import ConversationOut
from app.modules.requests import service
from app.modules.requests.schemas import (
    RespondIn,
    ServiceRequestIn,
    ServiceRequestOut,
    ServiceRequestOwnerOut,
)

router = APIRouter(prefix="/service-requests", tags=["service requests"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 403, 422, 429),
    summary="Post a service request (customers)",
)
async def create_request(
    data: ServiceRequestIn, caller: CallerDep, session: SessionDep, services: ServicesDep
) -> ServiceRequestOwnerOut:
    return await service.create(session, services, caller, data)


@router.get("/mine", responses=error_responses(401, 403, 422), summary="The caller's own service requests")
async def my_requests(
    response: Response, caller: CallerDep, session: SessionDep, services: ServicesDep, page: PageDep
) -> list[ServiceRequestOut]:
    items, total = await service.list_mine(session, services, caller, limit=page.limit, offset=page.offset)
    set_page_headers(response, page=page, total=total, returned=len(items))
    return items


@router.get(
    "/feed",
    responses=error_responses(401, 403, 404, 422),
    summary="Open requests matching the professional's categories and campuses (no exact locations)",
)
async def feed(
    response: Response, caller: CallerDep, session: SessionDep, services: ServicesDep, page: PageDep
) -> list[ServiceRequestOut]:
    items, total = await service.feed(session, services, caller, limit=page.limit, offset=page.offset)
    set_page_headers(response, page=page, total=total, returned=len(items))
    return items


@router.get("/{request_id}", responses=error_responses(401, 403, 404), summary="One service request")
async def get_request(
    request_id: uuid.UUID, caller: CallerDep, session: SessionDep, services: ServicesDep
) -> ServiceRequestOut | ServiceRequestOwnerOut:
    return await service.get(session, services, caller, request_id)


@router.post(
    "/{request_id}/respond",
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": ConversationOut, "description": "Already responded"},
        **error_responses(401, 403, 404, 409, 422),
    },
    summary="Respond to a request: opens a conversation with the customer",
)
async def respond(
    request_id: uuid.UUID,
    data: RespondIn,
    response: Response,
    caller: CallerDep,
    session: SessionDep,
    services: ServicesDep,
    hub: HubDep,
) -> ConversationOut:
    conversation, created = await service.respond(session, services, hub, caller, request_id, data.message)
    if not created:
        response.status_code = status.HTTP_200_OK
    return chat.conversation_out(conversation, await chat.unread_for(session, conversation.id))


@router.post(
    "/{request_id}/cancel",
    responses=error_responses(401, 403, 404, 409),
    summary="Cancel an open request (owner)",
)
async def cancel_request(
    request_id: uuid.UUID, caller: CallerDep, session: SessionDep, services: ServicesDep
) -> ServiceRequestOut | ServiceRequestOwnerOut:
    return await service.cancel(session, services, caller, request_id)
