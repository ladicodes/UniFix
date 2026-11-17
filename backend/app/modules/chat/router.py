from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, WebSocket, status

from app.api.deps import CallerDep, HubDep, ServicesDep, SessionDep
from app.core.config import API_PREFIX
from app.core.errors import error_responses
from app.core.pagination import PageDep, set_page_headers
from app.modules.chat import service, ws
from app.modules.chat.schemas import (
    ConversationDetail,
    ConversationOut,
    ConversationSummary,
    MarkReadIn,
    MessageOut,
    OpenConversationIn,
    ReportIn,
    ReportOut,
    SendMessageIn,
    TicketIn,
    TicketOut,
)

router = APIRouter(tags=["conversations"])


@router.get("/conversations", responses=error_responses(401, 403, 422), summary="The caller's conversations")
async def list_conversations(
    response: Response, caller: CallerDep, session: SessionDep, page: PageDep
) -> list[ConversationSummary]:
    items, total = await service.list_conversations(session, caller, limit=page.limit, offset=page.offset)
    set_page_headers(response, page=page, total=total, returned=len(items))
    return items


@router.post(
    "/conversations",
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": ConversationOut, "description": "Existing thread"},
        **error_responses(400, 401, 403, 404, 422),
    },
    summary="Open (or return the existing) direct conversation with a professional (customers)",
)
async def open_conversation(
    data: OpenConversationIn, response: Response, caller: CallerDep, session: SessionDep
) -> ConversationOut:
    conversation, created = await service.open_conversation(session, caller, data.professional_id)
    if not created:
        response.status_code = status.HTTP_200_OK
    unread = await service.unread_for(session, conversation.id)
    return service.conversation_out(conversation, unread)


@router.get(
    "/conversations/{conversation_id}",
    responses=error_responses(401, 403, 404, 422),
    summary="Conversation with recent messages (oldest first)",
)
async def get_conversation(
    conversation_id: uuid.UUID,
    caller: CallerDep,
    session: SessionDep,
    services: ServicesDep,
    messages_limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ConversationDetail:
    return await service.detail(session, services, caller, conversation_id, messages_limit=messages_limit)


@router.get(
    "/conversations/{conversation_id}/messages",
    responses=error_responses(400, 401, 403, 404, 422),
    summary="Message history: `before` pages back, `after` catches up after a reconnect",
)
async def list_messages(
    conversation_id: uuid.UUID,
    caller: CallerDep,
    session: SessionDep,
    services: ServicesDep,
    before: uuid.UUID | None = None,
    after: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[MessageOut]:
    return await service.history(
        session, services, caller, conversation_id, before=before, after=after, limit=limit
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": MessageOut, "description": "Duplicate client_message_id"},
        **error_responses(400, 401, 403, 404, 409, 422, 429),
    },
    summary="Send a message (persisted, then delivered over the WebSocket)",
)
async def send_message(
    conversation_id: uuid.UUID,
    data: SendMessageIn,
    response: Response,
    caller: CallerDep,
    session: SessionDep,
    services: ServicesDep,
    hub: HubDep,
) -> MessageOut:
    message, created = await service.send_message(session, services, hub, caller, conversation_id, data)
    if not created:
        response.status_code = status.HTTP_200_OK
    return message


@router.post(
    "/conversations/{conversation_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(400, 401, 403, 404, 422),
    summary="Advance the caller's read pointer",
)
async def mark_read(
    conversation_id: uuid.UUID,
    data: MarkReadIn,
    caller: CallerDep,
    session: SessionDep,
    services: ServicesDep,
    hub: HubDep,
) -> Response:
    await service.mark_read(session, services, hub, caller, conversation_id, data.last_read_message_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/conversations/{conversation_id}/report",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 403, 404, 409, 422),
    summary="Report a conversation or one of its messages",
)
async def report(
    conversation_id: uuid.UUID, data: ReportIn, caller: CallerDep, session: SessionDep
) -> ReportOut:
    return ReportOut.model_validate(await service.report(session, caller, conversation_id, data))


@router.post(
    "/ws/tickets",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 404, 422, 429),
    summary="Issue a single-use, 30-second WebSocket ticket for a conversation",
)
async def issue_ticket(
    data: TicketIn, caller: CallerDep, session: SessionDep, services: ServicesDep
) -> TicketOut:
    raw, expires_at = await service.issue_ticket(session, services, caller, data.conversation_id)
    return TicketOut(
        ticket=raw, expires_at=expires_at, ws_path=f"{API_PREFIX}/ws/conversations/{data.conversation_id}"
    )


@router.websocket("/ws/conversations/{conversation_id}")
async def conversation_socket(websocket: WebSocket, conversation_id: uuid.UUID) -> None:
    await ws.serve(websocket, conversation_id)
