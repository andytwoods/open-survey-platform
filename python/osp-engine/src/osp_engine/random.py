"""Deterministic randomness for surveys (layer L2: no I/O, no global randomness).

Everything here is a pure function of its arguments. See ``planning/semantics.md`` §7.

ODK XForms ``randomize(nodeset, seed)``
=======================================

:func:`randomize` (alias :func:`shuffle`) reproduces Enketo's ``randomize`` exactly
(openrosa-xpath-evaluator 3.2.0, verified against enketo-core 9.0.1 in the Enketo spike, E5):

* PRNG: Park–Miller "minimal standard", modulus ``M = 2**31 - 1``, multiplier ``16807``.
* Seed to state: ``state = seed rem M`` with the remainder **truncating toward zero** (JS/Java
  ``%``, sign of the dividend; *not* Python's floor ``%``), then ``if state <= 0: state += M - 1``.
* Each draw: ``state = state * 16807 mod M``; ``u = (state - 1) / (M - 1)`` as an IEEE double.
* Inside-out Fisher–Yates, one draw per element including ``i = 0``:
  ``j = floor(u * (i + 1)); out[i] = out[j]; out[j] = items[i]``.

**Seed policy** (semantics §7): only positive integers ``1 <= seed <= 2**53 - 1`` are accepted.
Enketo throws on decimal and string seeds, and integers above ``2**53 - 1`` are not exact in
an XPath number literal. ``bool``, ``float``, ``str``, ``0`` and negatives raise
:class:`InvalidSeedError` (a ``ValueError`` carrying a ``code``), never anything else.

Per-node streams
================

Every random decision uses its own seed, :func:`node_seed`, so changing one randomiser never
changes another. The formula (versioned by the ``osp-node-seed/1`` tag) is::

    ns(s)  = str(len(utf8(s))) + ":" + utf8(s) + ","                  # netstring
    msg    = ns("osp-node-seed/1") + ns(survey_version)
             + ns(decimal(session_seed)) + ns(node_id)
    h      = SHA-256(msg)
    seed   = (int.from_bytes(h[0:8], "big") mod (2**31 - 2)) + 1          # 1 .. 2**31 - 2

The netstring framing makes the encoding unambiguous for any strings (no separator can
collide). The result lies in ``1 .. M - 1``, so it is a valid Enketo seed and becomes the
Park–Miller state unchanged (no reduction, never zero). Reducing 64 bits mod ``2**31 - 2``
has a bias below ``2**-32``. The XLSForm exporter emits these values as server-computed
``calculate`` defaults, so this formula must stay fixed; a change needs a new tag.

Server-side helpers
===================

* :func:`shuffle` orders questions and blocks (the same algorithm as ``randomize``).
* :func:`assign` picks one condition with probability proportional to its weight.

Pass seeds from :func:`node_seed`, not raw session seeds: the first Park–Miller draw from a
small seed is small (seed ``s`` gives ``u ~ 16807 s / M``), so consecutive raw seeds are not
spread out. Hashed per-node seeds are.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Sequence
from fractions import Fraction

__all__ = [
    "MAX_SEED",
    "NODE_SEED_MAX",
    "NODE_SEED_TAG",
    "InvalidSeedError",
    "RandomInputError",
    "assign",
    "check_seed",
    "node_seed",
    "randomize",
    "shuffle",
]

_M = 2**31 - 1  # Park–Miller modulus
_A = 16807  # Park–Miller multiplier

MAX_SEED = 2**53 - 1
"""Largest accepted seed (JS ``Number.MAX_SAFE_INTEGER``)."""

NODE_SEED_MAX = _M - 1
"""Largest value :func:`node_seed` returns (``2**31 - 2``)."""

NODE_SEED_TAG = "osp-node-seed/1"


class RandomInputError(ValueError):
    """Bad input to a function in this module. ``code`` is a stable diagnostic id."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class InvalidSeedError(RandomInputError):
    """A seed that is not a positive integer in ``1 .. MAX_SEED``."""


def check_seed(seed: object) -> int:
    """Return ``seed`` if it is a valid seed, else raise :class:`InvalidSeedError`."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise InvalidSeedError(
            "seed.not_integer", f"seed must be an integer, got {type(seed).__name__}"
        )
    if seed < 1:
        raise InvalidSeedError("seed.not_positive", f"seed must be >= 1, got {seed}")
    if seed > MAX_SEED:
        raise InvalidSeedError("seed.too_large", f"seed must be <= 2**53 - 1, got {seed}")
    return int(seed)


class _ParkMiller:
    __slots__ = ("state",)

    def __init__(self, seed: int) -> None:
        # Truncating remainder (sign of the dividend), as JS `%`. Exact for any int.
        s = abs(seed) % _M
        if seed < 0:
            s = -s
        if s <= 0:
            s += _M - 1
        self.state = s

    def next_state(self) -> int:
        self.state = (self.state * _A) % _M
        return self.state

    def next_float(self) -> float:
        return (self.next_state() - 1) / (_M - 1)


def _permute[T](items: Sequence[T], seed: int) -> list[T]:
    """The raw algorithm, for any int seed (Enketo semantics incl. 0 and negatives).

    Not part of the public API: callers go through :func:`randomize`, which enforces the
    seed policy. Kept separate so the tests can check parity on Enketo's 0 and negative seeds.
    """
    rng = _ParkMiller(seed)
    out: list[T] = []
    for i, x in enumerate(items):
        j = math.floor(rng.next_float() * (i + 1))
        if j == i:
            out.append(x)
        else:
            out.append(out[j])
            out[j] = x
    return out


def randomize[T](items: Iterable[T], seed: object) -> list[T]:
    """ODK XForms ``randomize(nodeset, seed)``: a new list, ``items`` untouched."""
    return _permute(list(items), check_seed(seed))


def shuffle[T](items: Iterable[T], seed: object) -> list[T]:
    """Server-side question/block order. Same algorithm and seed policy as :func:`randomize`."""
    return randomize(items, seed)


def _netstring(s: str, what: str) -> bytes:
    if not isinstance(s, str):
        raise RandomInputError(f"{what}.not_string", f"{what} must be a str")
    try:
        b = s.encode("utf-8")
    except UnicodeEncodeError as e:
        raise RandomInputError(f"{what}.not_utf8", f"{what} is not valid UTF-8 text") from e
    return str(len(b)).encode("ascii") + b":" + b + b","


def node_seed(survey_version: str, session_seed: int, node_id: str) -> int:
    """The seed for one random decision (``node_id``) in one session. See module docstring."""
    session = check_seed(session_seed)
    msg = (
        _netstring(NODE_SEED_TAG, "tag")
        + _netstring(survey_version, "survey_version")
        + _netstring(str(session), "session_seed")
        + _netstring(node_id, "node_id")
    )
    h = hashlib.sha256(msg).digest()
    return int.from_bytes(h[:8], "big") % (_M - 1) + 1


def _weight(w: object, index: int) -> Fraction:
    if isinstance(w, bool) or not isinstance(w, (int, float)):
        raise RandomInputError("weights.not_number", f"weight {index} must be a number")
    if isinstance(w, float) and not math.isfinite(w):
        raise RandomInputError("weights.not_finite", f"weight {index} must be finite")
    if w < 0:
        raise RandomInputError("weights.negative", f"weight {index} must be >= 0")
    return Fraction(w)


def assign[T](conditions: Sequence[T], weights: Sequence[float] | None, seed: object) -> T:
    """Pick one condition, with probability ``weights[k] / sum(weights)``.

    ``weights=None`` means equal weights. Uses one Park–Miller draw from ``seed`` and exact
    rational arithmetic: with ``r = state - 1`` (uniform on ``0 .. M - 2``), the result is the
    first ``k`` with ``r * total < cumulative_weight[k] * (M - 1)``. Zero-weight conditions
    are never chosen.
    """
    s = check_seed(seed)
    if isinstance(conditions, (str, bytes)) or not isinstance(conditions, Sequence):
        raise RandomInputError("conditions.not_sequence", "conditions must be a sequence")
    if len(conditions) == 0:
        raise RandomInputError("conditions.empty", "conditions must not be empty")
    if weights is None:
        ws = [Fraction(1)] * len(conditions)
    else:
        if isinstance(weights, (str, bytes)) or not isinstance(weights, Sequence):
            raise RandomInputError("weights.not_sequence", "weights must be a sequence")
        if len(weights) != len(conditions):
            raise RandomInputError(
                "weights.length",
                f"{len(weights)} weights for {len(conditions)} conditions",
            )
        ws = [_weight(w, i) for i, w in enumerate(weights)]
    total = sum(ws, Fraction(0))
    if total == 0:
        raise RandomInputError("weights.all_zero", "at least one weight must be > 0")
    r = _ParkMiller(s).next_state() - 1
    cumulative = Fraction(0)
    for cond, w in zip(conditions, ws, strict=True):
        cumulative += w
        if w > 0 and r * total < cumulative * (_M - 1):
            return cond
    raise AssertionError("unreachable: r < M - 1 and cumulative reaches total")  # pragma: no cover
