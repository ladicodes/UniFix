from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAt, UUIDPrimaryKey, enum_check


class FilePurpose(StrEnum):
    AVATAR = "AVATAR"
    PORTFOLIO = "PORTFOLIO"
    VERIFICATION_DOCUMENT = "VERIFICATION_DOCUMENT"
    REQUEST_MEDIA = "REQUEST_MEDIA"
    MESSAGE_ATTACHMENT = "MESSAGE_ATTACHMENT"
    COMPLETION_EVIDENCE = "COMPLETION_EVIDENCE"
    DISPUTE_EVIDENCE = "DISPUTE_EVIDENCE"


class FileVisibility(StrEnum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


class StoredFile(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "files"
    __table_args__ = (
        CheckConstraint(enum_check("purpose", FilePurpose), name="purpose_valid"),
        CheckConstraint(enum_check("visibility", FileVisibility), name="visibility_valid"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        Index("ix_files_owner_purpose", "owner_user_id", "purpose"),
    )

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    deleted_at: Mapped[datetime | None] = mapped_column()
