"""Upload validation, storage, signed URLs and authorised download."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import unicodedata
import uuid
from collections.abc import Sequence
from datetime import timedelta

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import API_PREFIX
from app.core.container import Services
from app.core.errors import BadRequest, Forbidden, NotFound, PayloadTooLarge
from app.core.ratelimit import rate_limit_key
from app.modules.audit import service as audit
from app.modules.auth.context import AuthContext
from app.modules.uploads import inspection, policy, repository
from app.modules.uploads.models import FilePurpose, FileVisibility, StoredFile
from app.modules.uploads.rules import RULES
from app.modules.uploads.schemas import FileRef

_CHUNK = 64 * 1024
_NAME_UNSAFE = re.compile(r"[^\w.\- ]+")


def _safe_name(raw: str | None) -> str:
    name = unicodedata.normalize("NFKC", (raw or "upload").replace("\\", "/").rsplit("/", 1)[-1])
    name = _NAME_UNSAFE.sub("_", name).strip(" .") or "upload"
    return name[:255]


async def _read_limited(upload: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise PayloadTooLarge(f"Files for this purpose must be at most {max_bytes // (1024 * 1024)} MB.")
        chunks.append(chunk)
    if total == 0:
        raise BadRequest("The file is empty.", code="EMPTY_FILE")
    return b"".join(chunks)


async def upload(
    session: AsyncSession, services: Services, caller: AuthContext, purpose: FilePurpose, file: UploadFile
) -> StoredFile:
    rule = RULES[purpose]
    if rule.roles is not None and caller.role not in rule.roles:
        raise Forbidden("Your account type cannot upload files for this purpose.", code="ROLE_FORBIDDEN")
    await services.rate_limiter.hit(
        bucket="uploads",
        key=rate_limit_key(str(caller.user_id)),
        limit=services.settings.upload_rate_limit_per_hour,
        window=timedelta(hours=1),
        now=services.clock.now(),
    )
    raw = await _read_limited(file, rule.max_bytes)
    content = inspection.inspect(raw, rule.allowed_types)
    if len(content.data) > rule.max_bytes:
        raise PayloadTooLarge("The processed file is too large.")
    key = f"{purpose.value.lower()}/{uuid.uuid4().hex}"
    stored = StoredFile(
        id=uuid.uuid4(),
        owner_user_id=caller.user_id,
        purpose=purpose.value,
        visibility=rule.visibility.value,
        storage_key=key,
        content_type=content.content_type,
        size_bytes=len(content.data),
        sha256=hashlib.sha256(content.data).hexdigest(),
        original_name=_safe_name(file.filename),
        width=content.width,
        height=content.height,
    )
    await services.storage.put(key, content.data, content.content_type)
    try:
        repository.add(session, stored)
        await audit.record(
            session,
            action="file.uploaded",
            entity_type="file",
            entity_id=stored.id,
            actor_user_id=caller.user_id,
            data={"purpose": purpose.value, "size": stored.size_bytes, "content_type": stored.content_type},
        )
        await session.commit()
    except Exception:
        await services.storage.delete(key)  # never leave an orphaned object behind
        raise
    await session.refresh(stored)
    return stored


def _signing_key(services: Services) -> bytes:
    secret = services.settings.jwt_secret.get_secret_value().encode()
    return hmac.new(secret, b"unifix-file-url-v1", hashlib.sha256).digest()


def _signature(services: Services, file_id: uuid.UUID, expires: int) -> str:
    digest = hmac.new(_signing_key(services), f"{file_id}.{expires}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def file_ref(services: Services, file: StoredFile) -> FileRef:
    url = f"{API_PREFIX}/files/{file.id}"
    signed_url = None
    if file.visibility == FileVisibility.PRIVATE.value:
        expires = int(services.clock.now().timestamp()) + services.settings.signed_url_ttl_seconds
        signed_url = f"{url}?exp={expires}&sig={_signature(services, file.id, expires)}"
    return FileRef(
        id=file.id,
        url=url,
        signed_url=signed_url,
        name=file.original_name,
        content_type=file.content_type,
        size=file.size_bytes,
        width=file.width,
        height=file.height,
        purpose=FilePurpose(file.purpose),
    )


def public_url(file: StoredFile | None) -> str | None:
    return f"{API_PREFIX}/files/{file.id}" if file is not None and file.deleted_at is None else None


def _signature_valid(
    services: Services, file_id: uuid.UUID, expires: int | None, signature: str | None
) -> bool:
    if expires is None or signature is None:
        return False
    if expires < int(services.clock.now().timestamp()):
        return False
    return hmac.compare_digest(_signature(services, file_id, expires), signature)


async def open_for_download(
    session: AsyncSession,
    services: Services,
    caller: AuthContext | None,
    file_id: uuid.UUID,
    *,
    expires: int | None,
    signature: str | None,
) -> tuple[StoredFile, bytes]:
    stored = await repository.get(session, file_id)
    if stored is None or stored.deleted_at is not None:
        raise NotFound("File not found.")
    allowed = _signature_valid(services, file_id, expires, signature) or await policy.can_read(
        session, caller, stored
    )
    if not allowed:
        raise NotFound("File not found.")  # indistinguishable from a missing file
    return stored, await services.storage.get(stored.storage_key)


async def require_owned(
    session: AsyncSession, caller: AuthContext, file_ids: Sequence[uuid.UUID], purpose: FilePurpose
) -> list[StoredFile]:
    """Files the caller uploaded for ``purpose``; anything else is rejected without revealing why."""
    unique = list(dict.fromkeys(file_ids))
    found = {file.id: file for file in await repository.get_many(session, unique)}
    for file_id in unique:
        file = found.get(file_id)
        if (
            file is None
            or file.owner_user_id != caller.user_id
            or file.purpose != purpose.value
            or file.deleted_at
        ):
            raise BadRequest(
                f"File {file_id} is not one of your {purpose.value} uploads.", code="INVALID_FILE"
            )
    return [found[file_id] for file_id in unique]
