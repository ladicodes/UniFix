from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, Numeric, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPrimaryKey, enum_check


class RequestStatus(StrEnum):
    OPEN = "OPEN"
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ServiceRequest(UUIDPrimaryKey, Timestamps, Base):
    """A customer's description of a job. Exact location stays private to the customer."""

    __tablename__ = "service_requests"
    __table_args__ = (
        CheckConstraint(enum_check("status", RequestStatus), name="status_valid"),
        CheckConstraint(
            "preferred_end IS NULL OR preferred_start IS NULL OR preferred_end >= preferred_start",
            name="window_order",
        ),
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name="coordinates_paired"),
        Index("ix_service_requests_feed", "status", "category_id", "campus_id", "created_at"),
        Index("ix_service_requests_customer", "customer_id", "created_at"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("service_categories.id", ondelete="RESTRICT"), nullable=False
    )
    campus_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campuses.id", ondelete="SET NULL"))
    target_professional_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("professional_profiles.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    item: Mapped[str | None] = mapped_column(String(120))
    location_text: Mapped[str | None] = mapped_column(String(300))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    preferred_start: Mapped[datetime | None] = mapped_column()
    preferred_end: Mapped[datetime | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=RequestStatus.OPEN.value)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)


service_request_media = Table(
    "service_request_media",
    Base.metadata,
    Column("request_id", ForeignKey("service_requests.id", ondelete="CASCADE"), primary_key=True),
    Column("file_id", ForeignKey("files.id", ondelete="RESTRICT"), primary_key=True),
    Column("sort_order", Integer, nullable=False, server_default="0"),
    Index("ix_service_request_media_file_id", "file_id"),
)
