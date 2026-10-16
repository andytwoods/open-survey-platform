"""osp-expr AST → LimeSurvey Expression Manager: a conversion table, one row per case."""

from __future__ import annotations

from typing import Any

import pytest
from osp_expr import EXPR_ADAPTER
from osp_targets.lss import EMContext, EMWriter
from osp_targets.lss.em import and_, not_, or_, string_literal

CODES = {"q": "q", "t": "tname", "m": "m", "d1": "d1", "d2": "d2", "c": "c", "x": "x", "a": "arm",
         "b": "flag"}  # fmt: skip
TYPES = {"q": "integer", "t": "text", "m": "multi", "d1": "date", "d2": "date", "c": "single",
         "x": "decimal", "a": "assigned", "b": "boolean"}  # fmt: skip
CHOICES = {"c": {"1": "1", "-1": "A1", "yes": "yes"}, "m": {"a": "a", "b": "b", "x y": "A1"}}


def ex(data: dict[str, Any]) -> Any:
    return EXPR_ADAPTER.validate_python(data)


def ref(i: str) -> dict[str, Any]:
    return {"kind": "ref", "id": i}


def num(v: int) -> dict[str, Any]:
    return {"kind": "int", "value": v}


def text(v: str) -> dict[str, Any]:
    return {"kind": "text", "value": v}


def cmp(op: str, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "compare", "op": op, "left": left, "right": right}


def arith(op: str, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "arith", "op": op, "left": left, "right": right}


def writer() -> EMWriter:
    return EMWriter(EMContext(CODES, TYPES, CHOICES))


CONDITIONS: list[tuple[str, dict[str, Any], str]] = [
    ("compare guarded", cmp(">", ref("q"), num(5)), "!is_empty(q.NAOK) and (q.NAOK > 5)"),
    (
        "not-equal guarded too",
        cmp("!=", ref("t"), ref("q")),
        "!is_empty(tname.NAOK) and !is_empty(q.NAOK) and (tname.NAOK != q.NAOK)",
    ),
    ("compare with null is false", cmp("==", ref("q"), {"kind": "null"}), "0"),
    ("null == null is false", cmp("==", {"kind": "null"}, {"kind": "null"}), "0"),
    (
        "not of a null compare is true",
        {"kind": "not", "arg": cmp("==", {"kind": "null"}, {"kind": "null"})},
        "1",
    ),
    (
        "text literal",
        cmp("==", ref("t"), text("abc")),
        '!is_empty(tname.NAOK) and (tname.NAOK == "abc")',
    ),  # fmt: skip
    (
        "text with double quote",
        cmp("==", ref("t"), text('a"b')),
        "!is_empty(tname.NAOK) and (tname.NAOK == 'a\"b')",
    ),  # fmt: skip
    (
        "text with both quotes",
        cmp("==", ref("t"), text("a\"b'c")),
        '!is_empty(tname.NAOK) and (tname.NAOK == join("a", \'"\', "b\'c"))',
    ),
    ("negative number", cmp(">", ref("q"), num(-3)), "!is_empty(q.NAOK) and (q.NAOK > (-3))"),
    (
        "decimal in plain notation",
        cmp("<", ref("x"), {"kind": "decimal", "value": "1E+2"}),
        "!is_empty(x.NAOK) and (x.NAOK < 100)",
    ),
    (
        "single choice: code as text",
        cmp("==", ref("c"), num(1)),
        '!is_empty(c.NAOK) and (c.NAOK == "1")',
    ),  # fmt: skip
    (
        "single choice: remapped code",
        cmp("==", ref("c"), num(-1)),
        '!is_empty(c.NAOK) and (c.NAOK == "A1")',
    ),
    (
        "literal on the left is mapped too",
        cmp("!=", num(-1), ref("c")),
        '!is_empty(c.NAOK) and ("A1" != c.NAOK)',
    ),
    ("assigned level", cmp("==", ref("a"), num(2)), '!is_empty(arm.NAOK) and (arm.NAOK == "2")'),
    (
        "dates compare via strtotime",
        cmp("<", ref("d1"), ref("d2")),
        "!is_empty(d1.NAOK) and !is_empty(d2.NAOK) and (strtotime(d1.NAOK) < strtotime(d2.NAOK))",
    ),
    (
        "date against a literal",
        cmp(">=", ref("d1"), text("2024-01-31")),
        '!is_empty(d1.NAOK) and (strtotime(d1.NAOK) >= strtotime("2024-01-31"))',
    ),
    (
        "division guards the divisor",
        cmp(">", arith("/", ref("q"), ref("x")), {"kind": "decimal", "value": "1.50"}),
        "!is_empty(q.NAOK) and !is_empty(x.NAOK) and (x.NAOK != 0) and ((q.NAOK / x.NAOK) > 1.50)",
    ),
    (
        "literal divisor needs no guard",
        cmp("==", arith("/", ref("q"), num(4)), num(2)),
        "!is_empty(q.NAOK) and ((q.NAOK / 4) == 2)",
    ),
    ("division by literal zero is null", cmp("==", arith("/", ref("q"), num(0)), num(2)), "0"),
    (
        "arithmetic precedence kept by parentheses",
        cmp("==", arith("*", arith("-", ref("q"), num(2)), num(3)), num(24)),
        "!is_empty(q.NAOK) and (((q.NAOK - 2) * 3) == 24)",
    ),
    (
        "and / or / not",
        {
            "kind": "or",
            "args": [
                {"kind": "and", "args": [cmp(">", ref("q"), num(1)), cmp("<", ref("q"), num(9))]},
                {"kind": "not", "arg": {"kind": "answered", "ref": ref("t")}},
            ],
        },
        "((!is_empty(q.NAOK) and (q.NAOK > 1)) and (!is_empty(q.NAOK) and (q.NAOK < 9)))"
        " or is_empty(tname.NAOK)",
    ),
    ("answered", {"kind": "answered", "ref": ref("q")}, "!is_empty(q.NAOK)"),
    (
        "answered on multi: any subquestion",
        {"kind": "answered", "ref": ref("m")},
        '(m_a.NAOK == "Y") or (m_b.NAOK == "Y") or (m_A1.NAOK == "Y")',
    ),
    ("contains", {"kind": "contains", "ref": ref("m"), "value": text("b")}, 'm_b.NAOK == "Y"'),
    (
        "contains a remapped code",
        {"kind": "contains", "ref": ref("m"), "value": text("x y")},
        'm_A1.NAOK == "Y"',
    ),
    ("contains an unknown code", {"kind": "contains", "ref": ref("m"), "value": text("zz")}, "0"),
    ("contains null", {"kind": "contains", "ref": ref("m"), "value": {"kind": "null"}}, "0"),
    (
        "contains a computed value",
        {"kind": "contains", "ref": ref("m"), "value": ref("t")},
        '!is_empty(tname.NAOK) and (((tname.NAOK == "a") and (m_a.NAOK == "Y")) or '
        '((tname.NAOK == "b") and (m_b.NAOK == "Y")) or '
        '((tname.NAOK == "x y") and (m_A1.NAOK == "Y")))',
    ),
    ("boolean literal true", {"kind": "bool", "value": True}, "1"),
    ("boolean literal false", {"kind": "bool", "value": False}, "0"),
    ("boolean variable", ref("b"), "flag.NAOK == 1"),
]


@pytest.mark.parametrize(("label", "expr", "want"), CONDITIONS, ids=[c[0] for c in CONDITIONS])
def test_condition_table(label: str, expr: dict[str, Any], want: str) -> None:
    assert writer().condition(ex(expr)) == want


VALUES: list[tuple[str, dict[str, Any], str]] = [
    ("plain reference", ref("q"), 'if(!is_empty(q.NAOK), q.NAOK, "")'),
    (
        "sum is null when an input is",
        arith("+", ref("q"), ref("x")),
        'if(!is_empty(q.NAOK) and !is_empty(x.NAOK), q.NAOK + x.NAOK, "")',
    ),
    ("literal only", arith("*", num(2), num(3)), "2 * 3"),
    ("null", {"kind": "null"}, '""'),
    ("division by zero literal", arith("/", ref("q"), num(0)), '""'),
    (
        "condition as a value",
        cmp(">", ref("q"), num(1)),
        "if(!is_empty(q.NAOK) and (q.NAOK > 1), 1, 0)",
    ),  # fmt: skip
    (
        "multi as a value: its codes",
        ref("m"),
        'if(!is_empty(trim(join(if(m_a.NAOK == "Y", "a ", ""), if(m_b.NAOK == "Y", "b ", ""), '
        'if(m_A1.NAOK == "Y", "A1 ", "")))), trim(join(if(m_a.NAOK == "Y", "a ", ""), '
        'if(m_b.NAOK == "Y", "b ", ""), if(m_A1.NAOK == "Y", "A1 ", ""))), "")',
    ),
]


@pytest.mark.parametrize(("label", "expr", "want"), VALUES, ids=[v[0] for v in VALUES])
def test_value_table(label: str, expr: dict[str, Any], want: str) -> None:
    assert writer().value(ex(expr)) == want


def test_helpers_fold_constants() -> None:
    assert and_("1", "a == 1") == "a == 1"
    assert and_("a", "0") == "0"
    assert or_("0", "0") == "0"
    assert or_("a", "1") == "1"
    assert not_("1") == "0"
    assert not_("!is_empty(q.NAOK)") == "is_empty(q.NAOK)"
    assert not_("a > 1") == "!(a > 1)"
    assert string_literal("plain") == '"plain"'
