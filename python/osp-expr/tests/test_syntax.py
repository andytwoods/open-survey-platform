"""Parser and printer: examples, canonical form, precedence and error positions."""

from decimal import Decimal

import pytest
from osp_expr import (
    And,
    Answered,
    Arith,
    Compare,
    Contains,
    DecLit,
    IntLit,
    Not,
    NullLit,
    Or,
    Ref,
    TextLit,
    parse,
    to_text,
)
from osp_expr.syntax import MAX_DEPTH

q3, q7 = Ref(id="q3"), Ref(id="q7")


def ok(src):
    result = parse(src)
    assert result.ok, result.diagnostics
    return result.expr


def test_headline_example():
    expr = ok('q3 > 5 and contains(q7, "b")')
    assert expr == And(
        args=(
            Compare(op=">", left=q3, right=IntLit(value=5)),
            Contains(ref=q7, value=TextLit(value="b")),
        )
    )


@pytest.mark.parametrize(
    "src, canonical",
    [
        ("q3>5", "q3 > 5"),
        ("  q3   ==\n5 ", "q3 == 5"),
        ("(q3 > 5)", "q3 > 5"),
        ("((answered(q3)))", "answered(q3)"),
        ("a and b and c", "a and b and c"),
        ("a and (b and c)", "a and (b and c)"),
        ("(a or b) and c", "(a or b) and c"),
        ("a or b and c", "a or b and c"),
        ("not a > 1", "not a > 1"),
        ("not (a and b)", "not (a and b)"),
        ("not not a", "not not a"),
        ("1 + 2 * 3", "1 + 2 * 3"),
        ("(1 + 2) * 3", "(1 + 2) * 3"),
        ("1 - (2 - 3)", "1 - (2 - 3)"),
        ("(1 - 2) - 3", "1 - 2 - 3"),
        ("a / (b * c)", "a / (b * c)"),
        ("a - -5", "a - -5"),
        ("- 5 < a", "-5 < a"),
        ("007 == a", "7 == a"),
        ("a == 1.50", "a == 1.50"),
        ("a == null", "a == null"),
        ('a == "say \\"hi\\"\\n"', 'a == "say \\"hi\\"\\n"'),
        ('a == "\\u0041"', 'a == "A"'),
        ('a == "\\u0001"', 'a == "\\u0001"'),
        ("(a < b) == (c < d)", "(a < b) == (c < d)"),
        ("contains(q7, 1) or answered(q3)", "contains(q7, 1) or answered(q3)"),
        ("contains(q7,a or b)", "contains(q7, a or b)"),
    ],
)
def test_canonical_print(src, canonical):
    expr = ok(src)
    assert to_text(expr) == canonical
    assert ok(canonical) == expr


def test_literal_kinds():
    assert ok("5") == IntLit(value=5)
    assert ok("-5") == IntLit(value=-5)
    assert ok("2.25") == DecLit(value=Decimal("2.25"))
    assert ok("null") == NullLit()
    assert ok('""') == TextLit(value="")


def test_decimal_without_fraction_prints_as_decimal():
    assert to_text(DecLit(value=Decimal("1E+3"))) == "1000.0"
    assert ok("1000.0") == DecLit(value=Decimal("1E+3"))


def test_precedence_shapes():
    assert ok("not a == 1 and b") == And(
        args=(Not(arg=Compare(op="==", left=Ref(id="a"), right=IntLit(value=1))), Ref(id="b"))
    )
    assert ok("a or b or c") == Or(args=(Ref(id="a"), Ref(id="b"), Ref(id="c")))
    assert ok("1 - 2 - 3") == Arith(
        op="-",
        left=Arith(op="-", left=IntLit(value=1), right=IntLit(value=2)),
        right=IntLit(value=3),
    )
    assert ok("answered(q3)") == Answered(ref=q3)


@pytest.mark.parametrize(
    "src, code, start, end",
    [
        ("", "expected", 0, 0),
        ("q3 >", "expected", 4, 4),
        ("q3 = 5", "unexpected-char", 3, 4),
        ("q3 && q4", "unexpected-char", 3, 5),
        ("q3 > 5)", "unexpected", 6, 7),
        ("(q3 > 5", "expected", 7, 7),
        ('q3 == "abc', "unterminated-text", 6, 10),
        ('q3 == "a\\qb"', "bad-escape", 8, 10),
        ("q3 == 'b'", "unexpected-char", 6, 7),
        ("1 < q3 < 5", "chained-comparison", 7, 8),
        ("-q3", "unary-minus", 0, 3),
        ("5. + 1", "bad-number", 0, 2),
        ("5abc", "bad-number", 0, 4),
        ("1.2.3", "bad-number", 0, 5),
        ("foo(q3)", "unknown-function", 0, 3),
        ("answered(5)", "expected-question", 9, 10),
        ("contains(q7)", "expected", 11, 12),
        ("q3 == true", "reserved-word", 6, 10),
        ("q3 and", "expected", 6, 6),
        ("q3 # 1", "unexpected-char", 3, 4),
    ],
)
def test_errors_have_positions(src, code, start, end):
    result = parse(src)
    assert not result.ok
    (diag,) = result.diagnostics
    assert (diag.code, diag.start, diag.end) == (code, start, end), diag


def test_nesting_limit_is_a_diagnostic():
    deep = "(" * (MAX_DEPTH + 5) + "q3" + ")" * (MAX_DEPTH + 5)
    result = parse(deep)
    assert not result.ok and result.diagnostics[0].code == "too-deep"
    assert parse("not " * 10_000 + "q3").diagnostics[0].code == "too-deep"
    assert parse(" + ".join(["q3"] * 10_000)).diagnostics[0].code == "too-deep"


def test_long_flat_chains_are_fine():
    expr = ok(" and ".join(f"answered(q{i})" for i in range(2_000)))
    assert isinstance(expr, And) and len(expr.args) == 2_000


def test_huge_integer_literal_is_a_diagnostic():
    assert parse("9" * 5_000).diagnostics[0].code == "bad-number"


def test_non_text_input_is_a_diagnostic():
    assert parse(None).diagnostics[0].code == "not-text"  # type: ignore[arg-type]
