from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import EmailStr, Field, StringConstraints, field_validator

from app.core.schemas import APIModel, ResponseModel
from app.modules.users.models import Country, Role
from app.modules.users.schemas import City, FullName, UserOut

# Passwords are never trimmed or otherwise altered.
NewPassword = Annotated[str, StringConstraints(min_length=10, max_length=128)]
AnyPassword = Annotated[str, StringConstraints(min_length=1, max_length=128)]
OpaqueToken = Annotated[str, StringConstraints(min_length=20, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


def _normalise_email(value: str) -> str:
    return value.strip().lower()


class RegisterIn(APIModel):
    name: FullName
    email: EmailStr
    password: NewPassword
    role: Literal[Role.CUSTOMER, Role.PROFESSIONAL]
    city: City | None = None
    country: Country

    _email = field_validator("email")(_normalise_email)


class LoginIn(APIModel):
    email: EmailStr
    password: AnyPassword

    _email = field_validator("email")(_normalise_email)


class AuthResponse(ResponseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"  # noqa: S105  (OAuth token type)
    expires_in: int = Field(description="Access-token lifetime in seconds")
    user: UserOut


class SessionOut(ResponseModel):
    id: uuid.UUID
    created_at: datetime
    last_used_at: datetime
    user_agent: str | None
    ip_hint: str | None = Field(description="Coarse network of the client (IPv4 /16, IPv6 /32)")
    current: bool


class ChangePasswordIn(APIModel):
    current_password: AnyPassword
    new_password: NewPassword


class TokenIn(APIModel):
    token: OpaqueToken


class PasswordResetRequestIn(APIModel):
    email: EmailStr

    _email = field_validator("email")(_normalise_email)


class PasswordResetConfirmIn(APIModel):
    token: OpaqueToken
    new_password: NewPassword
