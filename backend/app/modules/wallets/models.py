from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAt, UUIDPrimaryKey


class Wallet(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "wallets"
    __table_args__ = (
        CheckConstraint("network IN ('TESTNET', 'PUBLIC')", name="network_valid"),
        CheckConstraint("char_length(address) = 56 AND address LIKE 'G%'", name="address_shape"),
        Index(
            "uq_wallets_active_address",
            "network",
            "address",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index(
            "uq_wallets_primary_per_user",
            "user_id",
            "network",
            unique=True,
            postgresql_where=text("is_primary AND revoked_at IS NULL"),
        ),
        Index("ix_wallets_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    network: Mapped[str] = mapped_column(String(8), nullable=False)
    address: Mapped[str] = mapped_column(String(56), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(nullable=False)
    is_primary: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    revoked_at: Mapped[datetime | None] = mapped_column()


class WalletChallenge(UUIDPrimaryKey, CreatedAt, Base):
    """Single-use, 5-minute challenge bound to user + address + network."""

    __tablename__ = "wallet_challenges"
    __table_args__ = (Index("ix_wallet_challenges_user", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    network: Mapped[str] = mapped_column(String(8), nullable=False)
    address: Mapped[str] = mapped_column(String(56), nullable=False)
    nonce: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    used_at: Mapped[datetime | None] = mapped_column()
