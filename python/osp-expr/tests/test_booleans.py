"""Boolean literals ``true`` / ``false``: AST, JSON, parser, printer, evaluator, typecheck."""

import pytest
from osp_expr import (
    And,
    Answered,
    BoolLit,
    Compare,
    Not,
    Ref,
    evaluate,
    evaluate_condition,
    expr_from_json,
    expr_to_json,
    parse,
    to_text,
    typecheck,
)

TYPES = {"age": "integer", "name": "text", "pets": "multi"}


def ok(src):
    result = parse(src)
    assert result.ok, result.diagnostics
    return result.expr


def test_parse_and_print():
    assert ok("true") == BoolLit(value=True)
    assert ok("false") == BoolLit(value=False)
    assert ok("not false") == Not(arg=BoolLit(value=False))
    expr = ok("answered(age) == true and false")
    assert expr == And(
        args=(
            Compare(op="==", left=Answered(ref=Ref(id="age")), right=BoolLit(value=True)),
            BoolLit(value=False),
        )
    )
    assert to_text(expr) == "answered(age) == true and false"


def test_json_shape():
    assert expr_to_json(BoolLit(value=True)) == '{"kind":"bool","value":true}'
    assert expr_from_json('{"kind":"bool","value":false}') == BoolLit(value=False)


@pytest.mark.parametrize("bad", ['{"kind":"bool","value":1}', '{"kind":"bool","value":"true"}'])
def test_json_value_must_be_a_real_boolean(bad):
    with pytest.raises(ValueError):
        expr_from_json(bad)


def test_true_and_false_are_still_not_question_ids():
    assert not parse("answered(true)").ok
    assert not parse("contains(false, 1)").ok


@pytest.mark.parametrize(
    "src, value, condition",
    [
        ("true", True, True),
        ("false", False, False),
        ("not true", False, False),
        ("not false", True, True),
        ("true and age > 1", True, True),
        ("false or age > 1", True, True),
        ("true == true", True, True),
        ("true != false", True, True),
        ("answered(name) == false", True, True),
        ("answered(age) == true", True, True),
        ("true < false", None, False),  # ordering only for numbers and dates: mismatch, null
        ("true == 1", None, False),  # type mismatch: null (semantics §3)
        ("true + 1", None, False),  # arithmetic on non-numbers: mismatch, null
        ("ghost == true", False, False),  # §3: comparing null is false
    ],
)
def test_evaluate(src, value, condition):
    env = {"age": 5}
    assert evaluate(ok(src), env) == value
    assert evaluate_condition(ok(src), env) is condition


@pytest.mark.parametrize("src", ["true", "false", "not true", "answered(age) == false"])
def test_typecheck_boolean(src):
    assert typecheck(ok(src), TYPES) == []


@pytest.mark.parametrize(
    "src, code",
    [
        ("true + 1 > 0", "type-mismatch"),
        ("age == true", "type-mismatch"),
        ("true < false", "type-mismatch"),
    ],
)
def test_typecheck_errors(src, code):
    assert [d.code for d in typecheck(ok(src), TYPES)] == [code]
