from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import AuthRefreshToken, AuthSessionFamily, RevocationReason, UserToken
from app.modules.users.models import User


def add(session: AsyncSession, *rows: AuthSessionFamily | AuthRefreshToken | UserToken) -> None:
    session.add_all(rows)


async def get_family(
    session: AsyncSession, family_id: uuid.UUID, *, for_update: bool = False
) -> AuthSessionFamily | None:
    statement = select(AuthSessionFamily).where(AuthSessionFamily.id == family_id)
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def get_family_and_user(
    session: AsyncSession, family_id: uuid.UUID
) -> tuple[AuthSessionFamily, User] | None:
    statement = (
        select(AuthSessionFamily, User)
        .join(User, User.id == AuthSessionFamily.user_id)
        .where(AuthSessionFamily.id == family_id)
    )
    row = (await session.execute(statement)).first()
    return (row[0], row[1]) if row else None


async def list_live_families(
    session: AsyncSession, user_id: uuid.UUID, now: datetime
) -> Sequence[AuthSessionFamily]:
    statement = (
        select(AuthSessionFamily)
        .where(
            AuthSessionFamily.user_id == user_id,
            AuthSessionFamily.revoked_at.is_(None),
            AuthSessionFamily.absolute_expires_at > now,
        )
        .order_by(AuthSessionFamily.last_used_at.desc())
    )
    return (await session.execute(statement)).scalars().all()


async def get_refresh_token_by_hash(
    session: AsyncSession, token_hash: str, *, for_update: bool = False
) -> AuthRefreshToken | None:
    statement = select(AuthRefreshToken).where(AuthRefreshToken.token_hash == token_hash)
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def get_refresh_token(session: AsyncSession, token_id: uuid.UUID) -> AuthRefreshToken | None:
    return await session.get(AuthRefreshToken, token_id)


async def revoke_families(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    reason: RevocationReason,
    now: datetime,
    except_family_id: uuid.UUID | None = None,
) -> int:
    statement = (
        update(AuthSessionFamily)
        .where(AuthSessionFamily.user_id == user_id, AuthSessionFamily.revoked_at.is_(None))
        .values(revoked_at=now, revoked_reason=reason.value)
    )
    if except_family_id is not None:
        statement = statement.where(AuthSessionFamily.id != except_family_id)
    result = await session.execute(statement.execution_options(synchronize_session="fetch"))
    return int(getattr(result, "rowcount", 0) or 0)


async def get_user_token_by_hash(
    session: AsyncSession, token_hash: str, purpose: str, *, for_update: bool = False
) -> UserToken | None:
    statement = select(UserToken).where(UserToken.token_hash == token_hash, UserToken.purpose == purpose)
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def invalidate_user_tokens(
    session: AsyncSession, *, user_id: uuid.UUID, purpose: str, now: datetime
) -> None:
    await session.execute(
        update(UserToken)
        .where(UserToken.user_id == user_id, UserToken.purpose == purpose, UserToken.used_at.is_(None))
        .values(used_at=now)
    )
