"""Professional schemas.

Public and private shapes are separate types: ``ProfessionalOut`` (anyone) never contains
coordinates, verification documents, reviewer identities or listing internals;
``ProfessionalPrivateOut`` (the owner) adds them.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from app.core.schemas import APIModel, ResponseModel
from app.modules.campuses.schemas import CampusSummary, Latitude, Longitude, Slug
from app.modules.professionals.models import (
    Availability,
    CheckStatus,
    Currency,
    VerificationStatus,
    VerificationType,
)
from app.modules.uploads.schemas import FileRef
from app.modules.users.models import Country

Headline = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=120)]
Bio = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Place = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Area = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Caption = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
MinorAmount = Annotated[int, Field(ge=0, le=10_000_000_000, description="Integer minor units (kobo/pesewas)")]
Years = Annotated[int, Field(ge=0, le=60)]
Tags = Annotated[list[Tag], Field(max_length=30)]


def _dedupe(values: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for value in values:
        seen.setdefault(value.lower(), value)
    return list(seen.values())


class _CoordinatesMixin(APIModel):
    latitude: Latitude | None = Field(default=None, description="Approximate; rounded to ~1 km, never shown")
    longitude: Longitude | None = None

    @model_validator(mode="after")
    def _paired(self) -> Self:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class ProfessionalCreateIn(_CoordinatesMixin):
    category_slug: Slug = Field(description="Primary service category")
    category_slugs: Annotated[list[Slug], Field(max_length=10)] = Field(
        default_factory=list, description="Additional categories"
    )
    headline: Headline
    bio: Bio = ""
    city: Place
    area: Area = ""
    country: Country
    coverage: Tags = Field(default_factory=list, description="Areas/neighbourhoods served")
    campus_ids: Annotated[list[uuid.UUID], Field(max_length=20)] = Field(default_factory=list)
    years_experience: Years = 0
    starting_price_minor: MinorAmount = 0
    currency: Currency = Currency.NGN
    availability: Availability = Availability.TODAY
    skills: Tags = Field(default_factory=list)
    languages: Tags = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalise(self) -> Self:
        self.skills, self.languages, self.coverage = (
            _dedupe(self.skills),
            _dedupe(self.languages),
            _dedupe(self.coverage),
        )
        return self


class ProfessionalUpdateIn(_CoordinatesMixin):
    category_slug: Slug | None = None
    category_slugs: Annotated[list[Slug], Field(max_length=10)] | None = None
    headline: Headline | None = None
    bio: Bio | None = None
    city: Place | None = None
    area: Area | None = None
    coverage: Tags | None = None
    campus_ids: Annotated[list[uuid.UUID], Field(max_length=20)] | None = None
    years_experience: Years | None = None
    starting_price_minor: MinorAmount | None = None
    currency: Currency | None = None
    availability: Availability | None = None
    skills: Tags | None = None
    languages: Tags | None = None
    is_listed: bool | None = None


class VerificationFlags(ResponseModel):
    identity: bool
    trade: bool
    phone: bool


class RatingBreakdown(ResponseModel):
    quality: float
    punctuality: float
    communication: float
    professionalism: float
    value: float


class PortfolioItemOut(ResponseModel):
    id: uuid.UUID
    title: str
    caption: str
    image_url: str
    category_id: uuid.UUID | None


class ProfessionalOut(ResponseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    avatar_url: str | None
    category: str
    categories: list[str]
    headline: str
    bio: str
    city: str
    area: str
    country: Country
    campuses: list[CampusSummary]
    distance_km: float | None
    coverage: list[str]
    skills: list[str]
    languages: list[str]
    rating: float
    review_count: int
    completed_jobs: int
    years_experience: int
    verification: VerificationFlags
    verification_status: VerificationStatus
    availability: Availability
    response_minutes: int | None
    starting_price_minor: int
    currency: Currency
    portfolio: list[PortfolioItemOut]
    rating_breakdown: RatingBreakdown
    joined_at: datetime


class VerificationOut(ResponseModel):
    id: uuid.UUID
    type: VerificationType
    status: CheckStatus
    note: str | None
    files: list[FileRef]
    submitted_at: datetime
    reviewed_at: datetime | None
    rejection_reason: str | None


class ProfessionalPrivateOut(ProfessionalOut):
    is_listed: bool
    latitude: Decimal | None
    longitude: Decimal | None
    verifications: list[VerificationOut]


class PortfolioCreateIn(APIModel):
    title: Title
    caption: Caption = ""
    category_id: uuid.UUID | None = None
    image_file_id: uuid.UUID


class PortfolioUpdateIn(APIModel):
    title: Title | None = None
    caption: Caption | None = None
    category_id: uuid.UUID | None = None
    sort_order: Annotated[int, Field(ge=0, le=1000)] | None = None


class VerificationSubmitIn(APIModel):
    type: VerificationType
    file_ids: Annotated[list[uuid.UUID], Field(max_length=5)] = Field(default_factory=list)
    note: Note | None = None

    @model_validator(mode="after")
    def _documents_required(self) -> Self:
        if self.type is not VerificationType.PHONE and not self.file_ids:
            raise ValueError("IDENTITY and TRADE verification need at least one document")
        return self


class VerificationDecisionIn(APIModel):
    decision: CheckStatus = Field(description="VERIFIED or REJECTED")
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)] | None = (
        None
    )

    @model_validator(mode="after")
    def _valid(self) -> Self:
        if self.decision is CheckStatus.PENDING:
            raise ValueError("decision must be VERIFIED or REJECTED")
        if self.decision is CheckStatus.REJECTED and not self.reason:
            raise ValueError("a reason is required when rejecting")
        return self


class AdminVerificationOut(ResponseModel):
    id: uuid.UUID
    professional_id: uuid.UUID
    professional_name: str
    professional_email: str
    type: VerificationType
    status: CheckStatus
    note: str | None
    files: list[FileRef]
    submitted_at: datetime
    reviewed_at: datetime | None
    rejection_reason: str | None
