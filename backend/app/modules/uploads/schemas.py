from __future__ import annotations

import uuid

from app.core.schemas import ResponseModel
from app.modules.uploads.models import FilePurpose


class FileRef(ResponseModel):
    id: uuid.UUID
    url: str
    signed_url: str | None
    name: str
    content_type: str
    size: int
    width: int | None
    height: int | None
    purpose: FilePurpose
