"""Per-request context (request ID, client IP) carried through contextvars."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequestContext:
    request_id: str
    client_ip: str | None
    user_agent: str | None


_context: ContextVar[RequestContext | None] = ContextVar("unifix_request_context", default=None)


def set_request_context(context: RequestContext) -> object:
    return _context.set(context)


def reset_request_context(token: object) -> None:
    _context.reset(token)  # type: ignore[arg-type]


def get_request_context() -> RequestContext | None:
    return _context.get()


def current_request_id() -> str | None:
    context = _context.get()
    return context.request_id if context else None
