"""Process-wide Stellar configuration and gateway, built once by the app factory."""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass

from stellar_sdk import Asset, Keypair

from app.core.config import Settings
from app.modules.stellar.errors import EscrowNotConfigured
from app.modules.stellar.gateway import ChainGateway, RpcGateway

logger = logging.getLogger(__name__)


@dataclass
class StellarContext:
    settings: Settings
    gateway: ChainGateway | None  # None when escrow is not configured

    @property
    def passphrase(self) -> str:
        return self.settings.network_passphrase

    @property
    def network(self) -> str:
        return self.settings.stellar_network.value

    @property
    def asset(self) -> Asset:
        return Asset(self.settings.escrow_token_code, self.settings.escrow_token_issuer)

    def require(self) -> ChainGateway:
        if self.gateway is None:
            raise EscrowNotConfigured()
        return self.gateway

    def operator(self) -> Keypair:
        """The operator key. Read from settings on use; never logged, returned or persisted."""
        secret = self.settings.stellar_operator_secret
        if secret is None:
            raise EscrowNotConfigured()
        return Keypair.from_secret(secret.get_secret_value())

    def escrow_key(self, booking_id: str) -> bytes:
        """STELLAR_ESCROW_DESIGN §6: HMAC-SHA256(secret, "unifix-escrow-v1|" + passphrase + "|" + id)."""
        secret = self.settings.escrow_id_secret
        if secret is None:
            raise EscrowNotConfigured()
        message = f"unifix-escrow-v1|{self.passphrase}|{booking_id}".encode()
        return hmac.new(secret.get_secret_value().encode(), message, hashlib.sha256).digest()

    def explorer_tx_url(self, tx_hash: str) -> str:
        return f"{self.settings.stellar_explorer_url.rstrip('/')}/tx/{tx_hash}"


def build_stellar(settings: Settings) -> StellarContext:
    gateway: ChainGateway | None = None
    if settings.escrow_contract_id is not None:
        gateway = RpcGateway(
            rpc_url=settings.stellar_rpc_url,
            horizon_url=settings.stellar_horizon_url,
            passphrase=settings.network_passphrase,
            contract_id=settings.escrow_contract_id,
            timeout=settings.stellar_rpc_timeout_seconds,
        )
    return StellarContext(settings=settings, gateway=gateway)


class StartupCheckFailed(RuntimeError):
    pass


async def startup_check(context: StellarContext) -> None:
    """Refuse to start unless the configured asset and contracts exist on the configured network
    and the on-chain operator is our operator (Issue 5 asset configuration check)."""
    settings = context.settings
    if context.gateway is None or not settings.stellar_check_on_startup:
        return
    gateway = context.gateway
    if not await gateway.contract_exists(settings.escrow_token_contract_id):
        raise StartupCheckFailed("ESCROW_TOKEN_CONTRACT_ID has no contract instance on this network")
    assert settings.escrow_contract_id is not None
    if not await gateway.contract_exists(settings.escrow_contract_id):
        raise StartupCheckFailed("ESCROW_CONTRACT_ID has no contract instance on this network")
    assert settings.stellar_operator_address is not None
    config = await gateway.get_config(settings.stellar_operator_address)
    if config.token != settings.escrow_token_contract_id:
        raise StartupCheckFailed("The escrow contract holds a different token than ESCROW_TOKEN_CONTRACT_ID")
    if config.operator != settings.stellar_operator_address:
        raise StartupCheckFailed("The escrow contract's operator is not STELLAR_OPERATOR_ADDRESS")
    if config.review_window != settings.escrow_review_window_seconds:
        raise StartupCheckFailed("ESCROW_REVIEW_WINDOW_SECONDS differs from the contract's review window")
    logger.info("stellar.startup_check_passed", extra={"contract_id": settings.escrow_contract_id})
