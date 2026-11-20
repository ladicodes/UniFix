from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.core.schemas import APIModel, ResponseModel
from app.modules.reviews.models import ReviewStatus

Rating = Field(ge=1, le=5)


class Ratings(APIModel):
    quality: int = Rating
    punctuality: int = Rating
    communication: int = Rating
    professionalism: int = Rating
    value: int = Rating


class ReviewIn(APIModel):
    ratings: Ratings
    comment: str = Field(min_length=1, max_length=2000)


class ResponseIn(APIModel):
    body: str = Field(min_length=1, max_length=2000)


class ReviewReportIn(APIModel):
    reason: str = Field(min_length=3, max_length=64)
    details: str | None = Field(default=None, max_length=2000)


class ModerationAction(StrEnum):
    HIDE = "HIDE"
    RESTORE = "RESTORE"
    REMOVE = "REMOVE"


class ModerateIn(APIModel):
    action: ModerationAction
    reason: str = Field(min_length=3, max_length=500)


class RatingsOut(ResponseModel):
    quality: int
    punctuality: int
    communication: int
    professionalism: int
    value: int


class ReviewResponseOut(ResponseModel):
    body: str
    created_at: datetime


class ReviewOut(ResponseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    professional_id: uuid.UUID
    customer_id: uuid.UUID
    customer_name: str
    job_title: str
    ratings: RatingsOut
    overall: float = Field(description="Mean of the five ratings, one decimal")
    comment: str
    status: ReviewStatus
    created_at: datetime
    response: ReviewResponseOut | None
