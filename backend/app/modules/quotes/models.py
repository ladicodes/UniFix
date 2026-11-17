from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAt, Timestamps, UUIDPrimaryKey, enum_check


class QuoteStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class ServiceMethod(StrEnum):
    CUSTOMER_TO_PRO = "CUSTOMER_TO_PRO"
    PRO_TO_CUSTOMER = "PRO_TO_CUSTOMER"
    EITHER = "EITHER"
    REMOTE = "REMOTE"


QUOTE_TERM_COLUMNS = (
    "conversation_id", "service_request_id", "professional_id", "customer_id", "version", "title",
    "description", "labour_minor", "materials_minor", "total_minor", "currency", "completion_date",
    "payment_terms", "service_method", "milestones", "valid_until", "created_at",
)  # fmt: skip


class Quote(UUIDPrimaryKey, Timestamps, Base):
    """A versioned offer. Terms never change (DB trigger); a revision is a new version."""

    __tablename__ = "quotes"
    __table_args__ = (
        CheckConstraint(enum_check("status", QuoteStatus), name="status_valid"),
        CheckConstraint(enum_check("service_method", ServiceMethod), name="service_method_valid"),
        CheckConstraint("currency IN ('NGN', 'GHS')", name="currency_valid"),
        CheckConstraint("labour_minor >= 0 AND materials_minor >= 0", name="amounts_non_negative"),
        CheckConstraint("total_minor = labour_minor + materials_minor", name="total_is_sum"),
        CheckConstraint("total_minor > 0", name="total_positive"),
        Index("uq_quotes_conversation_version", "conversation_id", "version", unique=True),
        Index(
            "uq_quotes_one_pending_per_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index("ix_quotes_service_request", "service_request_id", "status"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False
    )
    service_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_requests.id", ondelete="RESTRICT")
    )
    professional_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("professional_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    labour_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    materials_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    completion_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_terms: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    service_method: Mapped[str] = mapped_column(String(24), nullable=False)
    milestones: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default="[]")
    valid_until: Mapped[datetime] = mapped_column(nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column()


class Agreement(UUIDPrimaryKey, CreatedAt, Base):
    """Immutable accepted terms. ``canonical_json`` holds the exact RFC 8785 bytes that were hashed."""

    __tablename__ = "agreements"
    __table_args__ = (
        CheckConstraint(
            "agreement_hash = encode(sha256(convert_to(canonical_json, 'UTF8')), 'hex')",
            name="hash_matches_document",
        ),
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(unique=True, nullable=False)
    quote_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quotes.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    professional_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("professional_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    canonical_json: Mapped[str] = mapped_column(Text, nullable=False)
    agreement_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    accepted_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    accepted_at: Mapped[datetime] = mapped_column(nullable=False)
