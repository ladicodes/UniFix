"""The ``unifix.escrow-terms.v1`` document (STELLAR_ESCROW_DESIGN §6) and the refund deadline."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.payments.fx import LockedRate

SCHEMA = "unifix.escrow-terms.v1"
DISPUTE_POLICY = "unifix.dispute-policy.v1"
LAGOS = ZoneInfo("Africa/Lagos")
PRODUCTION_UNIT = 86_400
MAX_REFUND_DELAY = 180 * PRODUCTION_UNIT
# The funding transaction lands up to its validity window after preparation; keep refund_after
# comfortably inside the contract's [funded_at + 1 unit, funded_at + 180 units] bounds.
FUNDING_MARGIN = 3600


def refund_after(
    completion_date: date, *, now: datetime, service_grace: int, unit: int = PRODUCTION_UNIT
) -> int:
    """Later of (completion date 23:59 Lagos + grace) and (now + 24 h), plus a funding margin.

    With the test-only short-windows build (``unit`` = 60 s) the deadline is one hour from now,
    so timeout paths can run in real time on testnet. Production always uses the agreed date.
    """
    if unit != PRODUCTION_UNIT:
        return int(now.timestamp()) + 60 * unit
    end_of_day = datetime.combine(completion_date, time(23, 59), tzinfo=LAGOS)
    by_date = int((end_of_day + timedelta(seconds=service_grace)).timestamp())
    earliest = int(now.timestamp()) + PRODUCTION_UNIT + FUNDING_MARGIN
    return max(by_date, earliest)


def latest_allowed_refund_after(now: datetime, unit: int = PRODUCTION_UNIT) -> int:
    margin = FUNDING_MARGIN if unit == PRODUCTION_UNIT else 0
    return int(now.timestamp()) + 180 * unit - margin


def build(
    *,
    agreement_hash: str,
    booking_id: str,
    escrow_key_hex: str,
    passphrase: str,
    contract_id: str,
    asset_code: str,
    asset_issuer: str,
    sac_contract_id: str,
    decimals: int,
    asset_units: int,
    fiat_amount_minor: int,
    fiat_currency: str,
    rate: LockedRate,
    customer_wallet: str,
    professional_wallet: str,
    refund_after_ts: int,
    review_window: int,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "agreement_hash": agreement_hash,
        "booking_id": booking_id,
        "escrow_id": escrow_key_hex,
        "network_passphrase": passphrase,
        "escrow_contract_id": contract_id,
        "asset": {
            "code": asset_code,
            "issuer": asset_issuer,
            "sac_contract_id": sac_contract_id,
            "decimals": decimals,
        },
        "asset_amount": str(asset_units),
        "fiat": {"amount_minor": fiat_amount_minor, "currency": fiat_currency},
        "fx": {
            "rate": rate.rate_text,
            "base": rate.base,
            "quote": rate.quote,
            "source": rate.source,
            "is_demo_rate": rate.is_demo_rate,
            "locked_at": rate.locked_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "customer_wallet": customer_wallet,
        "professional_wallet": professional_wallet,
        "refund_after": refund_after_ts,
        "review_window": review_window,
        "dispute_policy": DISPUTE_POLICY,
    }
