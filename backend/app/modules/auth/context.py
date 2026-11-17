from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.modules.users.models import Role, User


@dataclass(frozen=True, slots=True)
class AuthContext:
    """The authenticated caller for one request."""

    user: User
    session_id: uuid.UUID

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    @property
    def role(self) -> Role:
        return Role(self.user.role)

    @property
    def is_admin(self) -> bool:
        return self.user.role == Role.ADMIN.value
