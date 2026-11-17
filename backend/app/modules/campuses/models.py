from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Numeric, String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPrimaryKey


class Campus(UUIDPrimaryKey, Timestamps, Base):
    """A university campus or campus community. Membership is self-declared, never email-based."""

    __tablename__ = "campuses"
    __table_args__ = (
        CheckConstraint("country IN ('NG', 'GH')", name="country_valid"),
        CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="slug_format"),
        CheckConstraint("latitude IS NULL OR latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude IS NULL OR longitude BETWEEN -180 AND 180", name="longitude_range"),
    )

    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    short_name: Mapped[str] = mapped_column(String(32), nullable=False)
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str | None] = mapped_column(String(80))
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
