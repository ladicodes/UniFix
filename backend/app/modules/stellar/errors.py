"""Chain-boundary errors. Every one of them leaves database state unchanged."""

from __future__ import annotations

from app.core.errors import BadGateway, BadRequest, Conflict, ServiceUnavailable


class ChainUnavailable(ServiceUnavailable):
    code = "CHAIN_UNAVAILABLE"
    default_detail = "The Stellar network is unreachable right now. Nothing was changed; please retry."


class ChainRejected(BadGateway):
    code = "CHAIN_REJECTED"
    default_detail = "The Stellar network rejected the transaction. Nothing was changed."


class EscrowNotConfigured(ServiceUnavailable):
    code = "ESCROW_NOT_CONFIGURED"
    default_detail = "Escrow payments are not configured on this server."


class TxMismatch(BadRequest):
    code = "TX_MISMATCH"
    default_detail = "The signed transaction is not the one that was prepared."


class TxExpired(Conflict):
    code = "TX_EXPIRED"
    default_detail = "The prepared transaction has expired. Prepare it again."
