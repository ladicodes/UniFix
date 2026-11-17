"""Time source. Code asks the clock instead of calling datetime.now() so tests can control time."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock(Clock):
    """Deterministic clock for tests."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)
