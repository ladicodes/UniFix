from __future__ import annotations

import uuid

from fastapi import APIRouter, Response

from app.api.deps import CallerDep, ServicesDep, SessionDep, StellarDep
from app.api.presenters import user_out
from app.core.errors import error_responses
from app.modules.users.schemas import UserOut
from app.modules.wallets import service
from app.modules.wallets.schemas import ChallengeIn, ChallengeOut, VerifyWalletIn, WalletOut

router = APIRouter(prefix="/wallets", tags=["wallets"])


@router.post(
    "/challenge",
    status_code=201,
    responses=error_responses(400, 401, 422, 429),
    summary="Issue a single-use SEP-53 message to sign with the wallet (5-minute expiry)",
)
async def create_challenge(
    data: ChallengeIn, caller: CallerDep, session: SessionDep, services: ServicesDep, stellar: StellarDep
) -> ChallengeOut:
    return await service.create_challenge(session, services, stellar, caller, data)


@router.post(
    "",
    responses=error_responses(400, 401, 409, 422, 503),
    summary="Verify a signed challenge and link the wallet; returns the updated user",
)
async def verify_wallet(
    data: VerifyWalletIn, caller: CallerDep, session: SessionDep, services: ServicesDep, stellar: StellarDep
) -> UserOut:
    await service.verify(session, services, stellar, caller, data)
    return await user_out(session, caller.user)


@router.get("", responses=error_responses(401), summary="The caller's verified wallets")
async def list_wallets(caller: CallerDep, session: SessionDep, stellar: StellarDep) -> list[WalletOut]:
    return await service.list_wallets(session, stellar, caller)


@router.delete(
    "/{wallet_id}",
    status_code=204,
    response_class=Response,
    responses=error_responses(401, 404, 409),
    summary="Unlink a wallet (refused while it is party to an active escrow)",
)
async def remove_wallet(
    wallet_id: uuid.UUID, caller: CallerDep, session: SessionDep, services: ServicesDep, stellar: StellarDep
) -> Response:
    await service.remove(session, services, stellar, caller, wallet_id)
    return Response(status_code=204)
