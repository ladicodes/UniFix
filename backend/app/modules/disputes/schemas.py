from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.core.schemas import APIModel, ResponseModel
from app.modules.disputes.models import DisputeOutcome, DisputeReason, DisputeStatus
from app.modules.payments.schemas import EscrowOut
from app.modules.uploads.schemas import FileRef


class OpenDisputeIn(APIModel):
    reason: DisputeReason
    details: str = Field(min_length=10, max_length=4000)


class LockIn(APIModel):
    """Empty body re-prepares the on-chain lock; ``{signed_xdr}`` submits it."""

    signed_xdr: str | None = Field(default=None, min_length=1, max_length=20_000)


class EvidenceIn(APIModel):
    note: str = Field(min_length=1, max_length=4000)
    file_id: uuid.UUID | None = None


class ResolveIn(APIModel):
    """Prepare with ``{outcome, split_bps_to_professional?, note}``; submit with ``{signed_xdr}``."""

    outcome: DisputeOutcome | None = Field(default=None, description="RELEASE | REFUND | SPLIT")
    split_bps_to_professional: int | None = Field(default=None, ge=1, le=9999)
    note: str | None = Field(default=None, min_length=3, max_length=4000)
    signed_xdr: str | None = Field(default=None, min_length=1, max_length=20_000)


class SlaOut(ResponseModel):
    evidence_closes_at: datetime | None
    decision_due_at: datetime | None
    escalation_level: int
    escalated_at: datetime | None


class EvidenceOut(ResponseModel):
    id: uuid.UUID
    submitted_by: uuid.UUID
    note: str
    file: FileRef | None
    created_at: datetime


class DisputeOut(ResponseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    escrow_id: uuid.UUID
    opened_by: uuid.UUID
    reason: DisputeReason
    details: str
    status: DisputeStatus
    opened_at: datetime
    locked_at: datetime | None
    outcome: DisputeOutcome | None
    sla: SlaOut
    split_bps_to_professional: int | None
    resolution_note: str | None
    resolved_at: datetime | None
    evidence: list[EvidenceOut]


class DisputePreparedOut(ResponseModel):
    dispute: DisputeOut
    escrow: EscrowOut
    unsigned_xdr: str
    tx_hash: str
    valid_until: datetime


class DisputeBundle(ResponseModel):
    dispute: DisputeOut
    escrow: EscrowOut
    booking_title: str
    customer_id: uuid.UUID
    professional_id: uuid.UUID
