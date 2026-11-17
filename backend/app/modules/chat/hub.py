"""In-process real-time fan-out for conversation events.

Each connection gets a bounded outbound queue drained by its own writer task, so one slow
client can never block delivery to others: when its queue is full it is disconnected
(close 1013) and reconnects, catching up from the REST history (`after=` cursor).

Scope: one API process. Running several instances requires swapping this class for a
PostgreSQL LISTEN/NOTIFY-backed fan-out with the same ``publish``/``subscribe`` surface.
Messages are always persisted before they are published, so nothing is lost if a
connection or the process drops: delivery is best-effort, history is authoritative.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from starlette.websockets import WebSocket, WebSocketState

logger = logging.getLogger("unifix.chat.hub")

QUEUE_SIZE = 100
CLOSE_SLOW_CONSUMER = 1013


@dataclass(eq=False)
class Connection:
    websocket: WebSocket
    conversation_id: uuid.UUID
    user_id: uuid.UUID
    session_id: uuid.UUID
    queue: asyncio.Queue[dict[str, Any] | None] = field(default_factory=lambda: asyncio.Queue(QUEUE_SIZE))
    writer: asyncio.Task[None] | None = None

    async def _drain(self) -> None:
        while (event := await self.queue.get()) is not None:
            await self.websocket.send_json(event)

    def start(self) -> None:
        self.writer = asyncio.create_task(self._drain())

    def offer(self, event: dict[str, Any]) -> bool:
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            return False
        return True

    async def close(self, code: int, reason: str = "") -> None:
        if self.writer is not None and not self.writer.done():
            self.writer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.writer
        if self.websocket.application_state == WebSocketState.CONNECTED:
            with contextlib.suppress(RuntimeError):
                await self.websocket.close(code=code, reason=reason)


class ConversationHub:
    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, set[Connection]] = defaultdict(set)

    def subscribe(self, connection: Connection) -> None:
        self._connections[connection.conversation_id].add(connection)
        connection.start()

    def unsubscribe(self, connection: Connection) -> None:
        group = self._connections.get(connection.conversation_id)
        if group is not None:
            group.discard(connection)
            if not group:
                del self._connections[connection.conversation_id]

    def connections(self, conversation_id: uuid.UUID) -> list[Connection]:
        return list(self._connections.get(conversation_id, ()))

    async def publish(
        self,
        conversation_id: uuid.UUID,
        event: dict[str, Any],
        *,
        only_user: uuid.UUID | None = None,
        exclude_user: uuid.UUID | None = None,
    ) -> None:
        for connection in self.connections(conversation_id):
            if only_user is not None and connection.user_id != only_user:
                continue
            if exclude_user is not None and connection.user_id == exclude_user:
                continue
            if not connection.offer(event):
                logger.warning("Disconnecting slow WebSocket consumer (conversation %s)", conversation_id)
                self.unsubscribe(connection)
                await connection.close(CLOSE_SLOW_CONSUMER, "Too slow; reconnect and fetch history")

    async def disconnect_user(self, user_id: uuid.UUID, code: int, reason: str) -> None:
        for group in list(self._connections.values()):
            for connection in list(group):
                if connection.user_id == user_id:
                    self.unsubscribe(connection)
                    await connection.close(code, reason)
