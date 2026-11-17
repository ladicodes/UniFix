from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import Field, StringConstraints

from app.core.schemas import APIModel, ResponseModel
from app.modules.users.models import Country

Slug = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=64)
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]
ShortName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=32)]
Place = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Latitude = Annotated[Decimal, Field(ge=-90, le=90, max_digits=9, decimal_places=6)]
Longitude = Annotated[Decimal, Field(ge=-180, le=180, max_digits=9, decimal_places=6)]


class CampusOut(ResponseModel):
    id: uuid.UUID
    slug: str
    name: str
    short_name: str
    city: str
    state: str | None
    country: Country


class CampusSummary(ResponseModel):
    id: uuid.UUID
    name: str
    short_name: str


class AdminCampusOut(CampusOut):
    latitude: Decimal | None
    longitude: Decimal | None
    is_active: bool


class CampusCreateIn(APIModel):
    slug: Slug
    name: Name
    short_name: ShortName
    city: Place
    state: Place | None = None
    country: Country
    latitude: Latitude | None = None
    longitude: Longitude | None = None


class CampusUpdateIn(APIModel):
    name: Name | None = None
    short_name: ShortName | None = None
    city: Place | None = None
    state: Place | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    is_active: bool | None = None
