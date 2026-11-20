"""Fiat ↔ token conversion. The only place it happens (STELLAR_ESCROW_DESIGN §8).

``asset_units = ceil(amount_minor * 10^decimals / (rate * 10^currency_exponent))`` with the rate
as an exact decimal of at most 8 places. Pure integer arithmetic; no float path. Rounding is up,
so the professional is never underpaid by rounding.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.core.config import Settings, StellarNetwork

CURRENCY_EXPONENT = {"NGN": 2, "GHS": 2}
RATE_PLACES = 8
DEMO_SOURCE = "DEMO_FIXED_RATE"


class RateUnavailable(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LockedRate:
    rate: Decimal  # fiat major units per 1 whole token unit
    base: str  # token code
    quote: str  # fiat currency
    source: str
    is_demo_rate: bool
    locked_at: datetime

    @property
    def rate_text(self) -> str:
        return f"{self.rate:.{RATE_PLACES}f}"


def parse_rate(raw: str) -> Decimal:
    try:
        rate = Decimal(raw)
    except InvalidOperation as exc:
        raise RateUnavailable("The FX rate is not a decimal number.") from exc
    exponent = rate.as_tuple().exponent
    if not rate.is_finite() or rate <= 0 or (isinstance(exponent, int) and exponent < -RATE_PLACES):
        raise RateUnavailable(f"The FX rate must be positive with at most {RATE_PLACES} decimal places.")
    return rate


def to_asset_units(amount_minor: int, currency: str, rate: Decimal, decimals: int) -> int:
    if amount_minor <= 0:
        raise ValueError("amount_minor must be positive")
    exponent = CURRENCY_EXPONENT[currency]
    scaled_rate = rate.scaleb(RATE_PLACES)
    if scaled_rate != scaled_rate.to_integral_value():
        raise RateUnavailable(f"The FX rate has more than {RATE_PLACES} decimal places.")
    numerator = amount_minor * 10**decimals * 10**RATE_PLACES
    denominator = int(scaled_rate) * 10**exponent
    units: int = -(-numerator // denominator)  # ceiling division on integers
    return units


def lock_rate(settings: Settings, currency: str, now: datetime) -> LockedRate:
    """D14: on testnet the rate is the configured demo rate, labelled as such everywhere."""
    if settings.stellar_network is not StellarNetwork.TESTNET:
        raise RateUnavailable("No production FX source is configured; demo rates are testnet-only.")
    raw = {"NGN": settings.fx_demo_rate_ngn, "GHS": settings.fx_demo_rate_ghs}.get(currency)
    if raw is None:
        raise RateUnavailable(f"No demo FX rate is configured for {currency}.")
    return LockedRate(
        rate=parse_rate(raw),
        base=settings.escrow_token_code,
        quote=currency,
        source=DEMO_SOURCE,
        is_demo_rate=True,
        locked_at=now.replace(microsecond=0),
    )
