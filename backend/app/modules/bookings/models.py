from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Identity, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAt, Timestamps, UUIDPrimaryKey, enum_check


class BookingStatus(StrEnum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    FUNDED = "FUNDED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETION_SUBMITTED = "COMPLETION_SUBMITTED"
    COMPLETED = "COMPLETED"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"
    RESOLVED = "RESOLVED"


ACTIVE_STATUSES = (
    BookingStatus.PENDING_PAYMENT,
    BookingStatus.FUNDED,
    BookingStatus.IN_PROGRESS,
    BookingStatus.COMPLETION_SUBMITTED,
    BookingStatus.DISPUTED,
)
_ACTIVE_SQL = ", ".join(f"'{status.value}'" for status in ACTIVE_STATUSES)


class TimelineActor(StrEnum):
    CUSTOMER = "CUSTOMER"
    PROFESSIONAL = "PROFESSIONAL"
    SYSTEM = "SYSTEM"
    CHAIN = "CHAIN"
    ADMIN = "ADMIN"


class Booking(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint(enum_check("status", BookingStatus), name="status_valid"),
        CheckConstraint("currency IN ('NGN', 'GHS')", name="currency_valid"),
        CheckConstraint("amount_minor > 0", name="amount_positive"),
        Index(
            "uq_bookings_active_per_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text(f"status IN ({_ACTIVE_SQL})"),
        ),
        Index(
            "uq_bookings_per_service_request",
            "service_request_id",
            unique=True,
            postgresql_where=text("service_request_id IS NOT NULL AND status <> 'CANCELLED'"),
        ),
        Index("ix_bookings_customer_status", "customer_id", "status"),
        Index("ix_bookings_professional_status", "professional_id", "status"),
        Index("ix_bookings_created_at", "created_at"),
    )

    agreement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agreements.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    quote_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quotes.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False
    )
    service_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_requests.id", ondelete="RESTRICT")
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    professional_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("professional_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    service_address: Mapped[str | None] = mapped_column(String(300))
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    payment_due_by: Mapped[datetime] = mapped_column(nullable=False)
    funded_at: Mapped[datetime | None] = mapped_column()
    started_at: Mapped[datetime | None] = mapped_column()
    completion_submitted_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()
    cancelled_at: Mapped[datetime | None] = mapped_column()
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012  (optimistic locking)


class BookingEvent(UUIDPrimaryKey, CreatedAt, Base):
    """Append-only timeline (UPDATE/DELETE blocked by trigger)."""

    __tablename__ = "booking_events"
    __table_args__ = (
        CheckConstraint(enum_check("actor_type", TimelineActor), name="actor_type_valid"),
        Index("ix_booking_events_booking_seq", "booking_id", "seq"),
    )

    # Monotonic insertion order: events written in the same instant still sort deterministically.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True, nullable=False)
    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str | None] = mapped_column(String(24))
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class IdempotencyKey(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        CheckConstraint("status IN ('IN_PROGRESS', 'COMPLETED')", name="status_valid"),
        Index("uq_idempotency_keys_user_key", "user_id", "key", unique=True),
        Index("ix_idempotency_keys_expires_at", "expires_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    path: Mapped[str] = mapped_column(String(300), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[Any | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
