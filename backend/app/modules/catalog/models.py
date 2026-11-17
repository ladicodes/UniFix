from __future__ import annotations

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPrimaryKey


class ServiceCategory(UUIDPrimaryKey, Timestamps, Base):
    """A service category. Slugs are stable identifiers the frontend treats as data."""

    __tablename__ = "service_categories"
    __table_args__ = (
        CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="slug_format"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
    )

    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_categories.id", ondelete="RESTRICT")
    )
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
