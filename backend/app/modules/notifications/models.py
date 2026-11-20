from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAt, UUIDPrimaryKey, enum_check


class NotificationType(StrEnum):
    MESSAGE_RECEIVED = "MESSAGE_RECEIVED"
    QUOTE_RECEIVED = "QUOTE_RECEIVED"
    QUOTE_ACCEPTED = "QUOTE_ACCEPTED"
    QUOTE_REJECTED = "QUOTE_REJECTED"
    BOOKING_FUNDED = "BOOKING_FUNDED"
    BOOKING_CANCELLED = "BOOKING_CANCELLED"
    JOB_STARTED = "JOB_STARTED"
    COMPLETION_SUBMITTED = "COMPLETION_SUBMITTED"
    PAYMENT_RELEASED = "PAYMENT_RELEASED"
    PAYMENT_REFUNDED = "PAYMENT_REFUNDED"
    DISPUTE_OPENED = "DISPUTE_OPENED"
    DISPUTE_LOCKED = "DISPUTE_LOCKED"
    DISPUTE_RESOLVED = "DISPUTE_RESOLVED"
    DISPUTE_SLA_REMINDER = "DISPUTE_SLA_REMINDER"
    DISPUTE_ESCALATED = "DISPUTE_ESCALATED"
    REVIEW_RECEIVED = "REVIEW_RECEIVED"
    VERIFICATION_APPROVED = "VERIFICATION_APPROVED"
    VERIFICATION_REJECTED = "VERIFICATION_REJECTED"
    ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED"
    DEADLINE_APPROACHING = "DEADLINE_APPROACHING"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    CANCELLATION_DECLINED = "CANCELLATION_DECLINED"
    CHAIN_VERIFICATION_FAILED = "CHAIN_VERIFICATION_FAILED"


class Notification(UUIDPrimaryKey, CreatedAt, Base):
    """In-app notification. Written in the same transaction as the event it describes."""

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(enum_check("type", NotificationType), name="type_valid"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
        Index("ix_notifications_user_unread", "user_id", postgresql_where=text("read_at IS NULL")),
        # Scheduled notifications (deadline warnings, SLA reminders) are sent at most once each.
        Index(
            "uq_notifications_user_dedupe",
            "user_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("dedupe_key IS NOT NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(String(500), nullable=False)
    href: Mapped[str | None] = mapped_column(String(300))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    dedupe_key: Mapped[str | None] = mapped_column(String(160))
    read_at: Mapped[datetime | None] = mapped_column()
