"""Audit logging. Callers record inside their own transaction so the entry commits atomically."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_context import get_request_context
from app.modules.audit.models import ActorType, AuditLog

_FORBIDDEN_KEYS = frozenset(
    {"password", "token", "refresh_token", "access_token", "ticket", "secret", "signed_xdr"}
)


def _assert_no_secrets(data: dict[str, Any]) -> None:
    leaked = _FORBIDDEN_KEYS.intersection(key.lower() for key in data)
    if leaked:
        raise ValueError(f"Audit data must not contain secrets: {sorted(leaked)}")


async def record(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    actor_type: ActorType = ActorType.USER,
    data: dict[str, Any] | None = None,
) -> None:
    payload = dict(data or {})
    _assert_no_secrets(payload)
    context = get_request_context()
    session.add(
        AuditLog(
            actor_type=actor_type.value,
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            request_id=context.request_id if context else None,
            ip=context.client_ip if context else None,
            data=payload,
        )
    )
