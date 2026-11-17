from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAt, UUIDPrimaryKey, enum_check


class CallStatus(StrEnum):
    RINGING = "RINGING"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    MISSED = "MISSED"
    DECLINED = "DECLINED"


LIVE_STATUSES = (CallStatus.RINGING.value, CallStatus.ACTIVE.value)


class CallSession(UUIDPrimaryKey, CreatedAt, Base):
    """Signaling state only. Media flows peer-to-peer between browsers (WebRTC)."""

    __tablename__ = "call_sessions"
    __table_args__ = (
        CheckConstraint(enum_check("status", CallStatus), name="status_valid"),
        Index(
            "uq_call_sessions_live_per_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("status IN ('RINGING', 'ACTIVE')"),
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    initiator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column()
    ended_at: Mapped[datetime | None] = mapped_column()
    end_reason: Mapped[str | None] = mapped_column(String(64))
