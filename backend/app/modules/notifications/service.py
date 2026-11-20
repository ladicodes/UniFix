"""In-app notifications.

``notify()`` only adds a row to the caller's session, so a notification commits (or rolls back)
together with the event it describes. Clients poll ``/notifications/unread-count``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.container import Services
from app.modules.auth.context import AuthContext
from app.modules.notifications import repository
from app.modules.notifications.models import NotificationType
from app.modules.notifications.schemas import MarkReadIn, NotificationOut
from app.modules.users.models import AccountStatus, Role, User

_SECRET_KEYS = frozenset({"password", "token", "secret", "signed_xdr", "unsigned_xdr", "ticket"})


async def notify(
    session: AsyncSession,
    user_id: uuid.UUID,
    type: NotificationType,
    *,
    title: str,
    body: str,
    href: str | None = None,
    data: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    now: datetime | None = None,
) -> None:
    payload = dict(data or {})
    leaked = _SECRET_KEYS.intersection(key.lower() for key in payload)
    if leaked:
        raise ValueError(f"Notification data must not contain secrets: {sorted(leaked)}")
    values: dict[str, Any] = {
        "user_id": user_id,
        "type": type.value,
        "title": title[:120],
        "body": body[:500],
        "href": href,
        "data": payload,
        "dedupe_key": dedupe_key,
    }
    if now is not None:
        values["created_at"] = now
    await repository.add(session, values)


async def notify_many(
    session: AsyncSession,
    user_ids: Iterable[uuid.UUID],
    type: NotificationType,
    **kwargs: Any,
) -> None:
    for user_id in dict.fromkeys(user_ids):  # de-duplicated, order kept
        await notify(session, user_id, type, **kwargs)


async def notify_message(
    session: AsyncSession,
    recipients: Iterable[uuid.UUID],
    *,
    conversation_id: uuid.UUID,
    sender_name: str,
    preview: str,
    now: datetime,
) -> None:
    """One unread notice per conversation and recipient, so a busy chat does not flood the list."""
    href = f"/messages/{conversation_id}"
    for user_id in dict.fromkeys(recipients):
        if await repository.has_unread(session, user_id, NotificationType.MESSAGE_RECEIVED.value, href):
            continue
        await notify(
            session, user_id, NotificationType.MESSAGE_RECEIVED, title=f"New message from {sender_name}",
            body=preview, href=href, data={"conversation_id": str(conversation_id)}, now=now,
        )  # fmt: skip


async def admin_ids(session: AsyncSession) -> list[uuid.UUID]:
    rows = await session.execute(
        select(User.id).where(User.role == Role.ADMIN.value, User.status == AccountStatus.ACTIVE.value)
    )
    return list(rows.scalars().all())


async def notify_admins(
    session: AsyncSession,
    type: NotificationType,
    **kwargs: Any,
) -> None:
    await notify_many(session, await admin_ids(session), type, **kwargs)


async def list_for(
    session: AsyncSession, caller: AuthContext, *, unread: bool | None, limit: int, offset: int
) -> tuple[list[NotificationOut], int]:
    rows, total = await repository.page(session, caller.user_id, unread=unread, limit=limit, offset=offset)
    return [NotificationOut.model_validate(row) for row in rows], total


async def unread_count(session: AsyncSession, caller: AuthContext) -> int:
    return await repository.unread_count(session, caller.user_id)


async def mark_read(session: AsyncSession, services: Services, caller: AuthContext, data: MarkReadIn) -> None:
    """Only the caller's own notifications change; foreign or unknown ids are ignored."""
    await repository.mark_read(session, caller.user_id, data.ids, services.clock.now())
    await session.commit()
