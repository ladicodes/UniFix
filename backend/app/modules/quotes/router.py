from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response, status

from app.api.deps import CallerDep, HubDep, ServicesDep, SessionDep
from app.core.errors import error_responses
from app.modules.bookings import idempotency
from app.modules.bookings import service as bookings
from app.modules.bookings.schemas import AcceptQuoteIn, BookingBundle
from app.modules.quotes import service
from app.modules.quotes.schemas import QuoteIn, QuoteOut, RejectIn

router = APIRouter(prefix="/quotes", tags=["quotes"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 403, 404, 409, 422),
    summary="Send a quote in a conversation (professionals); supersedes your pending quote there",
)
async def create_quote(
    data: QuoteIn, caller: CallerDep, session: SessionDep, services: ServicesDep, hub: HubDep
) -> QuoteOut:
    return await service.create(session, services, hub, caller, data)


@router.post(
    "/{quote_id}/accept",
    status_code=status.HTTP_201_CREATED,
    response_model=BookingBundle,
    responses=error_responses(400, 401, 403, 404, 409, 422),
    summary="Accept a quote: writes the immutable agreement and creates the booking (PENDING_PAYMENT)",
    description="Honours `Idempotency-Key`: a retry with the same key replays the original response.",
)
async def accept_quote(
    quote_id: uuid.UUID,
    data: AcceptQuoteIn,
    request: Request,
    caller: CallerDep,
    session: SessionDep,
    services: ServicesDep,
    hub: HubDep,
) -> Response:
    async def handler() -> tuple[int, BookingBundle]:
        return status.HTTP_201_CREATED, await bookings.accept_quote(
            session, services, hub, caller, quote_id, data
        )

    return await idempotency.run(request, services, caller, handler)


@router.post(
    "/{quote_id}/reject",
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Reject a pending quote (customer)",
)
async def reject_quote(
    quote_id: uuid.UUID,
    data: RejectIn,
    caller: CallerDep,
    session: SessionDep,
    services: ServicesDep,
    hub: HubDep,
) -> QuoteOut:
    return await service.reject(session, services, hub, caller, quote_id, data.reason)


@router.post(
    "/{quote_id}/withdraw",
    responses=error_responses(401, 403, 404, 409),
    summary="Withdraw your pending quote (professional)",
)
async def withdraw_quote(
    quote_id: uuid.UUID, caller: CallerDep, session: SessionDep, services: ServicesDep, hub: HubDep
) -> QuoteOut:
    return await service.withdraw(session, services, hub, caller, quote_id)
