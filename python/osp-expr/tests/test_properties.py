"""Hypothesis property tests: round-trips, never-crash, and parser fuzzing."""

import datetime as dt
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st
from osp_expr import (
    And,
    Answered,
    Arith,
    BoolLit,
    Compare,
    Contains,
    DecLit,
    IntLit,
    Not,
    NullLit,
    Or,
    Ref,
    TextLit,
    evaluate,
    evaluate_condition,
    expr_from_json,
    expr_to_json,
    parse,
    references,
    to_text,
    typecheck,
)
from osp_expr.ast import KEYWORDS

IDS = ["q1", "q2", "q3", "age", "pets", "name", "nr", "_x", "answered", "contains"]

ident = st.one_of(
    st.sampled_from(IDS),
    st.from_regex(r"\A[A-Za-z_][A-Za-z0-9_]{0,8}\Z").filter(lambda s: s not in KEYWORDS),
)
refs = st.builds(Ref, id=ident)
leaves = st.one_of(
    st.builds(IntLit, value=st.integers(-(10**30), 10**30)),
    st.builds(
        DecLit,
        value=st.decimals(allow_nan=False, allow_infinity=False, places=None).filter(
            lambda d: abs(d.adjusted()) < 40
        ),
    ),
    st.builds(TextLit, value=st.text(max_size=12)),
    st.builds(BoolLit, value=st.booleans()),
    st.just(NullLit()),
    refs,
    st.builds(Answered, ref=refs),
)


def _extend(children):
    pair = st.tuples(children, children)
    many = st.lists(children, min_size=2, max_size=4).map(tuple)
    return st.one_of(
        st.builds(
            Compare,
            op=st.sampled_from(["==", "!=", "<", "<=", ">", ">="]),
            left=children,
            right=children,
        ),
        st.builds(Arith, op=st.sampled_from(["+", "-", "*", "/"]), left=children, right=children),
        st.builds(And, args=many),
        st.builds(Or, args=many),
        st.builds(Not, arg=children),
        st.builds(Contains, ref=refs, value=children),
        pair.map(lambda p: Compare(op="==", left=p[0], right=p[1])),
    )


exprs = st.recursive(leaves, _extend, max_leaves=25)

answers = st.one_of(
    st.none(),
    st.integers(-(10**20), 10**20),
    st.decimals(allow_nan=True, allow_infinity=True),
    st.text(max_size=8),
    st.dates(),
    st.sets(st.one_of(st.integers(-5, 5), st.sampled_from(["a", "b", "c"])), max_size=3),
    st.floats(),
    st.booleans(),
    st.lists(st.one_of(st.integers(), st.text(max_size=2), st.floats()), max_size=3),
)
envs = st.dictionaries(st.sampled_from(IDS), answers, max_size=len(IDS))


@given(exprs)
def test_parse_print_roundtrip(expr):
    """parse(print(ast)) == ast."""
    text = to_text(expr)
    result = parse(text)
    assert result.ok, (text, result.diagnostics)
    assert result.expr == expr


@given(exprs)
def test_print_is_canonical(expr):
    """print(parse(s)) is a fixed point: printing a parsed canonical string gives it back."""
    text = to_text(expr)
    assert to_text(parse(text).expr) == text


@given(exprs)
def test_json_roundtrip(expr):
    assert expr_from_json(expr_to_json(expr)) == expr


@given(exprs, envs)
def test_evaluate_never_crashes(expr, env):
    value = evaluate(expr, env)
    assert value is None or isinstance(value, bool | int | Decimal | str | dt.date | frozenset)
    assert not isinstance(value, float)
    assert evaluate_condition(expr, env) in (True, False)


@given(
    exprs,
    st.dictionaries(
        st.sampled_from(IDS),
        st.sampled_from(["integer", "decimal", "text", "single", "multi", "date", "bogus"]),
    ),
)
def test_static_helpers_never_crash(expr, types):
    for d in typecheck(expr, types):
        assert d.path is not None and d.path.startswith("/")
    assert set(references(expr)) <= set(_all_ids(expr))


def _all_ids(expr):
    return [m.group(0) for m in __import__("re").finditer(r"[A-Za-z_]\w*", to_text(expr))]


def _check_parse_result(src):
    result = parse(src)
    if result.ok:
        assert result.diagnostics == ()
        # Anything that parses prints canonically and reparses to the same AST.
        assert parse(to_text(result.expr)).expr == result.expr
    else:
        assert result.diagnostics
        for d in result.diagnostics:
            assert d.severity == "error"
            assert d.start is not None and 0 <= d.start <= len(src)
            assert d.end is None or d.start <= d.end <= len(src)


@settings(max_examples=500)
@given(st.text())
def test_fuzz_parser_arbitrary_text(src):
    _check_parse_result(src)


TOKENS = [
    "q3",
    "q7",
    "5",
    "-",
    "2.5",
    '"b"',
    '"',
    "\\",
    "null",
    "and",
    "or",
    "not",
    "(",
    ")",
    ",",
    "==",
    "!=",
    "<",
    "<=",
    ">",
    ">=",
    "+",
    "*",
    "/",
    "=",
    "!",
    "answered",
    "contains",
    "true",
    "false",
    " ",
    "\n",
    "1.",
    "0x",
]


@settings(max_examples=500)
@given(st.lists(st.sampled_from(TOKENS), max_size=20))
def test_fuzz_parser_token_soup(tokens):
    _check_parse_result(" ".join(tokens))
    _check_parse_result("".join(tokens))
