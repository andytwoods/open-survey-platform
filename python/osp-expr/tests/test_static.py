"""references() and typecheck()."""

import pytest
from osp_expr import parse, references, typecheck

TYPES = {
    "age": "integer",
    "score": "decimal",
    "name": "text",
    "consent": "single",
    "pets": "multi",
    "dob": "date",
}


def expr(src):
    result = parse(src)
    assert result.ok, result.diagnostics
    return result.expr


def test_references_in_first_occurrence_order():
    e = expr('age > 5 and (contains(pets, "dog") or answered(name)) and age < score + age')
    assert references(e) == ("age", "pets", "name", "score")
    assert references(expr("1 + 2 == 3")) == ()


@pytest.mark.parametrize(
    "src",
    [
        "age >= 18 and age <= 120",
        "score / 2 > age",
        'name == "Ann"',
        "consent == 0",
        'consent == "yes"',
        "consent >= 4",
        'contains(pets, "dog")',
        "contains(pets, 3)",
        "dob < dob",
        "answered(dob) and not answered(name)",
        "consent + age > 3",
    ],
)
def test_well_typed(src):
    assert typecheck(expr(src), TYPES) == []


@pytest.mark.parametrize(
    "src, code, path",
    [
        ("name > 5", "type-mismatch", "/"),
        ("name == 5", "type-mismatch", "/"),
        ("dob == age", "type-mismatch", "/"),
        ('name < "b"', "type-mismatch", "/"),
        ('contains(name, "a")', "contains-non-multi", "/ref"),
        ("contains(pets, dob)", "type-mismatch", "/value"),
        ("name + 1 > 2", "type-mismatch", "/left/left"),
        ("pets == 1", "type-mismatch", "/"),
        ("age > 1 and age", "not-boolean", "/args/1"),
        ("not age", "not-boolean", "/arg"),
        ("age + 1", "not-boolean", "/"),
        ("ghost > 1", "unknown-question", "/left"),
        ("answered(ghost)", "unknown-question", "/ref"),
        ("age == null", "null-comparison", "/"),
        ("age + null > 1", "null-arithmetic", "/left"),
    ],
)
def test_ill_typed(src, code, path):
    diags = typecheck(expr(src), TYPES)
    assert [(d.code, d.path) for d in diags] == [(code, path)], diags


def test_warnings_vs_errors():
    (diag,) = typecheck(expr("age == null"), TYPES)
    assert diag.severity == "warning"
    (diag,) = typecheck(expr("name > 5"), TYPES)
    assert diag.severity == "error"


def test_value_expressions_need_not_be_conditions():
    assert typecheck(expr("age + 1"), TYPES, condition=False) == []
