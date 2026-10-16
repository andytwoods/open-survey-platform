"""Injected effects: clock and randomness.

Everything in `osp_app.auth` that needs the time or random bytes takes one of
these, so tests run on a fake clock and deterministic bytes.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time, timezone-aware UTC."""
        ...


class RandomSource(Protocol):
    def token_bytes(self, n: int) -> bytes:
        """`n` cryptographically secure random bytes."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class SystemRandom:
    def token_bytes(self, n: int) -> bytes:
        return secrets.token_bytes(n)
