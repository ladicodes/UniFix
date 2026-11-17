"""HTTP middleware: request IDs, request logging (no query strings) and security headers."""

from __future__ import annotations

import ipaddress
import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_context import RequestContext, reset_request_context, set_request_context

logger = logging.getLogger("unifix.request")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

_SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
)


def _client_ip(scope: Scope) -> str | None:
    """The peer address as seen by the ASGI server (configure uvicorn --proxy-headers behind a proxy)."""
    client = scope.get("client")
    if not client:
        return None
    try:
        return str(ipaddress.ip_address(client[0]))
    except ValueError:
        return None


class RequestContextMiddleware:
    """Pure ASGI middleware (works for HTTP and WebSocket scopes)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope["headers"]}
        incoming = headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID_PATTERN.match(incoming) else uuid.uuid4().hex
        token = set_request_context(
            RequestContext(
                request_id=request_id,
                client_ip=_client_ip(scope),
                user_agent=headers.get("user-agent"),
            )
        )
        started = time.perf_counter()
        status_holder: dict[str, int] = {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-request-id", request_id.encode()))
                existing = {name.lower() for name, _ in response_headers}
                response_headers.extend(item for item in _SECURITY_HEADERS if item[0] not in existing)
                if scope["path"].startswith("/api/v1/auth") and b"cache-control" not in existing:
                    response_headers.append((b"cache-control", b"no-store"))
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if scope["type"] == "http":
                logger.info(
                    "request",
                    extra={
                        "method": scope.get("method"),
                        "path": scope["path"],  # never the query string
                        "status": status_holder.get("status"),
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    },
                )
            reset_request_context(token)
