"""HTTP middleware: request IDs, request logging (no query strings), security headers, body limits."""

from __future__ import annotations

import ipaddress
import json
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
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
)
# JSON API responses never need scripts, frames or plugins. Swagger UI (docs) is exempt.
_API_CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
_HSTS = (b"strict-transport-security", b"max-age=63072000; includeSubDomains")


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

    def __init__(self, app: ASGIApp, *, hsts: bool = False, docs_prefix: str | None = None) -> None:
        self.app = app
        self.hsts = hsts
        self.docs_prefix = docs_prefix

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
                is_docs = self.docs_prefix is not None and scope["path"].startswith(self.docs_prefix)
                if not is_docs and _API_CSP[0] not in existing:
                    response_headers.append(_API_CSP)
                if self.hsts:
                    response_headers.append(_HSTS)
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


class BodySizeLimitMiddleware:
    """Reject oversized request bodies with 413 before the application reads them.

    Checks ``Content-Length`` up front and counts streamed (chunked) bytes as they arrive, so a
    missing or false header cannot bypass the limit. Upload routes get a larger allowance; the
    per-purpose limits in ``uploads.rules`` still apply after this outer bound.
    """

    def __init__(self, app: ASGIApp, *, default_limit: int, upload_limit: int, upload_path: str) -> None:
        self.app = app
        self.default_limit = default_limit
        self.upload_limit = upload_limit
        self.upload_path = upload_path

    async def _reject(self, send: Send, limit: int) -> None:
        body = json.dumps(
            {
                "detail": f"Request body must be at most {limit} bytes.",
                "code": "PAYLOAD_TOO_LARGE",
                "request_id": None,
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.upload_limit if scope["path"] == self.upload_path else self.default_limit
        for name, value in scope["headers"]:
            if name.lower() == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = -1
                if declared > limit:
                    await self._reject(send, limit)
                    return
        received = 0
        started = False
        rejected = False

        async def limited_receive() -> Message:
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # Answer 413 now and tell the app the client went away; its own reply is dropped.
                    rejected = True
                    if not started:
                        await self._reject(send, limit)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if rejected:
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        await self.app(scope, limited_receive, guarded_send)
