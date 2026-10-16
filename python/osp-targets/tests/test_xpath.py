"""AST → XPath lowering, and the in-form assignment draw matching osp_engine."""

from __future__ import annotations

import math
from decimal import Decimal

import pytest
from osp_engine.random import NODE_SEED_MAX, assign, node_seed
from osp_expr import EXPR_ADAPTER
from osp_spec.model import AssignedVariable
from osp_targets.xlsform.export import _assign_calc
from osp_targets.xlsform.xpath import XPathContext, XPathWriter, string_literal

NAMES = {"q": "q", "t": "t_name", "m": "m", "d1": "d1", "d2": "d2", "c": "c", "x": "x"}
TYPES = {
    "q": "integer",
    "t": "text",
    "m": "multi",
    "d1": "date",
    "d2": "date",
    "c": "single",
    "x": "decimal",
}


def ex(data: dict) -> object:
    return EXPR_ADAPTER.validate_python(data)


def ref(i: str) -> dict:
    return {"kind": "ref", "id": i}


def num(v: int) -> dict:
    return {"kind": "int", "value": v}


def cond(data: dict, self_id: str | None = None) -> str:
    return XPathWriter(XPathContext(NAMES, TYPES, self_id)).condition(ex(data))


def value(data: dict) -> str:
    return XPathWriter(XPathContext(NAMES, TYPES)).value(ex(data))


def test_comparison_is_false_when_an_operand_is_missing() -> None:
    got = cond({"kind": "compare", "op": ">", "left": ref("q"), "right": num(5)})
    assert got == "(string-length(${q}) > 0) and (${q} > 5)"


def test_not_equal_is_guarded_too() -> None:
    got = cond({"kind": "compare", "op": "!=", "left": ref("t"), "right": ref("q")})
    assert got == (
        "(string-length(${t_name}) > 0) and (string-length(${q}) > 0) and (${t_name} != ${q})"
    )


def test_comparison_with_null_literal_is_false() -> None:
    assert cond({"kind": "compare", "op": "==", "left": ref("q"), "right": {"kind": "null"}}) == (
        "false()"
    )
    assert cond({"kind": "not", "arg": {"kind": "compare", "op": "==", "left": {"kind": "null"},
                 "right": {"kind": "null"}}}) == "true()"  # fmt: skip


def test_division_guards_divisor_and_uses_div() -> None:
    e = {
        "kind": "compare",
        "op": ">",
        "left": {"kind": "arith", "op": "/", "left": ref("q"), "right": ref("x")},
        "right": {"kind": "decimal", "value": "1.50"},
    }
    got = cond(e)
    assert "${q} div ${x}" in got
    assert "${x} != 0" in got
    assert got.endswith("1.50)")


def test_calculate_value_is_empty_when_inputs_are_missing() -> None:
    e = {"kind": "arith", "op": "+", "left": ref("q"), "right": num(1)}
    assert value(e) == "if(string-length(${q}) > 0, ${q} + 1, '')"
    assert value(num(-3)) == "(-3)"
    assert value({"kind": "null"}) == "''"


def test_contains_and_answered() -> None:
    assert cond({"kind": "contains", "ref": ref("m"), "value": num(2)}) == "selected(${m}, '2')"
    assert cond({"kind": "answered", "ref": ref("t")}) == "string-length(${t_name}) > 0"


def test_codes_compare_as_text() -> None:
    got = cond({"kind": "compare", "op": "==", "left": ref("c"), "right": num(1)})
    assert got.endswith("(${c} = '1')")


def test_date_ordering_uses_decimal_date_time() -> None:
    got = cond({"kind": "compare", "op": "<", "left": ref("d1"), "right": ref("d2")})
    assert "decimal-date-time(${d1}) < decimal-date-time(${d2})" in got


def test_own_constraint_uses_dot_without_guard() -> None:
    got = cond({"kind": "compare", "op": ">=", "left": ref("q"), "right": num(18)}, self_id="q")
    assert got == ". >= 18"


def test_and_or_not() -> None:
    a = {"kind": "answered", "ref": ref("q")}
    b = {"kind": "answered", "ref": ref("t")}
    assert cond({"kind": "and", "args": [a, b]}) == (
        "(string-length(${q}) > 0) and (string-length(${t_name}) > 0)"
    )
    assert cond({"kind": "or", "args": [a, b]}).count(" or ") == 1
    assert cond({"kind": "not", "arg": a}) == "not(string-length(${q}) > 0)"


def test_non_boolean_condition_is_false() -> None:
    assert cond(ref("q")) == "false()"


@pytest.mark.parametrize(
    ("s", "expected"),
    [("a", "'a'"), ("it's", '"it\'s"'), ("""a'b"c""", "concat('a', \"'\", 'b\"c')")],
)
def test_string_literal(s: str, expected: str) -> None:
    assert string_literal(s) == expected


# --- Assignment draw parity ------------------------------------------------------------


def _xpath_assign_index(seed: int, n: int) -> int:
    """What the generated XPath computes, with IEEE doubles as XPath numbers are."""
    m = 2147483647.0
    state = math.fmod(float(seed) * 16807.0, m)
    return math.floor(((state - 1.0) * float(n)) / (m - 1.0))


SEEDS = [1, 2, 3, 16807, NODE_SEED_MAX, NODE_SEED_MAX - 1, 2**30, 123456789] + [
    node_seed("srv:3", s, f"framing{k}") for s in (1, 7, 99, 2**40) for k in range(25)
]


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 7, 10])
def test_assign_formula_matches_engine(n: int) -> None:
    levels = list(range(n))
    for seed in SEEDS:
        assert _xpath_assign_index(seed, n) == assign(levels, None, seed), seed


def test_assign_calc_shape() -> None:
    v = AssignedVariable(id="framing", kind="assigned", levels=["gain", "loss"])
    got = _assign_calc("osp_seed_framing", v)
    assert got.startswith("selected-at('gain loss', floor(")
    assert "mod 2147483647" in got and "div 2147483646" in got
    v2 = AssignedVariable(id="v", kind="assigned", levels=["a b", "c"])
    assert _assign_calc("s", v2).startswith("if(")


def test_decimal_literal_plain_notation() -> None:
    assert value({"kind": "decimal", "value": str(Decimal("1E+2"))}) == "100"


def test_bool_literals_as_conditions():
    assert cond({"kind": "bool", "value": True}) == "true()"
    assert cond({"kind": "bool", "value": False}) == "false()"
    either = {
        "kind": "or",
        "args": [{"kind": "bool", "value": False}, {"kind": "bool", "value": True}],
    }
    assert "true()" in cond(either)


def test_bool_literal_as_value_is_the_stored_string():
    w = XPathWriter(XPathContext(NAMES, TYPES, None))
    assert w.value(ex({"kind": "bool", "value": True})) == "'true'"
