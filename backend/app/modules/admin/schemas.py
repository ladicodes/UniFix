"""Admin read models. None of them carries a password hash, token hash, secret or transaction XDR."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from app.core.schemas import APIModel, ResponseModel


class AdminUserOut(ResponseModel):
    id: uuid.UUID
    email: str
    name: str
    role: str
    status: str
    country: str
    city: str | None
    campus_id: uuid.UUID | None
    email_verified: bool
    created_at: datetime
    last_login_at: datetime | None


class AdminWalletOut(ResponseModel):
    id: uuid.UUID
    network: str
    address: str
    is_primary: bool
    verified_at: datetime
    revoked_at: datetime | None


class AdminUserDetailOut(AdminUserOut):
    professional_id: uuid.UUID | None
    verification_status: str | None
    wallets: list[AdminWalletOut]
    active_sessions: int
    bookings_as_customer: int
    bookings_as_professional: int
    reports_filed: int
    reports_against: int


class AdminBookingOut(ResponseModel):
    id: uuid.UUID
    title: str
    status: str
    amount_minor: int
    currency: str
    customer_id: uuid.UUID
    professional_id: uuid.UUID
    conversation_id: uuid.UUID
    service_request_id: uuid.UUID | None
    escrow_id: uuid.UUID | None
    escrow_state: str | None
    created_at: datetime
    updated_at: datetime


class AdminEscrowOut(ResponseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    network: str
    contract_id: str
    state: str
    reconciliation: str
    asset_code: str
    asset_amount: str = Field(description="Token base units (integer string)")
    fiat_amount_minor: int
    fiat_currency: str
    is_demo_rate: bool
    customer_wallet: str
    professional_wallet: str
    refund_after: int
    review_deadline: int | None
    settled_by: str | None
    verification_error: str | None
    failure_reason: str | None
    last_synced_ledger: int | None
    created_at: datetime
    updated_at: datetime


class AdminChainTxOut(ResponseModel):
    id: uuid.UUID
    escrow_id: uuid.UUID
    kind: str
    status: str
    tx_hash: str
    source_account: str
    ledger: int | None
    result_code: str | None
    error: str | None
    attempts: int
    requested_by: uuid.UUID | None
    created_at: datetime
    submitted_at: datetime | None
    confirmed_at: datetime | None
    explorer_url: str


class AdminServiceRequestOut(ResponseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    category_id: uuid.UUID
    campus_id: uuid.UUID | None
    target_professional_id: uuid.UUID | None
    title: str
    status: str
    created_at: datetime
    expires_at: datetime


class AdminReportOut(ResponseModel):
    id: uuid.UUID
    reporter_id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    conversation_id: uuid.UUID | None
    reason: str
    details: str | None
    status: str
    resolved_by: uuid.UUID | None
    resolved_at: datetime | None
    resolution_note: str | None
    created_at: datetime


class ReportDecision(StrEnum):
    ACTIONED = "ACTIONED"
    DISMISSED = "DISMISSED"


class ResolveReportIn(APIModel):
    decision: ReportDecision
    note: str = Field(min_length=3, max_length=1000)


class AdminAuditLogOut(ResponseModel):
    id: int
    occurred_at: datetime
    actor_type: str
    actor_user_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    request_id: str | None
    ip: str | None
    data: dict[str, Any]


class RpcStatus(ResponseModel):
    configured: bool
    healthy: bool | None
    latest_ledger: int | None
    oldest_ledger: int | None
    error: str | None


class ReconcilerStatus(ResponseModel):
    enabled: bool
    last_ledger: int | None = Field(description="Last ledger the event scan committed")
    cursor_lag_ledgers: int | None = Field(description="latest_ledger - last_ledger")
    leader_instance: str | None
    leader_since: datetime | None
    last_error: str | None
    last_error_at: datetime | None
    updated_at: datetime | None


class OpsStatusOut(ResponseModel):
    checked_at: datetime
    pending_tx_count: int = Field(description="Transactions submitted and not yet final")
    awaiting_signature_count: int
    oldest_pending_age_seconds: int | None
    failed_verification_count: int = Field(description="Escrows flagged FAILED_VERIFICATION")
    conflict_event_count: int
    unapplied_event_count: int
    open_disputes: int
    open_reports: int
    rpc: RpcStatus
    reconciler: ReconcilerStatus
