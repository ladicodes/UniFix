from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAt, UUIDPrimaryKey, enum_check


class RevocationReason(StrEnum):
    LOGOUT = "LOGOUT"
    LOGOUT_ALL = "LOGOUT_ALL"
    SESSION_REVOKED = "SESSION_REVOKED"
    REFRESH_REUSE = "REFRESH_REUSE"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"  # noqa: S105  (enum value)
    PASSWORD_RESET = "PASSWORD_RESET"  # noqa: S105  (enum value)
    ACCOUNT_STATUS = "ACCOUNT_STATUS"


class TokenPurpose(StrEnum):
    VERIFY_EMAIL = "VERIFY_EMAIL"
    RESET_PASSWORD = "RESET_PASSWORD"  # noqa: S105  (enum value)


class AuthSessionFamily(UUIDPrimaryKey, CreatedAt, Base):
    """One browser login. Its id is the JWT ``sid``; revoking it ends every token in the chain."""

    __tablename__ = "auth_session_families"
    __table_args__ = (
        CheckConstraint(
            f"revoked_reason IS NULL OR {enum_check('revoked_reason', RevocationReason)}",
            name="revoked_reason_valid",
        ),
        Index("ix_auth_session_families_user_active", "user_id", postgresql_where=text("revoked_at IS NULL")),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column()
    revoked_reason: Mapped[str | None] = mapped_column(String(32))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    ip: Mapped[str | None] = mapped_column(INET)

    def is_live(self, now: datetime) -> bool:
        return self.revoked_at is None and self.absolute_expires_at > now


class AuthRefreshToken(UUIDPrimaryKey, CreatedAt, Base):
    """One refresh token in a family's rotation chain. Only the SHA-256 of the token is stored."""

    __tablename__ = "auth_refresh_tokens"
    __table_args__ = (Index("ix_auth_refresh_tokens_family_id", "family_id"),)

    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("auth_session_families.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("auth_refresh_tokens.id", ondelete="SET NULL")
    )
    successor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("auth_refresh_tokens.id", ondelete="SET NULL")
    )
    idle_expires_at: Mapped[datetime] = mapped_column(nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column()


class UserToken(UUIDPrimaryKey, CreatedAt, Base):
    """Single-use, expiring token for email verification and password reset."""

    __tablename__ = "user_tokens"
    __table_args__ = (
        CheckConstraint(enum_check("purpose", TokenPurpose), name="purpose_valid"),
        Index("ix_user_tokens_user_purpose", "user_id", "purpose"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    used_at: Mapped[datetime | None] = mapped_column()
