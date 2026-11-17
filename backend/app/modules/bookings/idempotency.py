"""``Idempotency-Key`` handling for state-changing financial routes (API_CONTRACT §2).

* Same key + same request → the stored response is replayed (``Idempotent-Replayed: true``).
* Same key + different request → 409 IDEMPOTENCY_KEY_REUSED.
* Same key while the first request is still running → 409 IDEMPOTENCY_IN_PROGRESS.
* A request that fails releases its key, so the client can retry with it.

Keys are scoped per user and expire after 24 hours. The reservation row commits in its
own transaction before the work starts, so the unique index arbitrates concurrent retries.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Awaitable, Callable
from datetime import timedelta

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.container import Services
from app.core.db import violated_constraint
from app.core.errors import BadRequest, Conflict
from app.modules.auth.context import AuthContext
from app.modules.bookings.models import IdempotencyKey

HEADER = "Idempotency-Key"
TTL = timedelta(hours=24)
_KEY = re.compile(r"^[A-Za-z0-9_-]{8,128}$")

Handler = Callable[[], Awaitable[tuple[int, BaseModel]]]


def _request_hash(request: Request, body: bytes) -> str:
    return hashlib.sha256(b"\n".join([request.method.encode(), request.url.path.encode(), body])).hexdigest()


async def run(request: Request, services: Services, caller: AuthContext, handler: Handler) -> JSONResponse:
    key = request.headers.get(HEADER)
    if key is None:
        status_code, model = await handler()
        return JSONResponse(status_code=status_code, content=jsonable_encoder(model))
    if not _KEY.match(key):
        raise BadRequest(
            "Idempotency-Key must be 8-128 characters of [A-Za-z0-9_-].", code="INVALID_IDEMPOTENCY_KEY"
        )

    now = services.clock.now()
    request_hash = _request_hash(request, await request.body())
    async with services.session_factory() as session:
        await session.execute(
            delete(IdempotencyKey).where(
                IdempotencyKey.user_id == caller.user_id,
                IdempotencyKey.key == key,
                IdempotencyKey.expires_at <= now,
            )
        )
        session.add(
            IdempotencyKey(
                user_id=caller.user_id,
                key=key,
                method=request.method,
                path=request.url.path,
                request_hash=request_hash,
                status="IN_PROGRESS",
                expires_at=now + TTL,
            )
        )
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            if violated_constraint(exc) != "uq_idempotency_keys_user_key":
                raise
            existing = (
                await session.execute(
                    select(IdempotencyKey).where(
                        IdempotencyKey.user_id == caller.user_id, IdempotencyKey.key == key
                    )
                )
            ).scalar_one()
            if existing.request_hash != request_hash:
                raise Conflict(
                    "This Idempotency-Key was used for a different request.", code="IDEMPOTENCY_KEY_REUSED"
                ) from exc
            if existing.status != "COMPLETED":
                raise Conflict(
                    "A request with this Idempotency-Key is still in progress.",
                    code="IDEMPOTENCY_IN_PROGRESS",
                ) from exc
            return JSONResponse(
                status_code=existing.response_status or 200,
                content=existing.response_body,
                headers={"Idempotent-Replayed": "true"},
            )

    try:
        status_code, model = await handler()
    except BaseException:
        async with services.session_factory() as session:
            await session.execute(
                delete(IdempotencyKey).where(
                    IdempotencyKey.user_id == caller.user_id, IdempotencyKey.key == key
                )
            )
            await session.commit()
        raise
    body = jsonable_encoder(model)
    async with services.session_factory() as session:
        row = (
            await session.execute(
                select(IdempotencyKey).where(
                    IdempotencyKey.user_id == caller.user_id, IdempotencyKey.key == key
                )
            )
        ).scalar_one()
        row.status, row.response_status, row.response_body = "COMPLETED", status_code, body
        await session.commit()
    return JSONResponse(status_code=status_code, content=body)
