"""Test doubles: a settable clock. For tests only. Never use in production."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

T0 = datetime(2026, 10, 16, 9, 0, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime = T0) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs: float) -> None:
        self._now += timedelta(**kwargs)
