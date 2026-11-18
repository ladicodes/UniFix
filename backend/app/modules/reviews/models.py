from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPrimaryKey, enum_check

CATEGORIES = ("quality", "punctuality", "communication", "professionalism", "value")


class ReviewStatus(StrEnum):
    PUBLISHED = "PUBLISHED"
    HIDDEN = "HIDDEN"
    REMOVED = "REMOVED"


class Review(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint(enum_check("status", ReviewStatus), name="status_valid"),
        *(CheckConstraint(f"{c} BETWEEN 1 AND 5", name=f"{c}_range") for c in CATEGORIES),
        CheckConstraint("overall BETWEEN 1 AND 5", name="overall_range"),
        CheckConstraint("char_length(comment) <= 2000", name="comment_length"),
        Index("ix_reviews_professional_status_created", "professional_id", "status", "created_at"),
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    professional_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("professional_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    overall: Mapped[Decimal] = mapped_column(Numeric(2, 1), nullable=False)
    quality: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    punctuality: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    communication: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    professionalism: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    value: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    response_body: Mapped[str | None] = mapped_column(Text)
    response_at: Mapped[datetime | None] = mapped_column()
    moderated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    moderation_reason: Mapped[str | None] = mapped_column(String(500))
