"""Injected effects: clock and randomness (tests use fakes)."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

#: Returns the current time, timezone-aware UTC.
Clock = Callable[[], datetime]


def system_clock() -> datetime:
    return datetime.now(UTC)


class RandomSource(Protocol):
    def token_bytes(self, n: int) -> bytes:
        """``n`` cryptographically secure random bytes."""
        ...

    def randbelow(self, n: int) -> int:
        """A cryptographically secure integer in ``0 .. n - 1``."""
        ...


class SystemRandom:
    """The server-side CSPRNG (``secrets``)."""

    def token_bytes(self, n: int) -> bytes:
        return secrets.token_bytes(n)

    def randbelow(self, n: int) -> int:
        return secrets.randbelow(n)
