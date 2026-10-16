"""A simple in-memory token bucket per key (session start, resume), with an injected clock.

Buckets live only in process memory; nothing about the caller is persisted. Per
process, so several API workers each allow ``capacity`` (good enough for the MVP).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from .ports import Clock, system_clock


@dataclass
class _Bucket:
    tokens: float
    at: float


class TokenBucket:
    def __init__(
        self,
        capacity: float,
        refill_per_second: float,
        clock: Clock = system_clock,
        max_keys: int = 10_000,
    ) -> None:
        if capacity <= 0 or refill_per_second < 0:
            raise ValueError("capacity must be > 0 and refill_per_second >= 0")
        self.capacity = float(capacity)
        self.rate = float(refill_per_second)
        self._clock = clock
        self._max_keys = max_keys
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _now(self) -> float:
        return self._clock().timestamp()

    def allow(self, key: str, cost: float = 1.0) -> bool:
        """Take ``cost`` tokens from ``key``'s bucket; False (and take nothing) if short."""
        now = self._now()
        with self._lock:
            b = self._buckets.get(key)
            if b is None:
                if len(self._buckets) >= self._max_keys:
                    self._prune(now)
                b = self._buckets[key] = _Bucket(self.capacity, now)
            else:
                elapsed = max(0.0, now - b.at)  # a clock going backwards never adds tokens
                b.tokens = min(self.capacity, b.tokens + elapsed * self.rate)
                b.at = now
            if b.tokens + 1e-9 >= cost:
                b.tokens -= cost
                return True
            return False

    def _prune(self, now: float) -> None:
        """Drop buckets that have refilled completely (they behave like new ones)."""
        full = [
            k
            for k, b in self._buckets.items()
            if b.tokens + (now - b.at) * self.rate >= self.capacity
        ]
        for k in full:
            del self._buckets[k]
        if len(self._buckets) >= self._max_keys:  # still full: forget the oldest
            for k in sorted(self._buckets, key=lambda k: self._buckets[k].at)[
                : len(self._buckets) // 2
            ]:
                del self._buckets[k]
