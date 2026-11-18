"""Escrow routes (API_CONTRACT §9). Every 💰 route honours ``Idempotency-Key``."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.deps import CallerDep, ServicesDep, SessionDep, StellarDep
from app.core.errors import error_responses
from app.modules.bookings import idempotency
from app.modules.payments import service
from app.modules.payments.schemas import (
    CancellationRequestIn,
    CancellationRequestOut,
    DeclineCancellationIn,
    EscrowOut,
    ExtendIn,
    PreparedOut,
    PrepareFundingIn,
    PrepareOrSubmitIn,
    ReceiptOut,
    SubmitIn,
)

router = APIRouter(tags=["escrow"])
CHAIN_ERRORS = error_responses(400, 401, 403, 404, 409, 422, 502, 503)


@router.post(
    "/bookings/{booking_id}/escrow",
    response_model=PreparedOut,
    responses=CHAIN_ERRORS,
    summary="Prepare the funding transaction for the customer's wallet to sign 💰",
)
async def prepare_funding(
    booking_id: uuid.UUID, data: PrepareFundingIn, request: Request, caller: CallerDep,
    session: SessionDep, services: ServicesDep, stellar: StellarDep,
) -> JSONResponse:  # fmt: skip
    async def handler() -> tuple[int, PreparedOut]:
        return 200, await service.prepare_funding(
            session, services, stellar, caller, booking_id, data.customer_wallet
        )

    return await idempotency.run(request, services, caller, handler)


@router.get(
    "/escrows/{escrow_id}", responses=error_responses(401, 404), summary="An escrow and its transactions"
)
async def get_escrow(
    escrow_id: uuid.UUID, caller: CallerDep, session: SessionDep, services: ServicesDep, stellar: StellarDep
) -> EscrowOut:
    return await service.get_escrow(session, services, stellar, caller, escrow_id)


@router.post(
    "/escrows/{escrow_id}/funding",
    response_model=EscrowOut,
    responses=CHAIN_ERRORS,
    summary="Submit the signed funding transaction; the booking becomes FUNDED on confirmation 💰",
)
async def submit_funding(
    escrow_id: uuid.UUID, data: SubmitIn, request: Request, caller: CallerDep,
    session: SessionDep, services: ServicesDep, stellar: StellarDep,
) -> JSONResponse:  # fmt: skip
    async def handler() -> tuple[int, EscrowOut]:
        return 200, await service.submit_funding(
            session, services, stellar, caller, escrow_id, data.signed_xdr
        )

    return await idempotency.run(request, services, caller, handler)


@router.post(
    "/escrows/{escrow_id}/release",
    response_model=PreparedOut | EscrowOut,
    responses=CHAIN_ERRORS,
    summary="Customer: {} prepares the release, {signed_xdr} submits it 💰",
)
async def release(
    escrow_id: uuid.UUID, data: PrepareOrSubmitIn, request: Request, caller: CallerDep,
    session: SessionDep, services: ServicesDep, stellar: StellarDep,
) -> JSONResponse:  # fmt: skip
    async def handler() -> tuple[int, PreparedOut | EscrowOut]:
        return 200, await service.release(session, services, stellar, caller, escrow_id, data.signed_xdr)

    return await idempotency.run(request, services, caller, handler)


@router.post(
    "/escrows/{escrow_id}/refund",
    response_model=PreparedOut | EscrowOut,
    responses=CHAIN_ERRORS,
    summary="Professional: {} prepares a full refund, {signed_xdr} submits it 💰",
)
async def refund(
    escrow_id: uuid.UUID, data: PrepareOrSubmitIn, request: Request, caller: CallerDep,
    session: SessionDep, services: ServicesDep, stellar: StellarDep,
) -> JSONResponse:  # fmt: skip
    async def handler() -> tuple[int, PreparedOut | EscrowOut]:
        return 200, await service.refund(session, services, stellar, caller, escrow_id, data.signed_xdr)

    return await idempotency.run(request, services, caller, handler)


@router.post(
    "/escrows/{escrow_id}/extend",
    response_model=PreparedOut | EscrowOut,
    responses=CHAIN_ERRORS,
    summary="Customer: {new_refund_after} prepares a deadline extension, {signed_xdr} submits it 💰",
)
async def extend(
    escrow_id: uuid.UUID, data: ExtendIn, request: Request, caller: CallerDep,
    session: SessionDep, services: ServicesDep, stellar: StellarDep,
) -> JSONResponse:  # fmt: skip
    async def handler() -> tuple[int, PreparedOut | EscrowOut]:
        return 200, await service.extend(
            session, services, stellar, caller, escrow_id, data.new_refund_after, data.signed_xdr
        )

    return await idempotency.run(request, services, caller, handler)


@router.post(
    "/bookings/{booking_id}/cancellation-requests",
    status_code=201,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Customer asks to cancel a funded booking (the professional refunds or declines; 48 h)",
)
async def request_cancellation(
    booking_id: uuid.UUID,
    data: CancellationRequestIn,
    caller: CallerDep,
    session: SessionDep,
    services: ServicesDep,
) -> CancellationRequestOut:
    return await service.request_cancellation(session, services, caller, booking_id, data.reason)


@router.post(
    "/cancellation-requests/{request_id}/decline",
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Professional declines a cancellation request",
)
async def decline_cancellation(
    request_id: uuid.UUID,
    data: DeclineCancellationIn,
    caller: CallerDep,
    session: SessionDep,
    services: ServicesDep,
) -> CancellationRequestOut:
    return await service.decline_cancellation(session, services, caller, request_id, data.reason)


@router.get(
    "/bookings/{booking_id}/receipts",
    responses=error_responses(401, 404),
    summary="Funding, release, refund and resolution receipts (from confirmed chain data only)",
)
async def receipts(
    booking_id: uuid.UUID, caller: CallerDep, session: SessionDep, services: ServicesDep
) -> list[ReceiptOut]:
    return await service.receipts(session, services, caller, booking_id)
