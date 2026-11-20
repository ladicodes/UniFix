from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.core.schemas import APIModel, ResponseModel
from app.modules.notifications.models import NotificationType


class NotificationOut(ResponseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    type: NotificationType
    title: str
    body: str
    href: str | None = Field(description="Frontend path to open, e.g. /bookings/{id}")
    created_at: datetime
    read_at: datetime | None


class MarkReadIn(APIModel):
    ids: list[uuid.UUID] | None = Field(
        default=None, min_length=1, max_length=100, description="Omit to mark every notification read"
    )


class UnreadCountOut(ResponseModel):
    count: int
