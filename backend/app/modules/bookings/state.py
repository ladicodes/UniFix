"""The booking state machine: the only definition of which transitions exist and who may make them.

Financial transitions (into FUNDED, COMPLETION_SUBMITTED, COMPLETED, REFUNDED, RESOLVED,
DISPUTED) may only be made by the CHAIN actor: the Batch 2 reconciler, after confirmed
and verified on-chain events. No API route can make them (ARCHITECTURE §8.2).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.bookings.models import BookingStatus as S
from app.modules.bookings.models import TimelineActor as A


@dataclass(frozen=True, slots=True)
class Rule:
    actors: frozenset[A]
    action: str | None  # the allowed_actions name for user-initiated transitions


_USER = frozenset({A.CUSTOMER, A.PROFESSIONAL})
_CHAIN = frozenset({A.CHAIN})

TRANSITIONS: dict[tuple[S, S], Rule] = {
    (S.PENDING_PAYMENT, S.CANCELLED): Rule(_USER | {A.SYSTEM}, "CANCEL"),
    (S.PENDING_PAYMENT, S.FUNDED): Rule(_CHAIN, None),
    (S.FUNDED, S.IN_PROGRESS): Rule(frozenset({A.PROFESSIONAL}), "START"),
    (S.FUNDED, S.COMPLETION_SUBMITTED): Rule(_CHAIN, None),
    (S.IN_PROGRESS, S.COMPLETION_SUBMITTED): Rule(_CHAIN, None),
    (S.FUNDED, S.REFUNDED): Rule(_CHAIN, None),
    (S.IN_PROGRESS, S.REFUNDED): Rule(_CHAIN, None),
    (S.COMPLETION_SUBMITTED, S.REFUNDED): Rule(_CHAIN, None),
    (S.COMPLETION_SUBMITTED, S.COMPLETED): Rule(_CHAIN, None),
    # The contract lets the customer release before completion is submitted (e.g. from another
    # wallet tool); the mirror must follow the chain.
    (S.FUNDED, S.COMPLETED): Rule(_CHAIN, None),
    (S.IN_PROGRESS, S.COMPLETED): Rule(_CHAIN, None),
    (S.FUNDED, S.DISPUTED): Rule(_CHAIN, None),
    (S.IN_PROGRESS, S.DISPUTED): Rule(_CHAIN, None),
    (S.COMPLETION_SUBMITTED, S.DISPUTED): Rule(_CHAIN, None),
    (S.DISPUTED, S.COMPLETED): Rule(_CHAIN, None),
    (S.DISPUTED, S.REFUNDED): Rule(_CHAIN, None),
    (S.DISPUTED, S.RESOLVED): Rule(_CHAIN, None),
}

TERMINAL = frozenset({S.COMPLETED, S.CANCELLED, S.REFUNDED, S.RESOLVED})


def rule_for(current: S, target: S) -> Rule | None:
    return TRANSITIONS.get((current, target))


def user_actions(current: S, actor: A) -> list[str]:
    """Actions a participant may take now, derived from the table (one source of truth)."""
    return sorted(
        rule.action
        for (source, _), rule in TRANSITIONS.items()
        if source == current and rule.action is not None and actor in rule.actors
    )
