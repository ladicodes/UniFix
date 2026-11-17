"""The accepted-agreement document: RFC 8785 (JCS) canonical JSON, hashed with SHA-256.

The exact bytes are stored (``agreements.canonical_json``, a text column, because jsonb
reorders keys). PostgreSQL re-checks the hash with a CHECK constraint. The Issue 5/6
escrow terms embed ``agreement_hash``, which binds the on-chain escrow to these terms
(STELLAR_ESCROW_DESIGN §6). Every field is always present; absent values are null; money
is integer minor units; timestamps are RFC 3339 UTC to the second.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime
from typing import Any

import rfc8785

SCHEMA = "unifix.agreement.v1"
DISPUTE_POLICY = "unifix.dispute-policy.v1"


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_document(
    *,
    agreement_id: uuid.UUID,
    booking_id: uuid.UUID,
    quote_id: uuid.UUID,
    quote_version: int,
    conversation_id: uuid.UUID,
    service_request_id: uuid.UUID | None,
    customer_id: uuid.UUID,
    professional_id: uuid.UUID,
    title: str,
    description: str,
    labour_minor: int,
    materials_minor: int,
    total_minor: int,
    currency: str,
    completion_date: date,
    service_method: str,
    payment_terms: str,
    milestones: list[dict[str, Any]],
    accepted_at: datetime,
) -> dict[str, Any]:
    if total_minor != labour_minor + materials_minor:
        raise ValueError("total_minor must equal labour_minor + materials_minor")
    return {
        "schema": SCHEMA,
        "agreement_id": str(agreement_id),
        "booking_id": str(booking_id),
        "quote_id": str(quote_id),
        "quote_version": quote_version,
        "conversation_id": str(conversation_id),
        "service_request_id": str(service_request_id) if service_request_id else None,
        "customer_id": str(customer_id),
        "professional_id": str(professional_id),
        "title": title,
        "description": description,
        "labour_minor": labour_minor,
        "materials_minor": materials_minor,
        "total_minor": total_minor,
        "currency": currency,
        "completion_date": completion_date.isoformat(),
        "service_method": service_method,
        "payment_terms": payment_terms,
        "milestones": [{"title": str(m["title"]), "percent": int(m["percent"])} for m in milestones],
        "dispute_policy": DISPUTE_POLICY,
        "accepted_at": _timestamp(accepted_at),
    }


def canonicalize(document: dict[str, Any]) -> str:
    return rfc8785.dumps(document).decode("utf-8")


def digest(canonical_json: str) -> str:
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
