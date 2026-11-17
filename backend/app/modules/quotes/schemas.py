from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from app.core.schemas import APIModel, ResponseModel
from app.modules.professionals.models import Currency
from app.modules.quotes.models import QuoteStatus, ServiceMethod

MinorAmount = Annotated[
    int, Field(ge=0, le=1_000_000_000_000, description="Integer minor units (kobo/pesewas)")
]


class Milestone(APIModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    percent: Annotated[int, Field(ge=1, le=100)]


class QuoteIn(APIModel):
    conversation_id: uuid.UUID
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=120)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    labour_minor: MinorAmount
    materials_minor: MinorAmount
    currency: Currency
    completion_date: date
    payment_terms: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    service_method: ServiceMethod = ServiceMethod.EITHER
    milestones: Annotated[list[Milestone], Field(max_length=10)] = Field(
        default_factory=list, description="Descriptive work steps only: UniFix escrow is a single payment"
    )
    valid_until: datetime | None = Field(default=None, description="Defaults to 7 days; at most 30 days")

    @model_validator(mode="after")
    def _valid(self) -> Self:
        if self.labour_minor + self.materials_minor <= 0:
            raise ValueError("a quote must have a positive total")
        if self.milestones and sum(m.percent for m in self.milestones) != 100:
            raise ValueError("milestone percentages must add up to 100")
        return self


class RejectIn(APIModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class QuoteOut(ResponseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    service_request_id: uuid.UUID | None
    professional_id: uuid.UUID
    customer_id: uuid.UUID
    version: int
    status: QuoteStatus
    title: str
    description: str
    labour_minor: int
    materials_minor: int
    total_minor: int
    currency: Currency
    completion_date: date
    payment_terms: str
    service_method: ServiceMethod
    milestones: list[dict[str, object]]
    valid_until: datetime
    expired: bool
    created_at: datetime
    accepted_at: datetime | None
    agreement_hash: str | None
