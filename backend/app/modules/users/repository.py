from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User


async def get(session: AsyncSession, user_id: uuid.UUID, *, for_update: bool = False) -> User | None:
    statement = select(User).where(User.id == user_id)
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    # users.email is citext, so this comparison is case-insensitive in PostgreSQL.
    return (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()


async def email_exists(session: AsyncSession, email: str) -> bool:
    return (await session.execute(select(User.id).where(User.email == email))).first() is not None


async def phone_taken_by_other(session: AsyncSession, phone: str, user_id: uuid.UUID) -> bool:
    statement = select(User.id).where(User.phone == phone, User.id != user_id)
    return (await session.execute(statement)).first() is not None


def add(session: AsyncSession, user: User) -> None:
    session.add(user)
