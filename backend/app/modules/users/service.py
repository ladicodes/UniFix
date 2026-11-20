from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.container import Services
from app.core.db import violated_constraint
from app.core.errors import BadRequest, Conflict, Forbidden, NotFound
from app.modules.audit import service as audit
from app.modules.audit.models import ActorType
from app.modules.auth import sessions
from app.modules.auth.context import AuthContext
from app.modules.auth.models import RevocationReason
from app.modules.campuses import service as campuses
from app.modules.notifications import service as notifications
from app.modules.notifications.models import NotificationType
from app.modules.uploads import service as uploads
from app.modules.uploads.models import FilePurpose
from app.modules.users import repository
from app.modules.users.models import AccountStatus, Role, User
from app.modules.users.schemas import AdminStatusChangeIn, UpdateMeIn


async def update_me(session: AsyncSession, caller: AuthContext, data: UpdateMeIn) -> User:
    user = await repository.get(session, caller.user_id, for_update=True)
    assert user is not None
    changes = data.model_dump(exclude_unset=True)
    new_phone = changes.get("phone")
    if new_phone is not None and await repository.phone_taken_by_other(session, new_phone, user.id):
        raise Conflict("This phone number is already in use.", code="PHONE_TAKEN")
    if "name" in changes and changes["name"] is not None:
        user.full_name = changes["name"]
    if "city" in changes:
        user.city = changes["city"]
    if "phone" in changes:
        user.phone = changes["phone"]
    if "campus_id" in changes:
        if changes["campus_id"] is not None:
            await campuses.require_active(session, changes["campus_id"])
        user.campus_id = changes["campus_id"]
    if "avatar_file_id" in changes:
        if changes["avatar_file_id"] is not None:
            await uploads.require_owned(session, caller, [changes["avatar_file_id"]], FilePurpose.AVATAR)
        user.avatar_file_id = changes["avatar_file_id"]
    try:
        await session.commit()
    except IntegrityError as exc:  # concurrent update claimed the same phone
        await session.rollback()
        if violated_constraint(exc) == "uq_users_phone":
            raise Conflict("This phone number is already in use.", code="PHONE_TAKEN") from exc
        raise
    await session.refresh(user)
    return user


async def change_status(
    session: AsyncSession,
    services: Services,
    admin: AuthContext,
    user_id: uuid.UUID,
    data: AdminStatusChangeIn,
) -> User:
    if user_id == admin.user_id:
        raise Forbidden("You cannot change the status of your own account.", code="SELF_STATUS_CHANGE")
    user = await repository.get(session, user_id, for_update=True)
    if user is None:
        raise NotFound("User not found.")
    previous = user.status
    if previous == data.status.value:
        return user
    now = services.clock.now()
    user.status = data.status.value
    revoked = 0
    if data.status is not AccountStatus.ACTIVE:
        revoked = await sessions.revoke_all(
            session, user_id=user.id, reason=RevocationReason.ACCOUNT_STATUS, now=now
        )
    if data.status is AccountStatus.SUSPENDED:
        await notifications.notify(
            session,
            user.id,
            NotificationType.ACCOUNT_SUSPENDED,
            title="Account suspended",
            body="An administrator suspended your account. Contact support if you think this is a mistake.",
            href=None,
            data={"reason": data.reason} if data.reason else {},
            now=now,
        )
    await audit.record(
        session,
        action="admin.user_status_changed",
        entity_type="user",
        entity_id=user.id,
        actor_user_id=admin.user_id,
        actor_type=ActorType.ADMIN,
        data={"from": previous, "to": user.status, "reason": data.reason, "sessions_revoked": revoked},
    )
    await session.commit()
    await session.refresh(user)
    return user


async def create_admin(
    session: AsyncSession, services: Services, *, email: str, name: str, password: str
) -> User:
    """Create an administrator. Only reachable from the CLI; admins cannot self-register."""
    email = email.strip().lower()
    if await repository.email_exists(session, email):
        raise Conflict("An account with this email already exists.", code="EMAIL_TAKEN")
    if not 10 <= len(password) <= 128:
        raise BadRequest("Password must be 10-128 characters.", code="PASSWORD_INVALID")
    now = services.clock.now()
    user = User(
        email=email,
        password_hash=services.passwords.hash(password),
        full_name=name.strip(),
        role=Role.ADMIN.value,
        status=AccountStatus.ACTIVE.value,
        country="NG",
        email_verified_at=now,
    )
    repository.add(session, user)
    await session.flush()
    await audit.record(
        session,
        action="admin.created",
        entity_type="user",
        entity_id=user.id,
        actor_user_id=None,
        actor_type=ActorType.SYSTEM,
    )
    await session.commit()
    return user
