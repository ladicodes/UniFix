"""Escrow mirror, chain transactions and events, the append-only payment ledger, receipts and
cancellation requests (DATABASE_DESIGN §3, Issue 6). Fiat (``*_minor`` bigint + currency) and
token (``*_units`` numeric(39,0) + asset identity) amounts never share a column."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAt, Timestamps, UUIDPrimaryKey, enum_check

UNITS = Numeric(39, 0)  # fits i128


class EscrowState(StrEnum):
    CREATED = "CREATED"
    FUNDED = "FUNDED"
    COMPLETION_SUBMITTED = "COMPLETION_SUBMITTED"
    DISPUTED = "DISPUTED"
    RELEASED = "RELEASED"
    REFUNDED = "REFUNDED"
    RESOLVED = "RESOLVED"


TERMINAL_ESCROW_STATES = frozenset({EscrowState.RELEASED, EscrowState.REFUNDED, EscrowState.RESOLVED})


class Reconciliation(StrEnum):
    AWAITING_SIGNATURE = "AWAITING_SIGNATURE"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class TxKind(StrEnum):
    FUND = "FUND"
    SUBMIT_COMPLETION = "SUBMIT_COMPLETION"
    RELEASE = "RELEASE"
    REFUND = "REFUND"
    EXTEND = "EXTEND"
    DISPUTE = "DISPUTE"
    RESOLVE = "RESOLVE"
    FINALIZE = "FINALIZE"


class TxStatus(StrEnum):
    PREPARED = "PREPARED"  # built and simulated; waiting for the wallet signature
    SUBMITTED = "SUBMITTED"  # signed and stored; the send outcome is not yet known
    PENDING = "PENDING"  # accepted by the RPC; waiting for a ledger
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


IN_FLIGHT = (TxStatus.PREPARED, TxStatus.SUBMITTED, TxStatus.PENDING)
_IN_FLIGHT_SQL = ", ".join(f"'{s.value}'" for s in IN_FLIGHT)


class EventStatus(StrEnum):
    INGESTED = "INGESTED"
    APPLIED = "APPLIED"
    APPLIED_NOOP = "APPLIED_NOOP"
    CONFLICT = "CONFLICT"


class EventSource(StrEnum):
    TX_RESULT = "TX_RESULT"
    EVENT_SCAN = "EVENT_SCAN"
    STATE_SYNC = "STATE_SYNC"


class LedgerEntryType(StrEnum):
    CUSTOMER_FUNDING = "CUSTOMER_FUNDING"
    PROFESSIONAL_PAYOUT = "PROFESSIONAL_PAYOUT"
    CUSTOMER_REFUND = "CUSTOMER_REFUND"


class ReceiptKind(StrEnum):
    FUNDING = "FUNDING"
    RELEASE = "RELEASE"
    REFUND = "REFUND"
    RESOLUTION = "RESOLUTION"


class CancellationStatus(StrEnum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class Escrow(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "escrows"
    __table_args__ = (
        CheckConstraint(enum_check("state", EscrowState), name="state_valid"),
        CheckConstraint(enum_check("reconciliation", Reconciliation), name="reconciliation_valid"),
        CheckConstraint("asset_units > 0", name="asset_units_positive"),
        CheckConstraint("fiat_amount_minor > 0", name="fiat_amount_positive"),
        CheckConstraint("fx_rate > 0", name="fx_rate_positive"),
        CheckConstraint("fx_source <> 'DEMO_FIXED_RATE' OR is_demo_rate", name="demo_rate_labelled"),
        CheckConstraint(
            "terms_hash = encode(sha256(convert_to(terms_canonical_json, 'UTF8')), 'hex')",
            name="terms_hash_matches",
        ),
        CheckConstraint(
            "state NOT IN ('RELEASED', 'REFUNDED', 'RESOLVED') OR "
            "professional_payout_units + customer_refund_units = asset_units",
            name="terminal_amounts_sum",
        ),
        CheckConstraint("octet_length(escrow_key) = 32", name="escrow_key_length"),
        Index("ix_escrows_keeper_refund", "state", "refund_after"),
        Index("ix_escrows_keeper_review", "state", "review_deadline"),
        Index("ix_escrows_customer_wallet", "customer_wallet"),
        Index("ix_escrows_professional_wallet", "professional_wallet"),
        Index("ix_escrows_created_at", "created_at"),
        Index(
            "ix_escrows_failed_verification",
            "created_at",
            postgresql_where=text("verification_error IS NOT NULL"),
        ),
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    network: Mapped[str] = mapped_column(String(8), nullable=False)
    network_passphrase: Mapped[str] = mapped_column(String(80), nullable=False)
    network_epoch: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_id: Mapped[str] = mapped_column(String(56), nullable=False)
    escrow_key: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=False)
    asset_code: Mapped[str] = mapped_column(String(12), nullable=False)
    asset_issuer: Mapped[str] = mapped_column(String(56), nullable=False)
    asset_sac_contract_id: Mapped[str] = mapped_column(String(56), nullable=False)
    asset_decimals: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    asset_units: Mapped[Decimal] = mapped_column(UNITS, nullable=False)
    fiat_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fiat_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    fx_base: Mapped[str] = mapped_column(String(12), nullable=False)
    fx_quote: Mapped[str] = mapped_column(String(3), nullable=False)
    fx_source: Mapped[str] = mapped_column(String(32), nullable=False)
    is_demo_rate: Mapped[bool] = mapped_column(nullable=False)
    fx_locked_at: Mapped[datetime] = mapped_column(nullable=False)
    customer_wallet: Mapped[str] = mapped_column(String(56), nullable=False)
    professional_wallet: Mapped[str] = mapped_column(String(56), nullable=False)
    refund_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    review_window: Mapped[int] = mapped_column(BigInteger, nullable=False)
    review_deadline: Mapped[int | None] = mapped_column(BigInteger)
    disputed_at: Mapped[int | None] = mapped_column(BigInteger)
    terms_canonical_json: Mapped[str] = mapped_column(Text, nullable=False)
    terms_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    agreement_hash: Mapped[str] = mapped_column(
        ForeignKey("agreements.agreement_hash", ondelete="RESTRICT"), nullable=False
    )
    evidence_hash: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    reconciliation: Mapped[str] = mapped_column(String(24), nullable=False)
    settled_by: Mapped[str | None] = mapped_column(String(16))
    professional_payout_units: Mapped[Decimal | None] = mapped_column(UNITS)
    customer_refund_units: Mapped[Decimal | None] = mapped_column(UNITS)
    funded_at_chain: Mapped[int | None] = mapped_column(BigInteger)
    verification_error: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    last_synced_ledger: Mapped[int | None] = mapped_column(Integer)
    last_synced_at: Mapped[datetime | None] = mapped_column()
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012  (optimistic locking)


class ChainTransaction(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "chain_transactions"
    __table_args__ = (
        CheckConstraint(enum_check("kind", TxKind), name="kind_valid"),
        CheckConstraint(enum_check("status", TxStatus), name="status_valid"),
        Index(
            "uq_chain_transactions_in_flight",
            "escrow_id",
            "kind",
            unique=True,
            postgresql_where=text(f"status IN ({_IN_FLIGHT_SQL})"),
        ),
        Index("ix_chain_transactions_status_checked", "status", "last_checked_at"),
        Index("ix_chain_transactions_escrow", "escrow_id", "created_at"),
    )

    escrow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("escrows.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_account: Mapped[str] = mapped_column(String(56), nullable=False)
    unsigned_envelope_xdr: Mapped[str] = mapped_column(Text, nullable=False)
    signed_envelope_xdr: Mapped[str | None] = mapped_column(Text)  # a public, signed tx; holds no secret
    valid_until: Mapped[datetime] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    ledger: Mapped[int | None] = mapped_column(Integer)
    ledger_closed_at: Mapped[datetime | None] = mapped_column()
    fee_stroops: Mapped[Decimal | None] = mapped_column(UNITS)
    result_code: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    submitted_at: Mapped[datetime | None] = mapped_column()
    last_checked_at: Mapped[datetime | None] = mapped_column()
    confirmed_at: Mapped[datetime | None] = mapped_column()


class ChainEvent(UUIDPrimaryKey, Base):
    """Ingested contract events: the unit of exactly-once processing. Never deleted."""

    __tablename__ = "chain_events"
    __table_args__ = (
        CheckConstraint(enum_check("status", EventStatus), name="status_valid"),
        CheckConstraint(enum_check("source", EventSource), name="source_valid"),
        Index("uq_chain_events_tx_event", "tx_hash", "event_index", unique=True),
        Index("ix_chain_events_apply_order", "escrow_key", "status", "ledger", "tx_index", "event_index"),
        Index("ix_chain_events_status", "status", "ledger"),
    )

    contract_id: Mapped[str] = mapped_column(String(56), nullable=False)
    ledger: Mapped[int] = mapped_column(Integer, nullable=False)
    ledger_closed_at: Mapped[datetime] = mapped_column(nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    tx_index: Mapped[int] = mapped_column(Integer, nullable=False)
    event_index: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    escrow_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=EventStatus.INGESTED.value)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column()
    error: Mapped[str | None] = mapped_column(Text)


class ChainSyncState(Base):
    __tablename__ = "chain_sync_state"

    contract_id: Mapped[str] = mapped_column(String(56), primary_key=True)
    last_ledger: Mapped[int | None] = mapped_column(Integer)
    cursor: Mapped[str | None] = mapped_column(String(64))
    leader_instance: Mapped[str | None] = mapped_column(String(64))
    leader_since: Mapped[datetime | None] = mapped_column()
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_at: Mapped[datetime | None] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(nullable=False)


class LedgerEntry(UUIDPrimaryKey, CreatedAt, Base):
    """Append-only payment ledger, written only from confirmed chain events (trigger-enforced)."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint(enum_check("type", LedgerEntryType), name="type_valid"),
        CheckConstraint("asset_units > 0", name="asset_units_positive"),
        Index("uq_ledger_entries_tx_type", "tx_hash", "type", unique=True),
        Index("ix_ledger_entries_booking", "booking_id"),
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False
    )
    escrow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("escrows.id", ondelete="RESTRICT"), nullable=False
    )
    chain_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chain_events.id", ondelete="RESTRICT"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(24), nullable=False)
    asset_units: Mapped[Decimal] = mapped_column(UNITS, nullable=False)
    asset_code: Mapped[str] = mapped_column(String(12), nullable=False)
    asset_issuer: Mapped[str] = mapped_column(String(56), nullable=False)
    from_address: Mapped[str] = mapped_column(String(56), nullable=False)
    to_address: Mapped[str] = mapped_column(String(56), nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ledger: Mapped[int] = mapped_column(Integer, nullable=False)


class Receipt(UUIDPrimaryKey, Base):
    __tablename__ = "receipts"
    __table_args__ = (
        CheckConstraint(enum_check("kind", ReceiptKind), name="kind_valid"),
        CheckConstraint(
            "payload_hash = encode(sha256(convert_to(payload_canonical_json, 'UTF8')), 'hex')",
            name="payload_hash_matches",
        ),
        Index("uq_receipts_escrow_kind", "escrow_id", "kind", unique=True),
        Index("ix_receipts_booking", "booking_id"),
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False
    )
    escrow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("escrows.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    asset_units: Mapped[Decimal] = mapped_column(UNITS, nullable=False)
    asset_code: Mapped[str] = mapped_column(String(12), nullable=False)
    asset_issuer: Mapped[str] = mapped_column(String(56), nullable=False)
    fiat_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fiat_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    fx_source: Mapped[str] = mapped_column(String(32), nullable=False)
    is_demo_rate: Mapped[bool] = mapped_column(nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ledger: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_canonical_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(nullable=False)


class CancellationRequest(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "cancellation_requests"
    __table_args__ = (
        CheckConstraint(enum_check("status", CancellationStatus), name="status_valid"),
        Index(
            "uq_cancellation_requests_open",
            "booking_id",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
        ),
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    responded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    responded_at: Mapped[datetime | None] = mapped_column()
    decline_reason: Mapped[str | None] = mapped_column(String(1000))
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
