"""Hypothesis: the validator never raises and never hits its own safety net."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from osp_spec import CODES, Diagnostic, validate

VALID = [
    json.loads(p.read_text(encoding="utf-8"))["survey"]
    for p in sorted((Path(__file__).parent / "cases" / "valid").glob("*.json"))
]
KEYS = [
    "specVersion", "id", "type", "kind", "var", "label", "items", "pages", "blocks", "flow",
    "then", "else", "if", "children", "pick", "choices", "choiceList", "value", "variables",
    "block", "quota", "quotas", "metadata", "languages", "showIf", "constraint", "levels",
    "expr", "name", "en", "onFull", "when", "limit", "op", "left", "right", "args", "arg",
    "ref",
]  # fmt: skip
TAGS = [
    "osp-survey/0.1", "integer", "single", "note", "block", "branch", "${q1}", "q1", "age",
    "ref", "int", "decimal", "text", "null", "compare", "arith", "and", "or", "not",
    "answered", "contains", "==", ">", "+",
]  # fmt: skip
SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=True, allow_infinity=True),
    st.text(max_size=12),
    st.sampled_from(KEYS + TAGS),
)
JSON = st.recursive(
    SCALARS,
    lambda inner: st.one_of(
        st.lists(inner, max_size=5),
        st.dictionaries(st.one_of(st.sampled_from(KEYS), st.text(max_size=8)), inner, max_size=6),
    ),
    max_leaves=40,
)


def _check(data: Any) -> None:
    out = validate(data)
    assert isinstance(out, list)
    for d in out:
        assert isinstance(d, Diagnostic)
        assert d.code in CODES and d.code != "internal.error", d
        assert d.pointer == "" or d.pointer.startswith("/")


@settings(max_examples=400, deadline=None)
@given(JSON)
def test_arbitrary_json(data: Any) -> None:
    _check(data)


@st.composite
def mutated_survey(draw: st.DrawFn) -> Any:
    """A valid fixture with one subtree replaced by random JSON."""
    doc = json.loads(json.dumps(draw(st.sampled_from(VALID))))
    node: Any = doc
    for _ in range(draw(st.integers(0, 8))):
        if isinstance(node, dict) and node:
            key = draw(st.sampled_from(sorted(node)))
            if draw(st.booleans()) or not isinstance(node[key], (dict, list)):
                node[key] = draw(JSON)
                return doc
            node = node[key]
        elif isinstance(node, list) and node:
            i = draw(st.integers(0, len(node) - 1))
            if draw(st.booleans()) or not isinstance(node[i], (dict, list)):
                node[i] = draw(JSON)
                return doc
            node = node[i]
        else:
            break
    return doc


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(mutated_survey())
def test_mutated_valid_surveys(data: Any) -> None:
    _check(data)


def test_deep_nesting_does_not_crash() -> None:
    deep: Any = {"kind": "ref", "id": "consent"}
    for _ in range(5000):
        deep = {"kind": "not", "arg": deep}
    doc = json.loads(json.dumps(VALID[0]))
    doc["flow"][1]["if"] = deep
    _check(doc)
