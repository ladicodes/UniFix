"""Agreement canonicalisation (RFC 8785) and the booking transition table."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime
from itertools import product
from typing import Any

import pytest

from app.modules.bookings import state
from app.modules.bookings.models import BookingStatus, TimelineActor
from app.modules.quotes import agreement

FIXED: dict[str, Any] = {
    "agreement_id": uuid.UUID("00000000-0000-4000-8000-000000000001"),
    "booking_id": uuid.UUID("00000000-0000-4000-8000-000000000002"),
    "quote_id": uuid.UUID("00000000-0000-4000-8000-000000000003"),
    "quote_version": 2,
    "conversation_id": uuid.UUID("00000000-0000-4000-8000-000000000004"),
    "service_request_id": None,
    "customer_id": uuid.UUID("00000000-0000-4000-8000-000000000005"),
    "professional_id": uuid.UUID("00000000-0000-4000-8000-000000000006"),
    "title": "Replace iPhone 13 screen",
    "description": "OEM screen, 3-month warranty — café receipt included",
    "labour_minor": 2_500_000,
    "materials_minor": 1_000_000,
    "total_minor": 3_500_000,
    "currency": "NGN",
    "completion_date": date(2026, 11, 20),
    "service_method": "PRO_TO_CUSTOMER",
    "payment_terms": "Single payment held in escrow",
    "milestones": [{"title": "Repair", "percent": 100}],
    "accepted_at": datetime(2026, 11, 17, 10, 30, 0, 123456, tzinfo=UTC),
}


def test_canonical_document_is_deterministic_and_sorted() -> None:
    first = agreement.canonicalize(agreement.build_document(**FIXED))
    second = agreement.canonicalize(agreement.build_document(**dict(reversed(list(FIXED.items())))))
    assert first == second
    keys = list(json.loads(first))
    assert keys == sorted(keys)
    assert '"accepted_at":"2026-11-17T10:30:00Z"' in first  # second precision, UTC
    assert '"service_request_id":null' in first
    assert '"dispute_policy":"unifix.dispute-policy.v1"' in first
    assert "café" in first  # UTF-8, not \\u escapes (RFC 8785)
    assert agreement.digest(first) == hashlib.sha256(first.encode()).hexdigest()


def test_any_term_change_changes_the_hash() -> None:
    base = agreement.digest(agreement.canonicalize(agreement.build_document(**FIXED)))
    for field, value in [
        ("labour_minor", 2_500_001),
        ("title", "Replace iPhone 13 screen."),
        ("quote_version", 3),
    ]:
        changed = {**FIXED, field: value}
        if field == "labour_minor":
            changed["total_minor"] = 3_500_001
        assert agreement.digest(agreement.canonicalize(agreement.build_document(**changed))) != base


def test_total_must_equal_sum() -> None:
    with pytest.raises(ValueError, match="total_minor"):
        agreement.build_document(**{**FIXED, "total_minor": 1})


def test_rfc8785_number_and_escape_vectors() -> None:
    # Vectors from RFC 8785 §3.2.2 / Appendix B (integers and string escaping).
    assert agreement.canonicalize({"b": 1, "a": [None, True, False, 0, -0, 9007199254740991]}) == (
        '{"a":[null,true,false,0,0,9007199254740991],"b":1}'
    )
    line_separator = chr(0x2028)  # JCS leaves U+2028 unescaped, unlike some JSON encoders
    raw = chr(0x0F) + '"\\\n' + line_separator
    expected = '{"s":"\\u000f\\"\\\\\\n' + line_separator + '"}'
    assert agreement.canonicalize({"s": raw}) == expected


FINANCIAL = {
    BookingStatus.FUNDED, BookingStatus.COMPLETION_SUBMITTED, BookingStatus.COMPLETED,
    BookingStatus.REFUNDED, BookingStatus.RESOLVED, BookingStatus.DISPUTED,
}  # fmt: skip
PEOPLE = (TimelineActor.CUSTOMER, TimelineActor.PROFESSIONAL, TimelineActor.ADMIN, TimelineActor.SYSTEM)


@pytest.mark.parametrize(("current", "target"), list(product(BookingStatus, BookingStatus)))
def test_no_person_or_system_actor_can_enter_a_financial_state(
    current: BookingStatus, target: BookingStatus
) -> None:
    rule = state.rule_for(current, target)
    if target in FINANCIAL:
        assert rule is None or rule.actors == {TimelineActor.CHAIN}


def test_terminal_states_have_no_exits() -> None:
    for terminal in state.TERMINAL:
        assert not [pair for pair in state.TRANSITIONS if pair[0] == terminal]


def test_shortcuts_are_impossible() -> None:
    for forbidden in [
        (BookingStatus.PENDING_PAYMENT, BookingStatus.COMPLETED),
        (BookingStatus.PENDING_PAYMENT, BookingStatus.IN_PROGRESS),
        (BookingStatus.FUNDED, BookingStatus.CANCELLED),
        (BookingStatus.COMPLETED, BookingStatus.REFUNDED),
        (BookingStatus.REFUNDED, BookingStatus.COMPLETED),
    ]:
        assert state.rule_for(*forbidden) is None


def test_allowed_actions_follow_the_table() -> None:
    assert state.user_actions(BookingStatus.PENDING_PAYMENT, TimelineActor.CUSTOMER) == ["CANCEL"]
    assert state.user_actions(BookingStatus.PENDING_PAYMENT, TimelineActor.PROFESSIONAL) == ["CANCEL"]
    assert state.user_actions(BookingStatus.FUNDED, TimelineActor.PROFESSIONAL) == ["START"]
    assert state.user_actions(BookingStatus.FUNDED, TimelineActor.CUSTOMER) == []
    assert state.user_actions(BookingStatus.COMPLETED, TimelineActor.CUSTOMER) == []
    assert all(
        state.user_actions(status, actor) == [] for status in BookingStatus for actor in [TimelineActor.CHAIN]
    )
