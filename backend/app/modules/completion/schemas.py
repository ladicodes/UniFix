from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.core.schemas import APIModel, ResponseModel
from app.modules.completion.models import SubmissionStatus
from app.modules.payments.schemas import EscrowOut
from app.modules.uploads.schemas import FileRef


class ChecklistItem(APIModel):
    label: str = Field(min_length=1, max_length=200)
    done: bool


class PrepareCompletionIn(APIModel):
    notes: str = Field(min_length=1, max_length=4000)
    checklist: list[ChecklistItem] = Field(default_factory=list, max_length=30)
    photo_file_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)


class SubmitCompletionIn(APIModel):
    signed_xdr: str = Field(min_length=1, max_length=20_000)


class CompletionOut(ResponseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    notes: str
    checklist: list[ChecklistItem]
    photos: list[FileRef]
    evidence_hash: str
    evidence_json: str = Field(description="Exact canonical bytes that evidence_hash covers")
    status: SubmissionStatus
    prepared_at: datetime
    submitted_at: datetime | None


class PreparedCompletionOut(ResponseModel):
    submission: CompletionOut
    escrow: EscrowOut
    unsigned_xdr: str
    tx_hash: str
    valid_until: datetime
