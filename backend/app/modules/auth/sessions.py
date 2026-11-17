"""Session (login) lifecycle: creation, rotation and revocation.

Separate from ``auth.service`` so that ``users.service`` can revoke sessions without
importing the whole auth flow (keeps the module graph acyclic).
"""

from __future__ import annotations

import ipaddress
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.request_context import get_request_context
from app.core.security import hash_token, new_opaque_token
from app.modules.auth import repository
from app.modules.auth.models import AuthRefreshToken, AuthSessionFamily, RevocationReason

_USER_AGENT_MAX = 512


@dataclass(frozen=True, slots=True)
class IssuedRefreshToken:
    raw: str
    row: AuthRefreshToken


async def start_family(
    session: AsyncSession, *, user_id: uuid.UUID, settings: Settings, now: datetime
) -> AuthSessionFamily:
    context = get_request_context()
    user_agent = context.user_agent[:_USER_AGENT_MAX] if context and context.user_agent else None
    family = AuthSessionFamily(
        id=uuid.uuid4(),
        user_id=user_id,
        last_used_at=now,
        absolute_expires_at=now + timedelta(seconds=settings.session_absolute_ttl_seconds),
        user_agent=user_agent,
        ip=context.client_ip if context else None,
    )
    repository.add(session, family)
    await session.flush()  # refresh tokens reference the family row
    return family


def issue_refresh_token(
    session: AsyncSession,
    *,
    family: AuthSessionFamily,
    settings: Settings,
    now: datetime,
    parent: AuthRefreshToken | None = None,
) -> IssuedRefreshToken:
    raw = new_opaque_token()
    idle_expiry = min(now + timedelta(seconds=settings.refresh_idle_ttl_seconds), family.absolute_expires_at)
    row = AuthRefreshToken(
        id=uuid.uuid4(),
        family_id=family.id,
        token_hash=hash_token(raw),
        parent_id=parent.id if parent else None,
        idle_expires_at=idle_expiry,
    )
    repository.add(session, row)
    return IssuedRefreshToken(raw=raw, row=row)


def revoke_family(family: AuthSessionFamily, *, reason: RevocationReason, now: datetime) -> None:
    if family.revoked_at is None:
        family.revoked_at = now
        family.revoked_reason = reason.value


async def revoke_all(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    reason: RevocationReason,
    now: datetime,
    except_family_id: uuid.UUID | None = None,
) -> int:
    return await repository.revoke_families(
        session, user_id=user_id, reason=reason, now=now, except_family_id=except_family_id
    )


async def is_live(session: AsyncSession, family_id: uuid.UUID, user_id: uuid.UUID, now: datetime) -> bool:
    """True while the login is unrevoked, unexpired and its user is active (used by WebSockets)."""
    found = await repository.get_family_and_user(session, family_id)
    if found is None:
        return False
    family, user = found
    return family.user_id == user_id and family.is_live(now) and user.is_active


def ip_hint(ip: str | None) -> str | None:
    """Coarse client network for the session list (IPv4 /16, IPv6 /32)."""
    if not ip:
        return None
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return None
    prefix = 16 if address.version == 4 else 32
    return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False))
