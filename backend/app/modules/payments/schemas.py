"""API shapes for escrow and payments (API_CONTRACT §9). Token amounts are decimal strings."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.core.schemas import APIModel, ResponseModel
from app.modules.payments.models import (
    CancellationStatus,
    EscrowState,
    ReceiptKind,
    Reconciliation,
    TxKind,
)

SignedXdr = Field(min_length=1, max_length=20_000, description="The envelope signed in Freighter, unchanged")


class AssetOut(ResponseModel):
    code: str
    issuer: str
    sac_contract_id: str
    decimals: int


class FiatOut(ResponseModel):
    amount_minor: int
    currency: str


class FxOut(ResponseModel):
    rate: str
    base: str
    quote: str
    source: str
    is_demo_rate: bool
    locked_at: datetime


class EscrowTransactionOut(ResponseModel):
    kind: TxKind
    hash: str
    ledger: int | None
    at: datetime
    status: str = Field(
        description="PENDING | CONFIRMED | FAILED | EXPIRED (prepared and submitted show as PENDING)"
    )
    explorer_url: str


class EscrowOut(ResponseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    contract_id: str
    escrow_id_hex: str
    state: EscrowState
    asset: AssetOut
    asset_amount: str
    fiat: FiatOut
    fx: FxOut
    fee_stroops: str | None
    customer_wallet: str
    professional_wallet: str
    refund_after: int
    review_deadline: int | None
    disputed_at: int | None
    reconciliation: Reconciliation
    failure_reason: str | None
    settled_by: str | None
    professional_payout: str | None
    customer_refund: str | None
    terms_hash: str
    transactions: list[EscrowTransactionOut]
    created_at: datetime


class PreparedOut(ResponseModel):
    escrow: EscrowOut
    unsigned_xdr: str
    tx_hash: str
    valid_until: datetime


class PrepareFundingIn(APIModel):
    customer_wallet: str | None = Field(
        default=None,
        min_length=56,
        max_length=56,
        description="One of your verified wallets; default primary",
    )


class SubmitIn(APIModel):
    signed_xdr: str = SignedXdr


class PrepareOrSubmitIn(APIModel):
    """Empty body prepares; ``{signed_xdr}`` submits what was prepared."""

    signed_xdr: str | None = Field(default=None, min_length=1, max_length=20_000)


class ExtendIn(APIModel):
    new_refund_after: int | None = Field(default=None, gt=0, description="Unix seconds; prepare only")
    signed_xdr: str | None = Field(default=None, min_length=1, max_length=20_000)


class ReceiptOut(ResponseModel):
    id: uuid.UUID
    number: str
    kind: ReceiptKind
    booking_id: uuid.UUID
    asset: AssetOut
    asset_amount: str
    fiat: FiatOut
    fx: dict[str, object] = Field(description="{rate, source, is_demo_rate}")
    tx_hash: str
    ledger: int
    issued_at: datetime
    payload_hash: str
    payload_json: str = Field(description="Exact canonical bytes that payload_hash covers")


class CancellationRequestIn(APIModel):
    reason: str = Field(min_length=3, max_length=1000)


class DeclineCancellationIn(APIModel):
    reason: str = Field(min_length=3, max_length=1000)


class CancellationRequestOut(ResponseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    requested_by: uuid.UUID
    reason: str
    status: CancellationStatus
    decline_reason: str | None
    created_at: datetime
    expires_at: datetime
    responded_at: datetime | None
