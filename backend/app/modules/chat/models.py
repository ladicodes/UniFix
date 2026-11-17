from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Identity, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAt, UUIDPrimaryKey, enum_check


class MessageKind(StrEnum):
    TEXT = "TEXT"
    IMAGE = "IMAGE"
    QUOTE = "QUOTE"
    SYSTEM = "SYSTEM"


class MemberRole(StrEnum):
    CUSTOMER = "CUSTOMER"
    PROFESSIONAL = "PROFESSIONAL"


class ReportTarget(StrEnum):
    MESSAGE = "MESSAGE"
    CONVERSATION = "CONVERSATION"
    USER = "USER"
    REVIEW = "REVIEW"


class ReportStatus(StrEnum):
    OPEN = "OPEN"
    DISMISSED = "DISMISSED"
    ACTIONED = "ACTIONED"


class TicketScope(StrEnum):
    CONVERSATION = "CONVERSATION"


class Conversation(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "uq_conversations_direct",
            "customer_id",
            "professional_id",
            unique=True,
            postgresql_where=text("service_request_id IS NULL"),
        ),
        Index(
            "uq_conversations_request_professional",
            "service_request_id",
            "professional_id",
            unique=True,
            postgresql_where=text("service_request_id IS NOT NULL"),
        ),
        Index("ix_conversations_professional_last", "professional_id", "last_message_at"),
        Index("ix_conversations_customer_last", "customer_id", "last_message_at"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    professional_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("professional_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    service_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_requests.id", ondelete="RESTRICT")
    )
    last_message_at: Mapped[datetime | None] = mapped_column()
    last_message_preview: Mapped[str] = mapped_column(String(140), nullable=False, server_default="")
    # Seconds from the customer's first message to the professional's first reply (response-time metric).
    first_response_seconds: Mapped[int | None] = mapped_column(Integer)


class ConversationMember(Base):
    """The two participants. Drives access control, unread state and read receipts."""

    __tablename__ = "conversation_members"
    __table_args__ = (
        CheckConstraint(enum_check("role", MemberRole), name="role_valid"),
        Index("ix_conversation_members_user_id", "user_id"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    last_read_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    last_read_message_id: Mapped[uuid.UUID | None] = mapped_column()
    last_read_at: Mapped[datetime | None] = mapped_column()


class Message(UUIDPrimaryKey, CreatedAt, Base):
    """Persisted before any delivery event. ``seq`` gives a total order used for history cursors."""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(enum_check("kind", MessageKind), name="kind_valid"),
        CheckConstraint("char_length(body) <= 4000", name="body_length"),
        CheckConstraint("kind <> 'IMAGE' OR attachment_file_id IS NOT NULL", name="image_has_attachment"),
        CheckConstraint("kind <> 'SYSTEM' OR sender_id IS NULL", name="system_has_no_sender"),
        CheckConstraint("kind <> 'QUOTE' OR quote_id IS NOT NULL", name="quote_message_has_quote"),
        Index("ix_messages_conversation_seq", "conversation_id", "seq"),
        Index(
            "uq_messages_sender_client_id",
            "sender_id",
            "client_message_id",
            unique=True,
            postgresql_where=text("client_message_id IS NOT NULL"),
        ),
        Index("ix_messages_attachment_file_id", "attachment_file_id"),
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True, nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    sender_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    attachment_file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("files.id", ondelete="RESTRICT"))
    quote_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("quotes.id", ondelete="RESTRICT"))
    client_message_id: Mapped[uuid.UUID | None] = mapped_column()


class Report(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint(enum_check("target_type", ReportTarget), name="target_type_valid"),
        CheckConstraint(enum_check("status", ReportStatus), name="status_valid"),
        Index("uq_reports_reporter_target", "reporter_id", "target_type", "target_id", unique=True),
        Index("ix_reports_status_created", "status", "created_at"),
    )

    reporter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[str | None] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=ReportStatus.OPEN.value)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column()


class WebSocketTicket(UUIDPrimaryKey, CreatedAt, Base):
    """Single-use, 30-second WebSocket credential. Only its SHA-256 is stored."""

    __tablename__ = "ws_tickets"
    __table_args__ = (
        CheckConstraint(enum_check("scope", TicketScope), name="scope_valid"),
        CheckConstraint("scope <> 'CONVERSATION' OR conversation_id IS NOT NULL", name="conversation_scoped"),
        Index("ix_ws_tickets_expires_at", "expires_at"),
    )

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("auth_session_families.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    used_at: Mapped[datetime | None] = mapped_column()
