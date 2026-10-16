"""Table test of the evaluator against planning/semantics.md.

Each row: (semantics section, expression text, environment, expected value,
expected condition result). Absent ids are not-reached; ``None`` is irrelevant or
unanswered (§1). Rows marked "OQ" follow a provisional rule from semantics.md
"Open questions".
"""

import datetime as dt
from decimal import Decimal

import pytest
from osp_expr import evaluate, evaluate_condition, parse

D = Decimal

ENV = {
    "n5": 5,
    "d2": D("2.5"),
    "zero": 0,
    "t": "abc",
    "irr": None,  # irrelevant / unanswered: stored as null (§1)
    "ws": "   ",  # whitespace-only text counts as unanswered (§2)
    "padded": "  abc  ",  # trimmed (§2)
    "m": {"a", "b"},
    "mi": [1, 2],
    "m_empty": set(),  # nothing ticked: unanswered (§1)
    "day": dt.date(2026, 10, 16),
    "s_code": 1,  # single-choice answer: a choice code (§2)
}
# "nr" is never in ENV: not-reached (§1).

ROWS = [
    # §3 comparisons with null are false, including null == null
    ("§3", "nr == 5", False, False),
    ("§3", "nr != 5", False, False),
    ("§3", "irr == 5", False, False),
    ("§3", "irr != 5", False, False),
    ("§3", "irr < 5", False, False),
    ("§3", "irr >= 5", False, False),
    ("§3", "null == null", False, False),
    ("§3", "null != null", False, False),
    ("§3", "nr == nr", False, False),
    ("§3", "irr == nr", False, False),
    ("§3", 'nr == "abc"', False, False),
    # §3 answered(x) tests presence
    ("§3", "answered(n5)", True, True),
    ("§3", "answered(irr)", False, False),
    ("§3", "answered(nr)", False, False),
    ("§3", "not answered(nr)", True, True),
    ("§2", "answered(ws)", False, False),
    ("§1", "answered(m_empty)", False, False),
    # §3 references to not-reached / irrelevant questions give null
    ("§3", "nr", None, False),
    ("§3", "irr", None, False),
    # §3 arithmetic with null gives null
    ("§3", "nr + 1", None, False),
    ("§3", "1 - irr", None, False),
    ("§3", "irr * 2", None, False),
    ("§3", "n5 / nr", None, False),
    ("§3", "null + null", None, False),
    ("§3", "(nr + 1) > 0", False, False),
    ("§3", "(nr + 1) == (nr + 1)", False, False),
    # §3 a condition that evaluates to null counts as false
    ("§3", "nr + 1", None, False),
    # §3 contains(multi, value)
    ("§3", 'contains(m, "a")', True, True),
    ("§3", 'contains(m, "z")', False, False),
    ("§3", "contains(mi, 2)", True, True),
    ("§3", 'contains(nr, "a")', False, False),
    ("§3", 'contains(irr, "a")', False, False),
    ("§3", "contains(m, null)", False, False),
    ("§1", 'contains(m_empty, "a")', False, False),
    # negation of a false comparison is true (comparisons are never null, §3)
    ("§3", "not nr > 5", True, True),
    ("§3", "not (irr == 5)", True, True),
    # §2 numbers are decimal; '/' returns a decimal; integers stay exact
    ("§2", "n5 + 1", 6, False),
    ("§2", "n5 / 2", D("2.5"), False),
    ("§2", "6 / 3", D("2"), False),
    ("§2", "1 / 3", D("0.3333333333333333333333333333"), False),
    ("§2", "d2 * 2", D("5.0"), False),
    ("§2", "0.1 + 0.2 == 0.3", True, True),
    ("§2", "n5 == 5.0", True, True),
    ("§2", "d2 > n5 / 2", False, False),
    ("§2", "d2 >= n5 / 2", True, True),
    # §2 text is trimmed; whitespace-only is unanswered
    ("§2", 'padded == "abc"', True, True),
    ("§2", 'ws == ""', False, False),
    ("§2", "ws", None, False),
    # §2 choice values are codes
    ("§2", "s_code == 1", True, True),
    ("§2", 's_code == "1"', False, False),
    # §2 dates compare as dates
    ("§2", "day == day", True, True),
    ("§2", "day < day", False, False),
    # boolean connectives
    ("§3", 'n5 > 1 and t == "abc"', True, True),
    ("§3", "n5 > 1 and nr > 1", False, False),
    ("§3", "nr > 1 or n5 > 1", True, True),
    # OQ: division by zero gives null (provisional)
    ("OQ", "n5 / 0", None, False),
    ("OQ", "n5 / zero", None, False),
    ("OQ", "(n5 / 0) == (n5 / 0)", False, False),
    # OQ: ill-typed operands (provisional)
    ("OQ", "t == 5", False, False),
    ("OQ", "t != 5", False, False),
    ("OQ", 't < "b"', False, False),
    ("OQ", "t + 1", None, False),
    ("OQ", "contains(t, 1)", False, False),
    ("OQ", "n5 and n5 > 1", False, False),
    ("OQ", "not n5", True, True),
    ("OQ", "not nr", True, True),
]


@pytest.mark.parametrize(
    "section, src, expected, condition",
    ROWS,
    ids=[f"{r[0]}: {r[1]}" for r in ROWS],
)
def test_semantics_table(section, src, expected, condition):
    expr = parse(src).expr
    assert expr is not None, src
    value = evaluate(expr, ENV)
    assert value == expected and type(value) is type(expected), (section, src, value)
    assert evaluate_condition(expr, ENV) is condition, (section, src)


def test_division_is_decimal_not_float():
    value = evaluate(parse("1 / 4").expr, {})
    assert isinstance(value, Decimal) and value == D("0.25")


def test_unsupported_env_values_are_null():
    expr = parse("x").expr
    for bad in (1.5, True, float("nan"), D("NaN"), D("Infinity"), object(), [1.5], [[1]]):
        assert evaluate(expr, {"x": bad}) is None


def test_env_lookup_errors_are_null():
    class Hostile(dict):
        def get(self, key, default=None):
            raise RuntimeError("boom")

    assert evaluate(parse("x == 1").expr, Hostile()) is False
