from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field, StringConstraints

from app.core.schemas import APIModel, ResponseModel
from app.modules.campuses.schemas import CampusOut
from app.modules.users.models import AccountStatus, Country, Role, User

FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
City = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
PhoneE164 = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\+[1-9]\d{7,14}$")]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class UserOut(ResponseModel):
    id: uuid.UUID
    name: str
    email: str
    role: Role
    status: AccountStatus
    email_verified: bool
    city: str | None
    country: Country
    phone: str | None
    created_at: datetime
    avatar_url: str | None = None
    campus: CampusOut | None = None
    professional_id: uuid.UUID | None = None
    wallet_address: str | None = None
    wallet_verified: bool = False

    @classmethod
    def from_user(
        cls,
        user: User,
        *,
        campus: CampusOut | None = None,
        professional_id: uuid.UUID | None = None,
        avatar_url: str | None = None,
    ) -> UserOut:
        return cls(
            avatar_url=avatar_url,
            campus=campus,
            professional_id=professional_id,
            id=user.id,
            name=user.full_name,
            email=user.email,
            role=Role(user.role),
            status=AccountStatus(user.status),
            email_verified=user.email_verified_at is not None,
            city=user.city,
            country=Country(user.country),
            phone=user.phone,
            created_at=user.created_at,
        )


class UpdateMeIn(APIModel):
    name: FullName | None = None
    city: City | None = None
    campus_id: uuid.UUID | None = Field(default=None, description="Self-declared campus; null clears it")
    avatar_file_id: uuid.UUID | None = Field(default=None, description="An AVATAR upload; null clears it")
    phone: PhoneE164 | None = Field(default=None, description="E.164 format, e.g. +2348012345678")


class AdminStatusChangeIn(APIModel):
    status: AccountStatus
    reason: Reason = Field(description="Why the status is changing; recorded in the audit log.")
