"""Wallet ownership via SEP-53 signed challenges (STELLAR_ESCROW_DESIGN §7)."""

from __future__ import annotations

import logging
import secrets
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.container import Services
from app.core.db import violated_constraint
from app.core.errors import BadRequest, Conflict, NotFound
from app.core.ratelimit import rate_limit_key
from app.modules.audit import service as audit
from app.modules.auth.context import AuthContext
from app.modules.stellar import signing
from app.modules.stellar.context import StellarContext
from app.modules.stellar.errors import ChainUnavailable
from app.modules.wallets import repository
from app.modules.wallets.models import Wallet, WalletChallenge
from app.modules.wallets.schemas import ChallengeIn, ChallengeOut, VerifyWalletIn, WalletOut

logger = logging.getLogger(__name__)

ActiveEscrowCheck = Callable[[AsyncSession, str], Awaitable[bool]]
_active_escrow_check: ActiveEscrowCheck | None = None


def register_active_escrow_check(check: ActiveEscrowCheck) -> None:
    """Payments registers this so a wallet that is party to a live escrow cannot be removed."""
    global _active_escrow_check
    _active_escrow_check = check


def _message(address: str, user_id: uuid.UUID, passphrase: str, nonce: str, issued: datetime) -> str:
    return (
        "UniFix wallet verification\n"
        f"Address: {address}\n"
        f"User: {user_id}\n"
        f"Network: {passphrase}\n"
        f"Nonce: {nonce}\n"
        f"Issued: {issued.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )


def _require_address(address: str) -> None:
    if not signing.is_account_address(address):
        raise BadRequest("Not a valid Stellar account address (G…).", code="INVALID_WALLET_ADDRESS")


async def create_challenge(
    session: AsyncSession, services: Services, stellar: StellarContext, caller: AuthContext, data: ChallengeIn
) -> ChallengeOut:
    _require_address(data.address)
    now = services.clock.now()
    await services.rate_limiter.hit(
        bucket="wallet_challenge",
        key=rate_limit_key(str(caller.user_id)),
        limit=services.settings.wallet_challenge_rate_limit_per_hour,
        window=timedelta(hours=1),
        now=now,
    )
    nonce = secrets.token_hex(16)
    issued = now.replace(microsecond=0)
    challenge = WalletChallenge(
        user_id=caller.user_id,
        network=stellar.network,
        address=data.address,
        nonce=nonce,
        message=_message(data.address, caller.user_id, stellar.passphrase, nonce, issued),
        expires_at=now + timedelta(seconds=services.settings.wallet_challenge_ttl_seconds),
    )
    repository.add(session, challenge)
    await session.commit()
    return ChallengeOut(message=challenge.message, nonce=nonce, expires_at=challenge.expires_at)


async def verify(
    session: AsyncSession,
    services: Services,
    stellar: StellarContext,
    caller: AuthContext,
    data: VerifyWalletIn,
) -> Wallet:
    _require_address(data.address)
    gateway = stellar.require()
    now = services.clock.now()
    challenge = await repository.consume_challenge(
        session,
        user_id=caller.user_id,
        address=data.address,
        network=stellar.network,
        message=data.message,
        now=now,
    )
    await session.commit()  # consumed even if the signature turns out to be wrong
    if challenge is None:
        raise BadRequest(
            "This challenge is invalid, expired or already used. Request a new one.", code="CHALLENGE_INVALID"
        )
    if not signing.verify_message(data.address, data.message, data.signature):
        raise BadRequest("The signature does not match this address and message.", code="INVALID_SIGNATURE")

    existing = await repository.active_by_address(session, stellar.network, data.address)
    if existing is not None:
        if existing.user_id != caller.user_id:
            raise Conflict("This wallet is linked to another account.", code="WALLET_IN_USE")
        return existing
    account = await gateway.account_info(data.address, stellar.asset)
    if not account.exists:
        raise BadRequest(
            "This account does not exist on the Stellar network yet. Fund it with XLM first.",
            code="WALLET_ACCOUNT_NOT_FOUND",
        )
    has_primary = await repository.primary(session, caller.user_id, stellar.network) is not None
    wallet = Wallet(
        user_id=caller.user_id,
        network=stellar.network,
        address=data.address,
        verified_at=now,
        is_primary=not has_primary,
    )
    repository.add(session, wallet)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if violated_constraint(exc) == "uq_wallets_active_address":
            raise Conflict("This wallet is linked to another account.", code="WALLET_IN_USE") from exc
        raise
    await audit.record(
        session,
        action="wallet.verified",
        entity_type="wallet",
        entity_id=wallet.id,
        actor_user_id=caller.user_id,
        data={"address": data.address, "network": stellar.network},
    )
    await session.commit()
    return wallet


async def list_wallets(
    session: AsyncSession, stellar: StellarContext, caller: AuthContext
) -> list[WalletOut]:
    wallets = await repository.active_for_user(session, caller.user_id, stellar.network)
    result = []
    for wallet in wallets:
        exists: bool | None = None
        trustline: bool | None = None
        if stellar.gateway is not None:
            try:
                info = await stellar.gateway.account_info(wallet.address, stellar.asset)
                exists, trustline = info.exists, info.has_trustline
            except ChainUnavailable:
                logger.warning("wallets.horizon_unavailable")
        result.append(
            WalletOut(
                id=wallet.id,
                address=wallet.address,
                network=wallet.network,
                verified_at=wallet.verified_at,
                is_primary=wallet.is_primary,
                account_exists=exists,
                has_escrow_trustline=trustline,
            )
        )
    return result


async def remove(
    session: AsyncSession,
    services: Services,
    stellar: StellarContext,
    caller: AuthContext,
    wallet_id: uuid.UUID,
) -> None:
    wallet = await repository.get(session, wallet_id, for_update=True)
    if wallet is None or wallet.user_id != caller.user_id or wallet.revoked_at is not None:
        raise NotFound("Wallet not found.")
    if _active_escrow_check is not None and await _active_escrow_check(session, wallet.address):
        raise Conflict("This wallet is party to an active escrow.", code="WALLET_IN_ESCROW")
    was_primary = wallet.is_primary
    wallet.revoked_at = services.clock.now()
    wallet.is_primary = False
    await session.flush()
    if was_primary:
        remaining = await repository.active_for_user(session, caller.user_id, wallet.network)
        if remaining:
            remaining[0].is_primary = True
    await audit.record(
        session,
        action="wallet.removed",
        entity_type="wallet",
        entity_id=wallet.id,
        actor_user_id=caller.user_id,
        data={"address": wallet.address},
    )
    await session.commit()


async def primary_address(
    session: AsyncSession, user_id: uuid.UUID, network: str | None = None
) -> str | None:
    """The user's primary verified wallet (a deployment uses exactly one network)."""
    wallet = await repository.primary(session, user_id, network)
    return wallet.address if wallet else None


async def owns(session: AsyncSession, user_id: uuid.UUID, address: str, network: str) -> bool:
    wallet = await repository.active_by_address(session, network, address)
    return wallet is not None and wallet.user_id == user_id
