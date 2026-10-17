"""Chi-square goodness of fit, without SciPy (review.md §7.2 distribution checks).

``chi2_sf(x, df)`` is the upper tail P(X >= x) of a chi-square distribution: the
regularised upper incomplete gamma Q(df/2, x/2), by its series for small x and a
continued fraction (modified Lentz) otherwise. Accurate to ~1e-12, plenty for a p-value.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

_EPS = 1e-14
_MAX_ITER = 10_000
_TINY = 1e-300


def _lower_series(a: float, x: float) -> float:
    term = total = 1.0 / a
    ap = a
    for _ in range(_MAX_ITER):
        ap += 1.0
        term *= x / ap
        total += term
        if abs(term) < abs(total) * _EPS:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _upper_fraction(a: float, x: float) -> float:
    b = x + 1.0 - a
    c = 1.0 / _TINY
    d = 1.0 / b
    h = d
    for i in range(1, _MAX_ITER):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        d = _TINY if abs(d) < _TINY else d
        c = b + an / c
        c = _TINY if abs(c) < _TINY else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def gamma_q(a: float, x: float) -> float:
    """Regularised upper incomplete gamma Q(a, x), a > 0, x >= 0."""
    if a <= 0 or x < 0 or math.isnan(x):
        raise ValueError("gamma_q needs a > 0 and x >= 0")
    if x == 0:
        return 1.0
    if x < a + 1.0:
        return max(0.0, min(1.0, 1.0 - _lower_series(a, x)))
    return max(0.0, min(1.0, _upper_fraction(a, x)))


def chi2_sf(x: float, df: int) -> float:
    """P(X >= x) for X ~ chi-square(df)."""
    if df < 1:
        raise ValueError("df must be at least 1")
    return gamma_q(df / 2.0, max(0.0, x) / 2.0)


@dataclass(frozen=True)
class ChiSquare:
    statistic: float
    df: int
    p_value: float
    #: Largest |observed - expected| / expected over the categories.
    max_deviation: float


def chi_square(observed: Sequence[float], expected: Sequence[float]) -> ChiSquare | None:
    """Goodness of fit of ``observed`` counts to ``expected`` counts (same order).

    None when there are fewer than two categories or an expected count is zero.
    """
    if len(observed) != len(expected) or len(observed) < 2 or any(e <= 0 for e in expected):
        return None
    stat = sum((o - e) ** 2 / e for o, e in zip(observed, expected, strict=True))
    dev = max(abs(o - e) / e for o, e in zip(observed, expected, strict=True))
    df = len(observed) - 1
    return ChiSquare(statistic=stat, df=df, p_value=chi2_sf(stat, df), max_deviation=dev)
