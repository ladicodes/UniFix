from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field, StringConstraints

from app.core.schemas import APIModel, ResponseModel
from app.modules.bookings.models import BookingStatus, TimelineActor
from app.modules.chat.schemas import PublicUser
from app.modules.disputes.schemas import DisputeOut
from app.modules.payments.schemas import EscrowOut
from app.modules.professionals.models import Currency
from app.modules.professionals.schemas import ProfessionalOut
from app.modules.quotes.schemas import QuoteOut
from app.modules.reviews.schemas import ReviewOut


class AcceptQuoteIn(APIModel):
    service_address: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)] | None
    ) = Field(default=None, description="Where the job happens; shown to the professional only once funded")


class CancelBookingIn(APIModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class TimelineEvent(ResponseModel):
    at: datetime
    label: str
    actor: TimelineActor
    from_status: BookingStatus | None
    to_status: BookingStatus | None


class BookingOut(ResponseModel):
    id: uuid.UUID
    quote_id: uuid.UUID
    agreement_id: uuid.UUID
    agreement_hash: str
    conversation_id: uuid.UUID
    service_request_id: uuid.UUID | None
    customer_id: uuid.UUID
    professional_id: uuid.UUID
    title: str
    address: str | None = Field(description="Visible to the professional only from FUNDED onwards")
    status: BookingStatus
    amount_minor: int
    currency: Currency
    payment_due_by: datetime
    created_at: datetime
    escrow_id: uuid.UUID | None = None
    completion: dict[str, object] | None = None
    dispute_id: uuid.UUID | None = None
    review_id: uuid.UUID | None = None
    cancellation_reason: str | None
    timeline: list[TimelineEvent]


class BookingBundle(ResponseModel):
    booking: BookingOut
    quote: QuoteOut
    escrow: EscrowOut | None = None
    professional: ProfessionalOut
    customer: PublicUser
    dispute: DisputeOut | None = None
    review: ReviewOut | None = None
    allowed_actions: list[str]


class AgreementProof(ResponseModel):
    agreement_json: str = Field(description="Exact RFC 8785 canonical bytes (UTF-8) that were hashed")
    agreement_hash: str = Field(description="SHA-256 hex of agreement_json")
    escrow_terms_json: str | None = Field(
        default=None, description="Added when the escrow is prepared (Issue 6)"
    )
    terms_hash: str | None = None
