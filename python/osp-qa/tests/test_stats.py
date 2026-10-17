"""Chi-square tail without SciPy, against closed forms and table values."""

from __future__ import annotations

import math

import pytest
from osp_qa import chi2_sf, chi_square, gamma_q


@pytest.mark.parametrize("x", [0.0, 0.1, 1.0, 2.5, 7.0, 30.0, 200.0])
def test_two_df_is_exponential(x):
    assert chi2_sf(x, 2) == pytest.approx(math.exp(-x / 2), rel=1e-10, abs=1e-300)


@pytest.mark.parametrize("x", [0.01, 0.5, 1.0, 3.0, 9.0, 25.0])
def test_one_df_is_erfc(x):
    assert chi2_sf(x, 1) == pytest.approx(math.erfc(math.sqrt(x / 2)), rel=1e-9)


@pytest.mark.parametrize(
    ("x", "df", "p"),
    [(3.841458820694124, 1, 0.05), (11.070497693516351, 5, 0.05), (20.515005652432873, 5, 0.001)],
)
def test_table_values(x, df, p):
    assert chi2_sf(x, df) == pytest.approx(p, rel=1e-8)


def test_edges():
    assert chi2_sf(0, 3) == 1.0
    assert gamma_q(1, 0) == 1.0
    assert 0 <= chi2_sf(1e6, 3) < 1e-100
    with pytest.raises(ValueError):
        chi2_sf(1, 0)
    with pytest.raises(ValueError):
        gamma_q(0, 1)


def test_goodness_of_fit():
    cs = chi_square([10, 20, 30], [20, 20, 20])
    assert cs is not None
    assert cs.statistic == pytest.approx(10.0)
    assert cs.df == 2
    assert cs.p_value == pytest.approx(math.exp(-5))
    assert cs.max_deviation == pytest.approx(0.5)
    assert chi_square([1], [1]) is None
    assert chi_square([1, 2], [0, 3]) is None
    assert chi_square([1, 2], [1]) is None
