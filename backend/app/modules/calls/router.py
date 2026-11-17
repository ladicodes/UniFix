from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import CallerDep, HubDep, ServicesDep, SessionDep
from app.core.errors import error_responses
from app.modules.calls import service
from app.modules.calls.schemas import CallSessionOut, EndCallIn, StartCallIn

router = APIRouter(prefix="/calls", tags=["calls"])


@router.post(
    "/sessions",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Start a call (RINGING); then send CALL_OFFER over the conversation WebSocket",
)
async def start_call(
    data: StartCallIn, caller: CallerDep, session: SessionDep, services: ServicesDep
) -> CallSessionOut:
    return service.call_out(services, await service.start(session, services, caller, data.conversation_id))


@router.post(
    "/sessions/{session_id}/end",
    responses=error_responses(401, 403, 404, 422),
    summary="End, decline or cancel a call",
)
async def end_call(
    session_id: uuid.UUID,
    data: EndCallIn,
    caller: CallerDep,
    session: SessionDep,
    services: ServicesDep,
    hub: HubDep,
) -> CallSessionOut:
    call = await service.end(session, services, hub, caller, session_id, data.reason)
    return service.call_out(services, call)
