"""Conversation WebSocket: ticket authentication, event delivery and signaling relay.

Authentication completes *before* the connection is considered established:

1. the ``Origin`` header is checked against the allowlist (cross-site WebSocket hijacking);
2. the single-use ticket is consumed atomically;
3. its scope is checked against the path;
4. the session (login) and the user's status are re-checked;
5. conversation membership is re-checked.

On any failure the handshake is accepted only so that a specific close code can be sent,
then the socket is closed immediately. No data is exchanged first.

Close codes: 4000 re-authenticate (max lifetime), 4401 bad ticket or revoked session,
4403 origin or scope rejected, 4404 not a member, 4429 too many frames, 1013 slow consumer.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections import deque
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from app.core.container import Services
from app.core.errors import AppError
from app.modules.auth import sessions
from app.modules.auth.context import AuthContext
from app.modules.calls import service as calls
from app.modules.chat import service as chat
from app.modules.chat.hub import Connection, ConversationHub
from app.modules.users import repository as users_repository

logger = logging.getLogger("unifix.chat.ws")

REVALIDATE_SECONDS = 60.0
MAX_LIFETIME_SECONDS = 3600.0
INBOUND_LIMIT = 30
INBOUND_WINDOW_SECONDS = 10.0
MAX_FRAME_BYTES = 32 * 1024


async def _reject(websocket: WebSocket, code: int, reason: str) -> None:
    await websocket.accept()
    await websocket.close(code=code, reason=reason)


async def _authorise(
    websocket: WebSocket, services: Services, conversation_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID] | None:
    origin = (websocket.headers.get("origin") or "").lower().rstrip("/")
    if origin not in services.settings.cors_origins:
        await _reject(websocket, 4403, "Origin not allowed")
        return None
    if "token" in websocket.query_params or "access_token" in websocket.query_params:
        await _reject(websocket, 4401, "Use a WebSocket ticket, not an access token")
        return None
    raw = websocket.query_params.get("ticket")
    if not raw or len(raw) > 128:
        await _reject(websocket, 4401, "Ticket required")
        return None
    now = services.clock.now()
    async with services.session_factory() as session:
        ticket = await chat.consume_ticket(session, raw, now)
        if ticket is None:
            await _reject(websocket, 4401, "Ticket invalid, expired or already used")
            return None
        if ticket.conversation_id != conversation_id:
            await _reject(websocket, 4403, "Ticket is for another conversation")
            return None
        if not await sessions.is_live(session, ticket.family_id, ticket.user_id, now):
            await _reject(websocket, 4401, "Session has ended")
            return None
        if not await chat.is_member(session, conversation_id, ticket.user_id):
            await _reject(websocket, 4404, "Not a member of this conversation")
            return None
    return ticket.user_id, ticket.family_id


async def _watchdog(services: Services, hub: ConversationHub, connection: Connection, started: float) -> None:
    """Close the socket when the session is revoked, membership ends or the max lifetime passes."""
    while True:
        await asyncio.sleep(REVALIDATE_SECONDS)
        if time.monotonic() - started >= MAX_LIFETIME_SECONDS:
            hub.unsubscribe(connection)
            await connection.close(4000, "Re-authenticate with a new ticket")
            return
        async with services.session_factory() as session:
            live = await sessions.is_live(
                session, connection.session_id, connection.user_id, services.clock.now()
            )
            member = live and await chat.is_member(session, connection.conversation_id, connection.user_id)
        if not member:
            hub.unsubscribe(connection)
            await connection.close(4401, "Session has ended")
            return


async def _caller(services: Services, connection: Connection) -> AuthContext:
    async with services.session_factory() as session:
        user = await users_repository.get(session, connection.user_id)
    if user is None or not user.is_active:
        raise AppError("Account is not active.", code="ACCOUNT_NOT_ACTIVE")
    return AuthContext(user=user, session_id=connection.session_id)


async def _dispatch(
    services: Services, hub: ConversationHub, connection: Connection, frame: dict[str, Any]
) -> None:
    frame_type = frame.get("type")
    if frame_type == "PING":
        connection.offer({"type": "PONG"})
    elif frame_type == "TYPING":
        await hub.publish(
            connection.conversation_id,
            {"type": "TYPING", "data": {"user_id": str(connection.user_id)}},
            exclude_user=connection.user_id,
        )
    elif frame_type == "READ":
        message_id = uuid.UUID(str(frame.get("last_read_message_id")))
        caller = await _caller(services, connection)
        async with services.session_factory() as session:
            await chat.mark_read(session, services, hub, caller, connection.conversation_id, message_id)
    elif frame_type in calls.SIGNAL_TYPES:
        async with services.session_factory() as session:
            await calls.relay(
                session,
                services,
                hub,
                sender_id=connection.user_id,
                conversation_id=connection.conversation_id,
                frame=frame,
            )
    else:
        connection.offer({"type": "ERROR", "data": {"code": "UNKNOWN_TYPE", "detail": "Unknown frame type."}})


async def serve(websocket: WebSocket, conversation_id: uuid.UUID) -> None:
    services: Services = websocket.app.state.services
    hub: ConversationHub = websocket.app.state.chat_hub
    identity = await _authorise(websocket, services, conversation_id)
    if identity is None:
        return
    user_id, session_id = identity
    await websocket.accept()
    connection = Connection(websocket, conversation_id, user_id, session_id)
    hub.subscribe(connection)
    watchdog = asyncio.create_task(_watchdog(services, hub, connection, time.monotonic()))
    recent: deque[float] = deque()
    try:
        while True:
            text = await websocket.receive_text()
            now = time.monotonic()
            recent.append(now)
            while recent and now - recent[0] > INBOUND_WINDOW_SECONDS:
                recent.popleft()
            if len(recent) > INBOUND_LIMIT:
                await connection.close(4429, "Too many frames")
                break
            try:
                if len(text) > MAX_FRAME_BYTES:
                    raise ValueError("frame too large")
                frame = json.loads(text)
                if not isinstance(frame, dict):
                    raise ValueError("frame must be an object")
                await _dispatch(services, hub, connection, frame)
            except AppError as exc:
                connection.offer({"type": "ERROR", "data": {"code": exc.code, "detail": exc.detail}})
            except (ValueError, TypeError):
                connection.offer(
                    {"type": "ERROR", "data": {"code": "INVALID_FRAME", "detail": "Malformed frame."}}
                )
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(connection)
        watchdog.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watchdog
        await connection.close(1000)
