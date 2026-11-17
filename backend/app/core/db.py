"""Database engine, session factory and declarative base."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import Settings

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {datetime: DateTime(timezone=True)}


class UUIDPrimaryKey:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class Timestamps(CreatedAt):
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


def enum_check(column: str, enum: type[StrEnum]) -> str:
    """SQL CHECK expression restricting ``column`` to the values of ``enum``."""
    values = ", ".join(f"'{member.value}'" for member in enum)
    return f"{column} IN ({values})"


def violated_constraint(exc: IntegrityError) -> str | None:
    """Name of the constraint behind an IntegrityError (psycopg diagnostics), if known."""
    diag = getattr(exc.orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return str(name) if name else None


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        pool_pre_ping=True,
        # All timestamps are produced and returned in UTC regardless of the server's local zone.
        connect_args={"options": "-c timezone=UTC"},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
