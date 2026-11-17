from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status

from app.api.deps import CallerDep, OptionalCallerDep, ServicesDep, SessionDep
from app.core.errors import error_responses
from app.modules.uploads import service
from app.modules.uploads.models import FilePurpose, FileVisibility
from app.modules.uploads.rules import IMAGES
from app.modules.uploads.schemas import FileRef

router = APIRouter(tags=["uploads"])


@router.post(
    "/uploads",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 403, 413, 415, 422, 429),
    summary="Upload a file; the type is detected from its bytes and images are re-encoded (EXIF stripped)",
)
async def upload_file(
    file: Annotated[UploadFile, File(description="The file to upload")],
    purpose: Annotated[FilePurpose, Form()],
    caller: CallerDep,
    session: SessionDep,
    services: ServicesDep,
) -> FileRef:
    stored = await service.upload(session, services, caller, purpose, file)
    return service.file_ref(services, stored)


@router.get(
    "/files/{file_id}",
    response_class=Response,
    responses={200: {"content": {"image/*": {}, "application/pdf": {}}}, **error_responses(404)},
    summary="Download a file (public, owner/authorised user via Bearer, or a short-lived signed URL)",
)
async def download_file(
    file_id: uuid.UUID,
    session: SessionDep,
    services: ServicesDep,
    caller: OptionalCallerDep,
    exp: Annotated[int | None, Query(description="Signed URL expiry (unix seconds)")] = None,
    sig: Annotated[str | None, Query(max_length=64, description="Signed URL signature")] = None,
) -> Response:
    stored, data = await service.open_for_download(
        session, services, caller, file_id, expires=exp, signature=sig
    )
    disposition = "inline" if stored.content_type in IMAGES else "attachment"
    cache = (
        "public, max-age=86400" if stored.visibility == FileVisibility.PUBLIC.value else "private, no-store"
    )
    return Response(
        content=data,
        media_type=stored.content_type,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(stored.original_name)}",
            "Cache-Control": cache,
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
