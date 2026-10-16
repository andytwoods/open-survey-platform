"""Test doubles: a settable clock, deterministic randomness and a cheap hasher.

For tests only (here and in later wiring tasks). Never use in production.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from .passwords import PasswordHasher

T0 = datetime(2026, 10, 16, 9, 0, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime = T0) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs: float) -> None:
        self._now += timedelta(**kwargs)


class FakeRandom:
    """Deterministic but distinct bytes on every call."""

    def __init__(self, seed: str = "rng") -> None:
        self._seed = seed
        self._n = 0

    def token_bytes(self, n: int) -> bytes:
        out = b""
        while len(out) < n:
            self._n += 1
            out += hashlib.sha256(f"{self._seed}-{self._n}".encode()).digest()
        return out[:n]


def cheap_hasher() -> PasswordHasher:
    """argon2id with minimal cost, so tests stay fast."""
    return PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
