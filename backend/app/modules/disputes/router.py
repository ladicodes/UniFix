from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.deps import AdminDep, CallerDep, ServicesDep, SessionDep, StellarDep
from app.core.errors import error_responses
from app.modules.bookings import idempotency
from app.modules.disputes import service
from app.modules.disputes.models import DisputeStatus
from app.modules.disputes.schemas import (
    DisputeBundle,
    DisputeOut,
    DisputePreparedOut,
    EvidenceIn,
    LockIn,
    OpenDisputeIn,
    ResolveIn,
)
from app.modules.payments.schemas import EscrowOut

router = APIRouter(tags=["disputes"])
CHAIN_ERRORS = error_responses(400, 401, 403, 404, 409, 422, 502, 503)


@router.post(
    "/escrows/{escrow_id}/disputes",
    response_model=DisputePreparedOut,
    responses=CHAIN_ERRORS,
    summary="Open a dispute (blocks release/refund at once) and prepare the on-chain lock to sign 💰",
)
async def open_dispute(
    escrow_id: uuid.UUID, data: OpenDisputeIn, request: Request, caller: CallerDep,
    session: SessionDep, services: ServicesDep, stellar: StellarDep,
) -> JSONResponse:  # fmt: skip
    async def handler() -> tuple[int, DisputePreparedOut]:
        return 201, await service.open_dispute(session, services, stellar, caller, escrow_id, data)

    return await idempotency.run(request, services, caller, handler)


@router.post(
    "/disputes/{dispute_id}/lock",
    response_model=DisputePreparedOut | EscrowOut,
    responses=CHAIN_ERRORS,
    summary="{signed_xdr} submits the signed open_dispute; {} prepares it again 💰",
)
async def lock_dispute(
    dispute_id: uuid.UUID, data: LockIn, request: Request, caller: CallerDep,
    session: SessionDep, services: ServicesDep, stellar: StellarDep,
) -> JSONResponse:  # fmt: skip
    async def handler() -> tuple[int, DisputePreparedOut | EscrowOut]:
        return 200, await service.lock(session, services, stellar, caller, dispute_id, data.signed_xdr)

    return await idempotency.run(request, services, caller, handler)


@router.get(
    "/disputes/{dispute_id}", responses=error_responses(401, 404), summary="A dispute (parties and admins)"
)
async def get_dispute(
    dispute_id: uuid.UUID, caller: CallerDep, session: SessionDep, services: ServicesDep
) -> DisputeOut:
    return await service.get(session, services, caller, dispute_id)


@router.post(
    "/disputes/{dispute_id}/evidence",
    status_code=201,
    responses=error_responses(400, 401, 404, 409, 422),
    summary="Add a note and optionally one DISPUTE_EVIDENCE file (parties and admins)",
)
async def add_evidence(
    dispute_id: uuid.UUID, data: EvidenceIn, caller: CallerDep, session: SessionDep, services: ServicesDep
) -> DisputeOut:
    return await service.add_evidence(session, services, caller, dispute_id, data)


@router.get(
    "/admin/disputes",
    tags=["admin"],
    responses=error_responses(401, 403, 422),
    summary="Dispute queue ordered by decision deadline (admin)",
)
async def admin_disputes(
    admin: AdminDep, session: SessionDep, services: ServicesDep, stellar: StellarDep,
    status: DisputeStatus | None = None,
) -> list[DisputeBundle]:  # fmt: skip
    return await service.admin_queue(session, services, stellar, status)


@router.post(
    "/disputes/{dispute_id}/resolve",
    tags=["admin"],
    response_model=DisputePreparedOut | DisputeOut,
    responses=CHAIN_ERRORS,
    summary="Arbiter: {outcome, split_bps_to_professional?, note} prepares resolve; {signed_xdr} submits 💰",
)
async def resolve_dispute(
    dispute_id: uuid.UUID, data: ResolveIn, request: Request, admin: AdminDep,
    session: SessionDep, services: ServicesDep, stellar: StellarDep,
) -> JSONResponse:  # fmt: skip
    async def handler() -> tuple[int, DisputePreparedOut | DisputeOut]:
        return 200, await service.resolve(session, services, stellar, admin, dispute_id, data)

    return await idempotency.run(request, services, admin, handler)
