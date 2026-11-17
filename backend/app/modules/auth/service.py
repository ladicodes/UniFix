"""Authentication flows: registration, login, refresh rotation, logout, email verification,
password change and reset.

Every function here is a unit of work: it validates, writes and commits. Routers only
translate HTTP to calls and results to responses (including cookies).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.container import Services
from app.core.db import violated_constraint
from app.core.email import OutgoingEmail
from app.core.errors import BadRequest, Conflict, Forbidden, NotFound, RateLimited, Unauthorized
from app.core.ratelimit import rate_limit_key
from app.core.request_context import get_request_context
from app.core.security import InvalidAccessToken, hash_token, new_opaque_token
from app.modules.audit import service as audit
from app.modules.audit.models import ActorType
from app.modules.auth import repository, sessions
from app.modules.auth.context import AuthContext
from app.modules.auth.models import AuthSessionFamily, RevocationReason, TokenPurpose, UserToken
from app.modules.auth.schemas import (
    ChangePasswordIn,
    LoginIn,
    PasswordResetConfirmIn,
    RegisterIn,
)
from app.modules.campuses import service as campuses
from app.modules.users import repository as users_repository
from app.modules.users.models import AccountStatus, Role, User

_BUCKET_AUTH_IP = "auth_ip"
_BUCKET_LOGIN_FAILURES = "login_failures_email"
_BUCKET_EMAIL_ACTION = "email_action"
_INVALID_CREDENTIALS = "Email or password is incorrect."
_LOCKED = "Too many failed sign-in attempts. Please try again later."


@dataclass(frozen=True, slots=True)
class AuthResult:
    user: User
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_at: datetime


@dataclass(frozen=True, slots=True)
class PendingEmail:
    """An email to send after the transaction commits."""

    message: OutgoingEmail


def _client_ip() -> str | None:
    context = get_request_context()
    return context.client_ip if context else None


async def _limit_ip(services: Services, now: datetime) -> None:
    await services.rate_limiter.hit(
        bucket=_BUCKET_AUTH_IP,
        key=rate_limit_key(_client_ip()),
        limit=services.settings.auth_ip_rate_limit_per_minute,
        window=timedelta(minutes=1),
        now=now,
    )


async def _limit_email_action(services: Services, subject: str, now: datetime) -> None:
    await services.rate_limiter.hit(
        bucket=_BUCKET_EMAIL_ACTION,
        key=rate_limit_key(subject),
        limit=services.settings.email_action_rate_limit_per_hour,
        window=timedelta(hours=1),
        now=now,
    )


def _issue_result(
    session: AsyncSession, services: Services, *, user: User, family: AuthSessionFamily, now: datetime
) -> tuple[sessions.IssuedRefreshToken, AuthResult]:
    issued = sessions.issue_refresh_token(session, family=family, settings=services.settings, now=now)
    access = services.access_tokens.issue(user_id=user.id, session_id=family.id, role=user.role, now=now)
    result = AuthResult(
        user=user,
        access_token=access,
        expires_in=services.access_tokens.ttl_seconds,
        refresh_token=issued.raw,
        refresh_expires_at=family.absolute_expires_at,
    )
    return issued, result


def _new_user_token(
    session: AsyncSession, *, user: User, purpose: TokenPurpose, ttl_seconds: int, now: datetime
) -> str:
    raw = new_opaque_token()
    repository.add(
        session,
        UserToken(
            user_id=user.id,
            purpose=purpose.value,
            token_hash=hash_token(raw),
            expires_at=now + timedelta(seconds=ttl_seconds),
        ),
    )
    return raw


def _verification_email(services: Services, user: User, raw_token: str) -> PendingEmail:
    link = f"{services.settings.frontend_base_url}/verify-email?token={raw_token}"
    return PendingEmail(
        OutgoingEmail(
            to=user.email,
            subject="Verify your UniFix email address",
            text_body=(
                f"Hi {user.full_name},\n\nConfirm your email address for UniFix:\n{link}\n\n"
                "If you did not create a UniFix account, you can ignore this message."
            ),
        )
    )


RegistrationStep = Callable[[AsyncSession, User], Awaitable[None]]


async def register(
    session: AsyncSession,
    services: Services,
    data: RegisterIn,
    *,
    extra_steps: Sequence[RegistrationStep] = (),
) -> tuple[AuthResult, PendingEmail]:
    """Create the account. ``extra_steps`` (e.g. professional onboarding) run in the same transaction."""
    now = services.clock.now()
    await _limit_ip(services, now)
    if await users_repository.email_exists(session, data.email):
        raise Conflict("An account with this email already exists.", code="EMAIL_TAKEN")
    if data.campus_id is not None:
        await campuses.require_active(session, data.campus_id)

    user = User(
        id=uuid.uuid4(),
        email=data.email,
        password_hash=services.passwords.hash(data.password),
        full_name=data.name,
        role=Role(data.role).value,
        status=AccountStatus.ACTIVE.value,
        city=data.city,
        country=data.country.value,
        campus_id=data.campus_id,
        last_login_at=now,
    )
    users_repository.add(session, user)
    try:
        await session.flush()  # dependent rows (session, audit, tokens) reference the user
    except IntegrityError as exc:  # concurrent registration with the same email
        await session.rollback()
        if violated_constraint(exc) == "uq_users_email":
            raise Conflict("An account with this email already exists.", code="EMAIL_TAKEN") from exc
        raise
    for step in extra_steps:
        await step(session, user)
    family = await sessions.start_family(session, user_id=user.id, settings=services.settings, now=now)
    _, result = _issue_result(session, services, user=user, family=family, now=now)
    raw_verify = _new_user_token(
        session,
        user=user,
        purpose=TokenPurpose.VERIFY_EMAIL,
        ttl_seconds=services.settings.email_verification_ttl_seconds,
        now=now,
    )
    await audit.record(
        session,
        action="auth.register",
        entity_type="user",
        entity_id=user.id,
        actor_user_id=user.id,
        data={"role": user.role},
    )
    await session.commit()
    await session.refresh(user)
    return result, _verification_email(services, user, raw_verify)


async def _record_login_failure(services: Services, email_key: str, now: datetime, user: User | None) -> None:
    await services.rate_limiter.record(bucket=_BUCKET_LOGIN_FAILURES, key=email_key, now=now)
    async with services.session_factory() as audit_session:
        await audit.record(
            audit_session,
            action="auth.login_failed",
            entity_type="user",
            entity_id=user.id if user else None,
            actor_user_id=None,
            actor_type=ActorType.SYSTEM,
            data={"email_key": email_key[:16]},
        )
        await audit_session.commit()


async def login(session: AsyncSession, services: Services, data: LoginIn) -> AuthResult:
    now = services.clock.now()
    settings = services.settings
    await _limit_ip(services, now)

    # Lockout is keyed by the (hashed) email, whether or not the account exists,
    # so it cannot be used to discover which emails are registered.
    email_key = rate_limit_key(data.email)
    locked_for = await services.rate_limiter.retry_after(
        bucket=_BUCKET_LOGIN_FAILURES,
        key=email_key,
        limit=settings.login_max_failures,
        window=timedelta(seconds=settings.login_lockout_seconds),
        now=now,
    )
    if locked_for is not None:
        raise RateLimited(locked_for, _LOCKED)

    user = await users_repository.get_by_email(session, data.email)
    if not services.passwords.verify(user.password_hash if user else None, data.password) or user is None:
        await _record_login_failure(services, email_key, now, user)
        raise Unauthorized(_INVALID_CREDENTIALS, code="INVALID_CREDENTIALS")
    if not user.is_active:
        raise Forbidden("This account is not active.", code="ACCOUNT_NOT_ACTIVE")

    await services.rate_limiter.clear(bucket=_BUCKET_LOGIN_FAILURES, key=email_key)
    if services.passwords.needs_rehash(user.password_hash):
        user.password_hash = services.passwords.hash(data.password)
    user.last_login_at = now
    family = await sessions.start_family(session, user_id=user.id, settings=settings, now=now)
    _, result = _issue_result(session, services, user=user, family=family, now=now)
    await audit.record(
        session, action="auth.login", entity_type="user", entity_id=user.id, actor_user_id=user.id
    )
    await session.commit()
    return result


async def refresh(session: AsyncSession, services: Services, raw_token: str | None) -> AuthResult:
    """Rotate a refresh token. Reuse of a rotated token revokes the whole family.

    A token rotated less than ``refresh_race_grace_seconds`` ago whose successor is still
    unused is a multi-tab race, not theft: answer 409 REFRESH_RACE and revoke nothing.
    """
    now = services.clock.now()
    settings = services.settings
    if not raw_token:
        raise Unauthorized("No active session.", code="REFRESH_MISSING")

    token = await repository.get_refresh_token_by_hash(session, hash_token(raw_token), for_update=True)
    if token is None:
        raise Unauthorized("Session is not valid.", code="REFRESH_INVALID")
    family = await repository.get_family(session, token.family_id, for_update=True)
    if family is None or not family.is_live(now):
        raise Unauthorized("Session has ended.", code="REFRESH_INVALID")

    if token.rotated_at is not None:
        successor = (
            await repository.get_refresh_token(session, token.successor_id) if token.successor_id else None
        )
        within_grace = now - token.rotated_at <= timedelta(seconds=settings.refresh_race_grace_seconds)
        if within_grace and successor is not None and successor.rotated_at is None:
            raise Conflict("Session was just refreshed by another tab; retry.", code="REFRESH_RACE")
        sessions.revoke_family(family, reason=RevocationReason.REFRESH_REUSE, now=now)
        await audit.record(
            session,
            action="auth.refresh_reuse_detected",
            entity_type="auth_session",
            entity_id=family.id,
            actor_user_id=family.user_id,
            actor_type=ActorType.SYSTEM,
        )
        await session.commit()
        raise Unauthorized("Session has ended.", code="REFRESH_REUSED")

    if token.idle_expires_at <= now:
        raise Unauthorized("Session has expired.", code="REFRESH_EXPIRED")

    user = await users_repository.get(session, family.user_id)
    if user is None or not user.is_active:
        sessions.revoke_family(family, reason=RevocationReason.ACCOUNT_STATUS, now=now)
        await session.commit()
        raise Unauthorized("Session has ended.", code="REFRESH_INVALID")

    issued = sessions.issue_refresh_token(session, family=family, settings=settings, now=now, parent=token)
    await session.flush()
    token.rotated_at = now
    token.successor_id = issued.row.id
    family.last_used_at = now
    access = services.access_tokens.issue(user_id=user.id, session_id=family.id, role=user.role, now=now)
    await session.commit()
    return AuthResult(
        user=user,
        access_token=access,
        expires_in=services.access_tokens.ttl_seconds,
        refresh_token=issued.raw,
        refresh_expires_at=family.absolute_expires_at,
    )


async def authenticate(session: AsyncSession, services: Services, bearer_token: str) -> AuthContext:
    """Resolve a Bearer access token to a live session and an active user."""
    now = services.clock.now()
    try:
        claims = services.access_tokens.decode(bearer_token, now=now)
    except InvalidAccessToken as exc:
        raise Unauthorized("Access token is invalid or expired.", code="TOKEN_INVALID") from exc
    found = await repository.get_family_and_user(session, claims.session_id)
    if found is None:
        raise Unauthorized("Session has ended.", code="SESSION_REVOKED")
    family, user = found
    if family.user_id != claims.user_id or not family.is_live(now):
        raise Unauthorized("Session has ended.", code="SESSION_REVOKED")
    if not user.is_active:
        raise Forbidden("This account is not active.", code="ACCOUNT_NOT_ACTIVE")
    return AuthContext(user=user, session_id=family.id)


async def logout(
    session: AsyncSession, services: Services, *, raw_refresh_token: str | None, bearer: AuthContext | None
) -> None:
    """Revoke the session identified by the refresh cookie and/or the access token. Idempotent."""
    now = services.clock.now()
    family_ids: set[uuid.UUID] = set()
    if raw_refresh_token:
        token = await repository.get_refresh_token_by_hash(session, hash_token(raw_refresh_token))
        if token is not None:
            family_ids.add(token.family_id)
    if bearer is not None:
        family_ids.add(bearer.session_id)
    for family_id in family_ids:
        family = await repository.get_family(session, family_id, for_update=True)
        if family is None or family.revoked_at is not None:
            continue
        sessions.revoke_family(family, reason=RevocationReason.LOGOUT, now=now)
        await audit.record(
            session,
            action="auth.logout",
            entity_type="auth_session",
            entity_id=family.id,
            actor_user_id=family.user_id,
        )
    await session.commit()


async def logout_all(session: AsyncSession, services: Services, caller: AuthContext) -> int:
    now = services.clock.now()
    count = await sessions.revoke_all(
        session, user_id=caller.user_id, reason=RevocationReason.LOGOUT_ALL, now=now
    )
    await audit.record(
        session,
        action="auth.logout_all",
        entity_type="user",
        entity_id=caller.user_id,
        actor_user_id=caller.user_id,
        data={"sessions_revoked": count},
    )
    await session.commit()
    return count


async def list_sessions(
    session: AsyncSession, services: Services, caller: AuthContext
) -> list[tuple[AuthSessionFamily, bool]]:
    families = await repository.list_live_families(session, caller.user_id, services.clock.now())
    return [(family, family.id == caller.session_id) for family in families]


async def revoke_session(
    session: AsyncSession, services: Services, caller: AuthContext, family_id: uuid.UUID
) -> None:
    family = await repository.get_family(session, family_id, for_update=True)
    if family is None or family.user_id != caller.user_id:
        raise NotFound("Session not found.")
    if family.revoked_at is None:
        sessions.revoke_family(family, reason=RevocationReason.SESSION_REVOKED, now=services.clock.now())
        await audit.record(
            session,
            action="auth.session_revoked",
            entity_type="auth_session",
            entity_id=family.id,
            actor_user_id=caller.user_id,
        )
    await session.commit()


async def change_password(
    session: AsyncSession, services: Services, caller: AuthContext, data: ChangePasswordIn
) -> None:
    now = services.clock.now()
    await _limit_ip(services, now)
    user = await users_repository.get(session, caller.user_id, for_update=True)
    assert user is not None
    if not services.passwords.verify(user.password_hash, data.current_password):
        raise BadRequest("Current password is incorrect.", code="CURRENT_PASSWORD_INCORRECT")
    if data.current_password == data.new_password:
        raise BadRequest("The new password must differ from the current one.", code="PASSWORD_UNCHANGED")
    user.password_hash = services.passwords.hash(data.new_password)
    revoked = await sessions.revoke_all(
        session,
        user_id=user.id,
        reason=RevocationReason.PASSWORD_CHANGED,
        now=now,
        except_family_id=caller.session_id,
    )
    await audit.record(
        session,
        action="auth.password_changed",
        entity_type="user",
        entity_id=user.id,
        actor_user_id=user.id,
        data={"other_sessions_revoked": revoked},
    )
    await session.commit()


async def request_email_verification(
    session: AsyncSession, services: Services, caller: AuthContext
) -> PendingEmail | None:
    now = services.clock.now()
    user = caller.user
    if user.email_verified_at is not None:
        return None
    await _limit_email_action(services, f"verify:{user.id}", now)
    await repository.invalidate_user_tokens(
        session, user_id=user.id, purpose=TokenPurpose.VERIFY_EMAIL.value, now=now
    )
    raw = _new_user_token(
        session,
        user=user,
        purpose=TokenPurpose.VERIFY_EMAIL,
        ttl_seconds=services.settings.email_verification_ttl_seconds,
        now=now,
    )
    await session.commit()
    return _verification_email(services, user, raw)


async def _consume_user_token(
    session: AsyncSession, raw: str, purpose: TokenPurpose, now: datetime
) -> UserToken:
    token = await repository.get_user_token_by_hash(session, hash_token(raw), purpose.value, for_update=True)
    if token is None or token.used_at is not None or token.expires_at <= now:
        raise BadRequest("This link is invalid or has expired.", code="TOKEN_INVALID")
    token.used_at = now
    return token


async def confirm_email_verification(session: AsyncSession, services: Services, raw_token: str) -> User:
    now = services.clock.now()
    await _limit_ip(services, now)
    token = await _consume_user_token(session, raw_token, TokenPurpose.VERIFY_EMAIL, now)
    user = await users_repository.get(session, token.user_id, for_update=True)
    assert user is not None
    if user.email_verified_at is None:
        user.email_verified_at = now
        await audit.record(
            session,
            action="auth.email_verified",
            entity_type="user",
            entity_id=user.id,
            actor_user_id=user.id,
        )
    await session.commit()
    return user


async def request_password_reset(
    session: AsyncSession, services: Services, email: str
) -> PendingEmail | None:
    """Always succeeds from the caller's point of view (no account enumeration)."""
    now = services.clock.now()
    await _limit_ip(services, now)
    await _limit_email_action(services, f"reset:{email}", now)
    user = await users_repository.get_by_email(session, email)
    if user is None or not user.is_active:
        return None
    await repository.invalidate_user_tokens(
        session, user_id=user.id, purpose=TokenPurpose.RESET_PASSWORD.value, now=now
    )
    raw = _new_user_token(
        session,
        user=user,
        purpose=TokenPurpose.RESET_PASSWORD,
        ttl_seconds=services.settings.password_reset_ttl_seconds,
        now=now,
    )
    await audit.record(
        session,
        action="auth.password_reset_requested",
        entity_type="user",
        entity_id=user.id,
        actor_user_id=None,
    )
    await session.commit()
    link = f"{services.settings.frontend_base_url}/reset-password?token={raw}"
    return PendingEmail(
        OutgoingEmail(
            to=user.email,
            subject="Reset your UniFix password",
            text_body=(
                f"Hi {user.full_name},\n\nReset your UniFix password using this link (valid for "
                f"{services.settings.password_reset_ttl_seconds // 60} minutes):\n{link}\n\n"
                "If you did not request this, you can ignore this message."
            ),
        )
    )


async def confirm_password_reset(
    session: AsyncSession, services: Services, data: PasswordResetConfirmIn
) -> None:
    now = services.clock.now()
    await _limit_ip(services, now)
    token = await _consume_user_token(session, data.token, TokenPurpose.RESET_PASSWORD, now)
    user = await users_repository.get(session, token.user_id, for_update=True)
    assert user is not None
    if not user.is_active:
        raise BadRequest("This link is invalid or has expired.", code="TOKEN_INVALID")
    user.password_hash = services.passwords.hash(data.new_password)
    await sessions.revoke_all(session, user_id=user.id, reason=RevocationReason.PASSWORD_RESET, now=now)
    await audit.record(
        session, action="auth.password_reset", entity_type="user", entity_id=user.id, actor_user_id=user.id
    )
    await session.commit()
    await services.rate_limiter.clear(bucket=_BUCKET_LOGIN_FAILURES, key=rate_limit_key(user.email))
