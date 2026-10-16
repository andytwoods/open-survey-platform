"""Semantics decisions batch 1 (planning/decisions-semantics-1.md) in osp-expr:
``if()``, runtime diagnostics, constant zero divisors, the shared trim set and canonical
decimals (both checked against contract/vectors/, which web/engine reads too)."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from osp_expr import (
    TRIM_CHARS,
    Diagnostic,
    If,
    Ref,
    TextLit,
    canonical_decimal,
    evaluate,
    evaluate_condition,
    expr_from_json,
    expr_to_json,
    parse,
    to_text,
    trim,
    typecheck,
)
from osp_expr.values import TRIM_CODE_POINTS

VECTORS = Path(__file__).resolve().parents[3] / "contract" / "vectors"
TYPES = {"age": "integer", "name": "text", "pets": "multi", "band": "single", "d": "decimal"}


def ok(src: str):
    result = parse(src)
    assert result.ok, result.diagnostics
    return result.expr


# --- if() ------------------------------------------------------------------------------


def test_if_parses_prints_and_round_trips_json():
    expr = ok('if(age < 40, "18-39", "40+")')
    assert isinstance(expr, If)
    assert expr.then == TextLit(value="18-39")
    assert to_text(expr) == 'if(age < 40, "18-39", "40+")'
    assert ok(to_text(expr)) == expr
    text = expr_to_json(expr)
    assert '"else":' in text and '"cond":' in text
    assert expr_from_json(text) == expr


def test_if_nests_and_works_inside_operators():
    expr = ok("if(age > 1, if(age > 2, 3, 2), 1) + 1 > 3")
    assert evaluate_condition(expr, {"age": 5}) is True
    assert evaluate(ok("if(answered(age), age, 0)"), {}) == 0


@pytest.mark.parametrize(
    "src, diag",
    [
        ("if(age > 1, 2)", "expected"),
        ("if(age > 1, 2, 3, 4)", "expected"),
        ("if()", "expected"),
    ],
)
def test_if_arity(src, diag):
    result = parse(src)
    assert not result.ok and result.diagnostics[0].code == diag


def test_if_is_lazy():
    diags: list[Diagnostic] = []
    assert evaluate(ok("if(age > 1, 1, age / 0)"), {"age": 5}, diags) == 1
    assert diags == []  # the else branch was never evaluated


def test_if_typecheck():
    assert typecheck(ok('if(age < 40, "young", "old")'), TYPES, condition=False) == []
    assert typecheck(ok("if(age < 40, null, 1)"), TYPES, condition=False) == []
    codes = [d.code for d in typecheck(ok('if(age < 40, 1, "old")'), TYPES, condition=False)]
    assert codes == ["type-mismatch"]
    codes = [d.code for d in typecheck(ok("if(age, 1, 2)"), TYPES, condition=False)]
    assert codes == ["not-boolean"]
    assert [d.code for d in typecheck(ok("if(age < 1, 1, 2)"), TYPES)] == ["not-boolean"]
    assert typecheck(ok("if(age < 1, true, answered(name))"), TYPES) == []


# --- runtime diagnostics -----------------------------------------------------------------


@pytest.mark.parametrize(
    "src, env, value, codes",
    [
        ("age / 0", {"age": 1}, None, ["division-by-zero"]),
        ("age / zero", {"age": 1, "zero": 0}, None, ["division-by-zero"]),
        ('name < "b"', {"name": "a"}, None, ["type-mismatch"]),
        ("name + 1", {"name": "a"}, None, ["type-mismatch"]),
        ("contains(name, 1)", {"name": "a"}, None, ["type-mismatch"]),
        ("not age", {"age": 1}, True, ["type-mismatch"]),
        ('d == "2.5"', {"d": Decimal("2.5")}, None, ["type-mismatch"]),
        ('band == "1"', {"band": 1}, True, []),  # C2-8: codes compare as text
        ("age + 1", {}, None, []),  # null is not a mismatch
        ('contains(pets, "a")', {}, False, []),
    ],
)
def test_runtime_diagnostics(src, env, value, codes):
    diags: list[Diagnostic] = []
    assert evaluate(ok(src), env, diags) == value
    assert [d.code for d in diags] == codes
    assert all(d.severity == "warning" and d.path for d in diags)


def test_condition_on_a_number_is_a_mismatch():
    diags: list[Diagnostic] = []
    assert evaluate_condition(ok("age + 1"), {"age": 1}, diags) is False
    assert [d.code for d in diags] == ["type-mismatch"]


def test_no_diagnostics_list_means_no_collection():
    assert evaluate(ok("age / 0"), {"age": 1}) is None


@pytest.mark.parametrize("src", ["age / 0", "age / 0.0", "(age + 1) / 0.000"])
def test_constant_zero_divisor_blocks_publishing(src):
    assert "division-by-zero" in [d.code for d in typecheck(ok(src), TYPES, condition=False)]


def test_non_constant_divisor_is_fine():
    assert typecheck(ok("age / (age - 1)"), TYPES, condition=False) == []


# --- shared vectors ----------------------------------------------------------------------


def _vectors(name: str) -> dict:
    return json.loads((VECTORS / name).read_text())


def test_trim_set_matches_the_shared_vectors():
    doc = _vectors("trim.json")
    assert list(TRIM_CODE_POINTS) == doc["trimmed"]
    assert set(TRIM_CHARS) == {chr(c) for c in doc["trimmed"]}
    assert 0x200B in doc["notTrimmed"] and not set(doc["notTrimmed"]) & set(doc["trimmed"])
    assert len(doc["cases"]) > 100
    for raw, want in doc["cases"]:
        assert trim(raw) == want, raw


def test_trimming_keeps_inner_text_and_never_normalises():
    composed, decomposed = "caf\u00e9", "cafe\u0301"
    assert trim(" " + decomposed + "\ufeff") == decomposed != composed
    assert evaluate(ok("t == u"), {"t": decomposed, "u": composed}) is False
    assert evaluate(ok("answered(t)"), {"t": "\u3000\u00a0"}) is False
    assert evaluate(ok("answered(t)"), {"t": "\u200b"}) is True


def test_canonical_decimals_match_the_shared_vectors():
    doc = _vectors("decimal.json")
    assert doc["maxSignificantDigits"] == 28
    for raw, want in doc["cases"]:
        assert canonical_decimal(raw) == want, raw


@pytest.mark.parametrize(
    "value, want",
    [(Decimal("5.0"), "5"), (Decimal("1E+2"), "100"), (7, "7"), (True, None), (1.5, None)],
)
def test_canonical_decimal_of_numbers(value, want):
    assert canonical_decimal(value) == want


def test_ref_id_still_checked():
    with pytest.raises(ValueError):
        If(cond=Ref(id="if x"), then=TextLit(value="a"), else_=TextLit(value="b"))
