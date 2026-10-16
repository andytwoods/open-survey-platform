"""Capability levels (planning/review.md §2.4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Level = Literal["native", "lowered", "approximated", "unsupported"]
LEVELS: tuple[Level, ...] = ("native", "lowered", "approximated", "unsupported")


@dataclass(frozen=True)
class Capability:
    """How a target handles one model feature.

    - ``native``: the target has the same feature with the same behaviour.
    - ``lowered``: rewritten into features the target has, behaviour kept.
    - ``approximated``: exported, but behaviour differs (diagnostic severity ``warning``).
    - ``unsupported``: dropped (diagnostic severity ``loss``).
    """

    level: Level
    note: str
