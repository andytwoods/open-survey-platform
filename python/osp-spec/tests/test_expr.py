"""Condition fields are C1's AST (`osp_expr.ast.Expr`)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from osp_expr.ast import Compare, Ref
from osp_spec import parse, validate
from osp_spec.expr import references

WORKED = json.loads(
    (Path(__file__).parent / "cases" / "valid" / "v01_worked_example.json").read_text("utf-8")
)["survey"]


def test_condition_fields_parse_to_the_ast() -> None:
    survey, diagnostics = parse(WORKED)
    assert diagnostics == [] and survey is not None
    gate = survey.flow[1]
    assert isinstance(gate.if_, Compare)
    assert isinstance(gate.if_.left, Ref) and gate.if_.left.id == "consent"


def test_references_walk_the_whole_tree() -> None:
    survey, _ = parse(WORKED)
    assert survey is not None
    age = survey.blocks[1].pages[0].items[0]
    assert references(age.constraint) == ["age"]


def _with_condition(cond: dict) -> dict:
    s = copy.deepcopy(WORKED)
    s["flow"][1]["if"] = cond
    return s


def test_typecheck_runs_when_osp_expr_static_is_available() -> None:
    """Activates once C1's `osp_expr.static` is on the branch (it lands after the AST)."""
    pytest.importorskip("osp_expr.static")
    # consent is a single-choice code; `consent + 1` is a number, not a condition.
    cond = {
        "kind": "arith",
        "op": "+",
        "left": {"kind": "ref", "id": "consent"},
        "right": {"kind": "int", "value": 1},
    }
    got = [(d.code, d.pointer) for d in validate(_with_condition(cond))]
    assert got and all(code == "expr.type" for code, _ in got)
    assert all(ptr.startswith("/flow/1/if") for _, ptr in got)
    # Unknown refs are reported once, by osp-spec, not again by the type checker.
    unknown = {"kind": "answered", "ref": {"kind": "ref", "id": "ghost"}}
    assert [(d.code, d.pointer) for d in validate(_with_condition(unknown))] == [
        ("ref.unknown", "/flow/1/if")
    ]
