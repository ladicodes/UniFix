from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import StringConstraints

from app.core.schemas import APIModel, ResponseModel
from app.modules.calls.models import CallStatus


class IceServer(ResponseModel):
    urls: list[str]


class StartCallIn(APIModel):
    conversation_id: uuid.UUID


class EndCallIn(APIModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=64)] | None = None


class CallSessionOut(ResponseModel):
    session_id: uuid.UUID
    conversation_id: uuid.UUID
    initiator_id: uuid.UUID
    status: CallStatus
    created_at: datetime
    answered_at: datetime | None
    ended_at: datetime | None
    ice_servers: list[IceServer]
