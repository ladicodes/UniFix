from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Index, String, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPrimaryKey, enum_check


class Role(StrEnum):
    CUSTOMER = "CUSTOMER"
    PROFESSIONAL = "PROFESSIONAL"
    ADMIN = "ADMIN"


class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class Country(StrEnum):
    NG = "NG"
    GH = "GH"


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(enum_check("role", Role), name="role_valid"),
        CheckConstraint(enum_check("status", AccountStatus), name="status_valid"),
        CheckConstraint(enum_check("country", Country), name="country_valid"),
        CheckConstraint("char_length(full_name) BETWEEN 2 AND 120", name="full_name_length"),
        Index("uq_users_phone", "phone", unique=True, postgresql_where=text("phone IS NOT NULL")),
        Index("ix_users_role_status", "role", "status"),
    )

    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column()
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(16))
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=AccountStatus.ACTIVE.value)
    city: Mapped[str | None] = mapped_column(String(80))
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column()

    @property
    def is_active(self) -> bool:
        return self.status == AccountStatus.ACTIVE.value
