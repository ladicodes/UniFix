"""Bindings for the UniFix escrow contract (backend/contracts/escrow): call arguments, the
``Escrow`` struct decoder and the event decoder. Pure functions, no I/O."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from stellar_sdk import Address, scval
from stellar_sdk import xdr as stellar_xdr

EVENT_PREFIX = "unifix"


class Function(StrEnum):
    FUND = "fund"
    SUBMIT_COMPLETION = "submit_completion"
    RELEASE = "release"
    REFUND = "refund"
    EXTEND = "extend"
    OPEN_DISPUTE = "open_dispute"
    RESOLVE = "resolve"
    FINALIZE_EXPIRED = "finalize_expired"
    GET_ESCROW = "get_escrow"
    CONFIG = "config"


class OnchainStatus(StrEnum):
    FUNDED = "Funded"
    COMPLETION_SUBMITTED = "CompletionSubmitted"
    DISPUTED = "Disputed"
    RELEASED = "Released"
    REFUNDED = "Refunded"
    RESOLVED = "Resolved"


TERMINAL = frozenset({OnchainStatus.RELEASED, OnchainStatus.REFUNDED, OnchainStatus.RESOLVED})

# Contract error codes (contracts/escrow/src/lib.rs `Error`).
CONTRACT_ERRORS = {
    1: "AlreadyExists",
    2: "NotFound",
    3: "InvalidAmount",
    4: "SameParty",
    5: "InvalidState",
    6: "NotParty",
    7: "InvalidSplit",
    8: "InvalidDeadline",
    9: "DeadlinePassed",
    10: "NotExpired",
}


@dataclass(frozen=True, slots=True)
class OnchainEscrow:
    customer: str
    professional: str
    amount: int
    terms_hash: str
    status: OnchainStatus
    funded_at: int
    refund_after: int
    review_window: int
    review_deadline: int | None
    disputed_at: int | None
    evidence_hash: str | None
    disputed_by: str | None
    professional_payout: int
    customer_refund: int
    settled_by: str | None  # "CUSTOMER" | "PROFESSIONAL" | "ARBITER" | "TIMEOUT"


@dataclass(frozen=True, slots=True)
class OnchainConfig:
    admin: str
    arbiter: str
    operator: str
    token: str
    review_window: int


def _id(escrow_id: bytes) -> stellar_xdr.SCVal:
    if len(escrow_id) != 32:
        raise ValueError("escrow ids are 32 bytes")
    return scval.to_bytes(escrow_id)


def fund_args(
    escrow_id: bytes, customer: str, professional: str, amount: int, terms_hash: bytes, refund_after: int
) -> list[stellar_xdr.SCVal]:
    return [
        _id(escrow_id),
        scval.to_address(customer),
        scval.to_address(professional),
        scval.to_int128(amount),
        _id(terms_hash),
        scval.to_uint64(refund_after),
    ]


def submit_completion_args(escrow_id: bytes, evidence_hash: bytes) -> list[stellar_xdr.SCVal]:
    return [_id(escrow_id), _id(evidence_hash)]


def escrow_only_args(escrow_id: bytes) -> list[stellar_xdr.SCVal]:
    """release, refund, finalize_expired and get_escrow."""
    return [_id(escrow_id)]


def extend_args(escrow_id: bytes, new_refund_after: int) -> list[stellar_xdr.SCVal]:
    return [_id(escrow_id), scval.to_uint64(new_refund_after)]


def open_dispute_args(escrow_id: bytes, caller: str) -> list[stellar_xdr.SCVal]:
    return [_id(escrow_id), scval.to_address(caller)]


def resolve_args(escrow_id: bytes, professional_amount: int) -> list[stellar_xdr.SCVal]:
    return [_id(escrow_id), scval.to_int128(professional_amount)]


def native(value: stellar_xdr.SCVal) -> Any:
    """SCVal → JSON-safe Python: addresses as StrKeys, bytes as hex, unit enums as their name."""
    return _jsonable(scval.to_native(value))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Address):
        return value.address
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(_jsonable(k)): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        # A unit enum variant (`EscrowStatus::Funded`) is encoded as a one-symbol vector.
        if len(value) == 1 and isinstance(value[0], str):
            return value[0]
        return [_jsonable(v) for v in value]
    return value


_SETTLED_BY = {
    "Customer": "CUSTOMER",
    "Professional": "PROFESSIONAL",
    "Arbiter": "ARBITER",
    "Timeout": "TIMEOUT",
}


def settled_by_name(value: str) -> str | None:
    return _SETTLED_BY.get(value)  # "Unsettled" → None


def decode_escrow(value: stellar_xdr.SCVal) -> OnchainEscrow:
    data = native(value)
    return OnchainEscrow(
        customer=data["customer"],
        professional=data["professional"],
        amount=int(data["amount"]),
        terms_hash=data["terms_hash"],
        status=OnchainStatus(data["status"]),
        funded_at=int(data["funded_at"]),
        refund_after=int(data["refund_after"]),
        review_window=int(data["review_window"]),
        review_deadline=data["review_deadline"],
        disputed_at=data["disputed_at"],
        evidence_hash=data["evidence_hash"],
        disputed_by=data["disputed_by"],
        professional_payout=int(data["professional_payout"]),
        customer_refund=int(data["customer_refund"]),
        settled_by=settled_by_name(data["settled_by"]),
    )


def decode_config(value: stellar_xdr.SCVal) -> OnchainConfig:
    data = native(value)
    return OnchainConfig(
        admin=data["admin"],
        arbiter=data["arbiter"],
        operator=data["operator"],
        token=data["token"],
        review_window=int(data["review_window"]),
    )


@dataclass(frozen=True, slots=True)
class DecodedEvent:
    name: str  # funded, completion_submitted, extended, disputed, released, refunded, resolved, expired, …
    escrow_key: bytes | None
    payload: dict[str, Any]


def decode_event(topics: list[stellar_xdr.SCVal], data: stellar_xdr.SCVal) -> DecodedEvent | None:
    """Our events have topics ``("unifix", <name>[, escrow_id])``; anything else returns None."""
    if len(topics) < 2:
        return None
    try:
        prefix, name = scval.from_symbol(topics[0]), scval.from_symbol(topics[1])
    except (ValueError, TypeError):
        return None
    if prefix != EVENT_PREFIX:
        return None
    escrow_key = scval.from_bytes(topics[2]) if len(topics) > 2 else None
    payload = native(data)
    if not isinstance(payload, dict):
        payload = {"value": payload}
    if "settled_by" in payload:
        payload["settled_by"] = settled_by_name(payload["settled_by"])
    return DecodedEvent(name=name, escrow_key=escrow_key, payload=payload)


def contract_error_name(result_or_diagnostic: str) -> str | None:
    """Extracts ``Error(Contract, #n)`` from a diagnostic/simulation error string, if present."""
    marker = "Error(Contract, #"
    start = result_or_diagnostic.find(marker)
    if start < 0:
        return None
    end = result_or_diagnostic.find(")", start)
    try:
        code = int(result_or_diagnostic[start + len(marker) : end])
    except ValueError:
        return None
    return CONTRACT_ERRORS.get(code)
