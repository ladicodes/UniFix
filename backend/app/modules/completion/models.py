from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPrimaryKey, enum_check


class SubmissionStatus(StrEnum):
    PREPARED = "PREPARED"  # evidence recorded; waiting for the professional's on-chain signature
    SUBMITTED = "SUBMITTED"  # submit_completion confirmed on-chain (review window running)
    APPROVED = "APPROVED"  # payment released
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"


class CompletionSubmission(UUIDPrimaryKey, Base):
    __tablename__ = "completion_submissions"
    __table_args__ = (
        CheckConstraint(enum_check("status", SubmissionStatus), name="status_valid"),
        CheckConstraint(
            "evidence_hash = encode(sha256(convert_to(evidence_canonical_json, 'UTF8')), 'hex')",
            name="evidence_hash_matches",
        ),
        Index(
            "uq_completion_submissions_live",
            "booking_id",
            unique=True,
            postgresql_where=text("status IN ('PREPARED', 'SUBMITTED')"),
        ),
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False
    )
    submitted_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    checklist: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    evidence_canonical_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    prepared_at: Mapped[datetime] = mapped_column(nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column()
    decided_at: Mapped[datetime | None] = mapped_column()


class CompletionFile(Base):
    __tablename__ = "completion_files"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("completion_submissions.id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id", ondelete="RESTRICT"), primary_key=True)
