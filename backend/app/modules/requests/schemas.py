from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from app.core.schemas import APIModel, ResponseModel
from app.modules.campuses.schemas import CampusSummary, Latitude, Longitude
from app.modules.requests.models import RequestStatus
from app.modules.uploads.schemas import FileRef

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=120)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=4000)]
Item = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Location = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class ServiceRequestIn(APIModel):
    category_id: uuid.UUID
    title: Title
    description: Description
    item: Item | None = None
    campus_id: uuid.UUID | None = None
    location_text: Location | None = Field(
        default=None, description="Private: shown to the professional only after funding"
    )
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    preferred_start: datetime | None = None
    preferred_end: datetime | None = None
    media_file_ids: Annotated[list[uuid.UUID], Field(max_length=8)] = Field(default_factory=list)
    target_professional_id: uuid.UUID | None = Field(
        default=None, description="Send to one professional only (hidden from everyone else's feed)"
    )

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        if self.preferred_start and self.preferred_end and self.preferred_end < self.preferred_start:
            raise ValueError("preferred_end must be after preferred_start")
        return self


class RespondIn(APIModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class ServiceRequestOut(ResponseModel):
    """What professionals see: no exact location, no coordinates, no customer contact details."""

    id: uuid.UUID
    category_id: uuid.UUID
    category: str
    title: str
    description: str
    item: str | None
    campus: CampusSummary | None
    city: str | None
    preferred_start: datetime | None
    preferred_end: datetime | None
    status: RequestStatus
    media: list[FileRef]
    targeted: bool
    created_at: datetime
    expires_at: datetime
    responded: bool = Field(default=False, description="Whether you (a professional) already responded")


class ServiceRequestOwnerOut(ServiceRequestOut):
    """The customer's own view."""

    location_text: str | None
    latitude: str | None
    longitude: str | None
    target_professional_id: uuid.UUID | None
    conversation_ids: list[uuid.UUID]
