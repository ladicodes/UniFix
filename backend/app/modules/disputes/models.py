from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, SmallInteger, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAt, Timestamps, UUIDPrimaryKey, enum_check


class DisputeReason(StrEnum):
    INCOMPLETE = "INCOMPLETE"
    DAMAGED = "DAMAGED"
    NO_SHOW = "NO_SHOW"
    PRICE_CHANGED = "PRICE_CHANGED"
    QUALITY = "QUALITY"
    OTHER = "OTHER"


class DisputeStatus(StrEnum):
    OPEN = "OPEN"  # recorded; the on-chain lock is not confirmed yet (ordinary settlement already blocked)
    UNDER_REVIEW = "UNDER_REVIEW"  # locked on-chain; evidence and arbitration
    AWAITING_SETTLEMENT = "AWAITING_SETTLEMENT"  # the arbiter has prepared a resolution
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"  # the lock never happened (e.g. the deadline settled the escrow first)


ACTIVE_DISPUTE = (DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW, DisputeStatus.AWAITING_SETTLEMENT)


class DisputeOutcome(StrEnum):
    RELEASE = "RELEASE"
    REFUND = "REFUND"
    SPLIT = "SPLIT"
    CONCEDED_RELEASE = "CONCEDED_RELEASE"
    CONCEDED_REFUND = "CONCEDED_REFUND"


class Dispute(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "disputes"
    __table_args__ = (
        CheckConstraint(enum_check("reason", DisputeReason), name="reason_valid"),
        CheckConstraint(enum_check("status", DisputeStatus), name="status_valid"),
        CheckConstraint(f"outcome IS NULL OR {enum_check('outcome', DisputeOutcome)}", name="outcome_valid"),
        CheckConstraint(
            "split_bps_to_professional IS NULL OR split_bps_to_professional BETWEEN 0 AND 10000",
            name="split_range",
        ),
        CheckConstraint("escalation_level BETWEEN 0 AND 2", name="escalation_range"),
        Index(
            "uq_disputes_active_per_booking",
            "booking_id",
            unique=True,
            postgresql_where=text("status NOT IN ('RESOLVED', 'CLOSED')"),
        ),
        Index("ix_disputes_queue", "status", "decision_due_at"),
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False
    )
    escrow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("escrows.id", ondelete="RESTRICT"), nullable=False
    )
    opened_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reason: Mapped[str] = mapped_column(String(16), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(24))
    split_bps_to_professional: Mapped[int | None] = mapped_column(Integer)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column()
    locked_at: Mapped[datetime | None] = mapped_column()
    evidence_closes_at: Mapped[datetime | None] = mapped_column()
    decision_due_at: Mapped[datetime | None] = mapped_column()
    escalation_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    escalated_at: Mapped[datetime | None] = mapped_column()


class DisputeEvidence(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "dispute_evidence"
    __table_args__ = (Index("ix_dispute_evidence_dispute", "dispute_id", "created_at"),)

    dispute_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("disputes.id", ondelete="RESTRICT"), nullable=False
    )
    submitted_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    note: Mapped[str] = mapped_column(Text, nullable=False)
    file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("files.id", ondelete="RESTRICT"))
