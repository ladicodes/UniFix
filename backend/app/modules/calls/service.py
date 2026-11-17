"""Call sessions and WebRTC signaling relay. The backend never touches media."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.container import Services
from app.core.db import violated_constraint
from app.core.errors import BadRequest, Conflict, NotFound
from app.modules.auth.context import AuthContext
from app.modules.calls import repository
from app.modules.calls.models import LIVE_STATUSES, CallSession, CallStatus
from app.modules.calls.schemas import CallSessionOut, IceServer
from app.modules.chat import service as chat
from app.modules.chat.hub import ConversationHub

RING_TIMEOUT = timedelta(seconds=45)
MAX_SIGNAL_BYTES = 16 * 1024
SIGNAL_TYPES = frozenset({"CALL_OFFER", "CALL_ANSWER", "CALL_ICE", "CALL_END"})


def call_out(services: Services, call: CallSession) -> CallSessionOut:
    return CallSessionOut(
        session_id=call.id,
        conversation_id=call.conversation_id,
        initiator_id=call.initiator_id,
        status=CallStatus(call.status),
        created_at=call.created_at,
        answered_at=call.answered_at,
        ended_at=call.ended_at,
        ice_servers=[IceServer(urls=services.settings.webrtc_stun_urls)],
    )


async def start(
    session: AsyncSession, services: Services, caller: AuthContext, conversation_id: uuid.UUID
) -> CallSession:
    await chat.require_member(session, caller, conversation_id, for_update=True)
    now = services.clock.now()
    await repository.expire_unanswered(session, conversation_id, now - RING_TIMEOUT)
    if await repository.live_for(session, conversation_id) is not None:
        raise Conflict("A call is already in progress in this conversation.", code="CALL_IN_PROGRESS")
    call = CallSession(
        id=uuid.uuid4(), conversation_id=conversation_id, initiator_id=caller.user_id,
        status=CallStatus.RINGING.value, created_at=now,
    )  # fmt: skip
    repository.add(session, call)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if violated_constraint(exc) == "uq_call_sessions_live_per_conversation":
            raise Conflict(
                "A call is already in progress in this conversation.", code="CALL_IN_PROGRESS"
            ) from exc
        raise
    return call


def _finish(call: CallSession, *, by: uuid.UUID, now: Any, reason: str | None) -> None:
    if call.status == CallStatus.RINGING.value and by != call.initiator_id:
        call.status = CallStatus.DECLINED.value
    elif call.status == CallStatus.RINGING.value:
        call.status = CallStatus.MISSED.value
    else:
        call.status = CallStatus.ENDED.value
    call.ended_at = now
    call.end_reason = reason


async def end(
    session: AsyncSession,
    services: Services,
    hub: ConversationHub,
    caller: AuthContext,
    call_id: uuid.UUID,
    reason: str | None,
) -> CallSession:
    call = await repository.get(session, call_id, for_update=True)
    if call is None or not await chat.is_member(session, call.conversation_id, caller.user_id):
        raise NotFound("Call not found.")
    if call.status in LIVE_STATUSES:
        _finish(call, by=caller.user_id, now=services.clock.now(), reason=reason)
        await session.commit()
        await hub.publish(
            call.conversation_id,
            {
                "type": "CALL_END",
                "data": {"session_id": str(call.id), "from": str(caller.user_id), "payload": {}},
            },
            exclude_user=caller.user_id,
        )
    return call


async def relay(
    session: AsyncSession,
    services: Services,
    hub: ConversationHub,
    *,
    sender_id: uuid.UUID,
    conversation_id: uuid.UUID,
    frame: dict[str, Any],
) -> None:
    """Relay one signaling frame to the other participant, enforcing session membership and state."""
    frame_type = frame.get("type")
    try:
        call_id = uuid.UUID(str(frame.get("session_id")))
    except ValueError as exc:
        raise BadRequest("session_id is required.", code="INVALID_SIGNAL") from exc
    payload = frame.get("payload") or {}
    if not isinstance(payload, dict) or len(json.dumps(payload)) > MAX_SIGNAL_BYTES:
        raise BadRequest("Signal payload is invalid or too large.", code="INVALID_SIGNAL")
    call = await repository.get(session, call_id, for_update=True)
    if call is None or call.conversation_id != conversation_id or call.status not in LIVE_STATUSES:
        raise NotFound("Call not found or not active.", code="CALL_NOT_ACTIVE")
    now = services.clock.now()
    if frame_type == "CALL_OFFER" and sender_id != call.initiator_id:
        raise BadRequest("Only the caller sends the offer.", code="INVALID_SIGNAL")
    if frame_type == "CALL_ANSWER":
        if sender_id == call.initiator_id or call.status != CallStatus.RINGING.value:
            raise BadRequest("Only the callee can answer a ringing call.", code="INVALID_SIGNAL")
        call.status = CallStatus.ACTIVE.value
        call.answered_at = now
    if frame_type == "CALL_END":
        _finish(call, by=sender_id, now=now, reason=str(payload.get("reason", ""))[:64] or None)
    await session.commit()
    await hub.publish(
        conversation_id,
        {
            "type": frame_type,
            "data": {"session_id": str(call.id), "from": str(sender_id), "payload": payload},
        },
        exclude_user=sender_id,
    )
