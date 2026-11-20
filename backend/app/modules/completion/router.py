from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.deps import CallerDep, ServicesDep, SessionDep, StellarDep
from app.core.errors import error_responses
from app.modules.bookings import idempotency
from app.modules.completion import service
from app.modules.completion.schemas import (
    CompletionOut,
    PrepareCompletionIn,
    PreparedCompletionOut,
    SubmitCompletionIn,
)
from app.modules.payments.schemas import EscrowOut

router = APIRouter(prefix="/bookings", tags=["completion"])


@router.post(
    "/{booking_id}/completion",
    response_model=PreparedCompletionOut,
    responses=error_responses(400, 401, 403, 404, 409, 422, 502, 503),
    summary="Record completion evidence and prepare submit_completion for the professional to sign 💰",
)
async def prepare_completion(
    booking_id: uuid.UUID, data: PrepareCompletionIn, request: Request, caller: CallerDep,
    session: SessionDep, services: ServicesDep, stellar: StellarDep,
) -> JSONResponse:  # fmt: skip
    async def handler() -> tuple[int, PreparedCompletionOut]:
        return 200, await service.prepare(session, services, stellar, caller, booking_id, data)

    return await idempotency.run(request, services, caller, handler)


@router.post(
    "/{booking_id}/completion/submit",
    response_model=EscrowOut,
    responses=error_responses(400, 401, 403, 404, 409, 422, 502, 503),
    summary="Submit the professional-signed submit_completion transaction 💰",
)
async def submit_completion(
    booking_id: uuid.UUID, data: SubmitCompletionIn, request: Request, caller: CallerDep,
    session: SessionDep, services: ServicesDep, stellar: StellarDep,
) -> JSONResponse:  # fmt: skip
    async def handler() -> tuple[int, EscrowOut]:
        return 200, await service.submit(session, services, stellar, caller, booking_id, data.signed_xdr)

    return await idempotency.run(request, services, caller, handler)


@router.get(
    "/{booking_id}/completion",
    responses=error_responses(401, 404),
    summary="The latest completion evidence for a booking (null if none)",
)
async def get_completion(
    booking_id: uuid.UUID, caller: CallerDep, session: SessionDep, services: ServicesDep
) -> CompletionOut | None:
    return await service.latest(session, services, caller, booking_id)
