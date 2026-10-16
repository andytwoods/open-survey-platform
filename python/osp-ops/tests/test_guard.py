"""Completeness guard (review.md §3.3): every registered op has
1. an inverse round-trip test: run, then run the inverse, gives back the original survey
   (and the patch replays the edit, and the inverse's inverse redoes it), and
2. a Hypothesis hostile-params fuzz test: never raises, never hits `op.internal`, and
   whenever it succeeds the same round-trip properties hold.

Adding an op without adding it to EXAMPLES fails `test_every_op_has_examples`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st
from osp_ops import REGISTRY, OpResult, run
from osp_ops import patch as jp
from osp_spec import Diagnostic, parse

BASE: dict[str, Any] = json.loads((Path(__file__).parent / "base_survey.json").read_text("utf-8"))

MINIMAL = {
    "specVersion": "osp-survey/0.1",
    "id": "tiny",
    "metadata": {"title": "Tiny", "languages": ["en"]},
    "blocks": [{"id": "b", "pages": [{"id": "p", "items": [{"id": "q", "type": "text",
                                                            "label": "Q"}]}]}],
    "flow": [{"type": "block", "id": "n", "block": "b"}],
}  # fmt: skip

AGE_LT_120 = {
    "kind": "compare",
    "op": "<",
    "left": {"kind": "ref", "id": "age"},
    "right": {"kind": "int", "value": 120},
}

# Params that must succeed on BASE, per op. One test per entry.
EXAMPLES: dict[str, list[dict[str, Any]]] = {
    "add_question": [
        {"page": "p_demo"},
        {"page": "p_main", "type": "single", "index": 0, "id": "newq", "label": "Hi"},
        {"page": "p_extra", "question": {"type": "note", "label": "N"}},
    ],
    "delete_question": [
        {"id": "why_pear"},
        {"id": "info"},
        {"id": "fruit", "cascade": True},
        {"id": "age", "force": True},
    ],
    "duplicate_question": [{"id": "age"}, {"id": "fruit", "new_id": "fruit2"}],
    "move_question": [
        {"id": "age", "page": "p_demo", "index": 2},
        {"id": "rating", "page": "p_consent", "index": 0},
        {"id": "why_pear", "page": "p_extra"},
    ],
    "set_property": [
        {"target": "age", "property": "required", "value": True},
        {"target": "age", "property": "help", "value": {"en": "Years", "de": "Jahre"}},
        {"target": "consent", "property": "required", "unset": True},
        {"target": "/settings", "property": "backNavigation", "value": False},
        {"target": "/metadata", "property": "license", "value": "CC0-1.0"},
        {"target": "b_intro", "property": "title", "value": "X"},
        {"target": "n_rand", "property": "pick", "value": 1},
        {"target": "spare", "property": "choices", "value": [{"value": "c", "label": "C"}]},
    ],
    "add_page": [
        {"block": "b_main"},
        {"block": "b_intro", "index": 0, "id": "p_new", "question_type": "single"},
    ],
    "delete_page": [{"id": "p_consent", "force": True}],
    "rename_page": [{"id": "p_main", "new_id": "p_main2"}],
    "move_page": [
        {"id": "p_demo", "block": "b_main", "index": 0},
        {"id": "p_demo", "block": "b_intro", "index": 0},
    ],
    "add_block": [{}, {"id": "b_new", "title": "New", "index": 0}],
    "delete_block": [{"id": "b_extra", "cascade": True}, {"id": "b_full", "cascade": True}],
    "rename_block": [{"id": "b_main", "title": "Main"}, {"id": "b_intro", "title": None}],
    "move_block": [{"id": "b_full", "index": 0}],
    "add_choice": [
        {"owner": "fruit", "label": "Fig"},
        {"owner": "yesno", "label": {"en": "Maybe", "de": "Vielleicht"}, "value": 9, "index": 0},
    ],
    "delete_choice": [
        {"owner": "fruit", "value": 3},
        {"owner": "fruit", "value": 2, "cascade": True},
        {"owner": "spare", "value": "a"},
    ],
    "move_choice": [{"owner": "fruit", "value": 1, "index": 2}],
    "set_choice": [
        {"owner": "fruit", "value": 3, "label": "Damson"},
        {"owner": "spare", "value": "a", "new_value": "z"},
    ],
    "bulk_paste_choices": [
        {"owner": "spare", "text": "One\nTwo\n\nThree"},
        {"owner": "fruit", "text": "Kiwi\nx\tMango", "mode": "append"},
    ],
    "create_choice_list": [{}, {"id": "agree", "choices": [{"value": 1, "label": "A"}]}],
    "delete_choice_list": [{"id": "spare"}, {"id": "yesno", "cascade": True}],
    "set_condition": [
        {"target": "rating", "condition": "age >= 21 and answered(consent)"},
        {"target": "why_pear", "condition": None},
        {"target": "n_branch", "condition": "consent == 0"},
        {"target": "age", "field": "constraint", "condition": AGE_LT_120},
        {"target": "adults", "condition": "age > 30"},
        {"target": "age_next", "condition": "age + 2"},
        {"target": "when", "condition": "rating > 2.5"},
    ],
    "insert_flow_node": [
        {"node": {"type": "end"}},
        {"node": {"type": "end", "id": "e_early"}, "parent": "n_branch", "arm": "else"},
        {"node": {"type": "randomiser", "children": [{"type": "end", "id": "e9"}]}, "index": 0},
    ],
    "delete_flow_node": [{"id": "n_rand"}, {"id": "n_assign"}, {"id": "n_end_no"}],
    "move_flow_node": [
        {"id": "n_quota", "index": 0},
        {"id": "n_main", "parent": "n_branch", "arm": "else"},
        {"id": "n_assign", "parent": "n_rand", "index": 0},
    ],
    "add_variable": [
        {"variable": {"kind": "embedded", "param": "pid"}},
        {"variable": {"id": "cond2", "kind": "assigned", "levels": [1, 2]}, "index": 0},
    ],
    "delete_variable": [
        {"id": "source", "cascade": True},
        {"id": "arm", "cascade": True},
        {"id": "age_next"},
    ],
    "set_title": [{"title": "Plain"}, {"title": {"en": "T", "de": "T"}}],
    "set_languages": [
        {"languages": ["en", "de", "fr"], "default_language": "en"},
        {"languages": ["en"], "cascade": True},
        {"languages": ["de", "en"]},
    ],
    "replace_survey": [{"survey": MINIMAL}],
    "apply_patch": [{"patch": [{"op": "replace", "path": "/metadata/title", "value": "P"}]}],
}


def check_result(op_id: str, before: Any, params: Any, res: OpResult) -> None:
    """Properties every op result has, successful or not."""
    assert isinstance(res, OpResult)
    for d in res.diagnostics:
        assert isinstance(d, Diagnostic)
        assert d.code != "op.internal", (op_id, params, d)
        assert d.pointer == "" or d.pointer.startswith("/"), d
    if not res.ok:
        assert res.diagnostics, "a rejection always says why"
        return
    assert parse(res.survey)[0] is not None, "ops only produce structurally valid surveys"
    assert jp.same(jp.apply(before, res.patch), res.survey), "patch replays the edit"
    assert res.inverse is not None
    undo = run(res.inverse.op, res.survey, res.inverse.params)
    assert undo.ok, (op_id, params, res.inverse, undo.diagnostics)
    assert jp.same(undo.survey, before), (op_id, params, "inverse must restore the original")
    assert undo.inverse is not None
    redo = run(undo.inverse.op, undo.survey, undo.inverse.params)
    assert redo.ok and jp.same(redo.survey, res.survey), (op_id, params, "redo")


def test_every_op_has_examples() -> None:
    assert set(EXAMPLES) == set(REGISTRY), "add EXAMPLES for new ops (and remove stale ones)"


@pytest.mark.parametrize(
    ("op_id", "params"),
    [(op_id, p) for op_id, ps in sorted(EXAMPLES.items()) for p in ps],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_inverse_round_trip(op_id: str, params: dict[str, Any]) -> None:
    before = copy.deepcopy(BASE)
    res = run(op_id, before, params)
    assert res.ok, [d.message for d in res.diagnostics]
    assert jp.same(before, BASE), "ops never mutate their input"
    assert res.patch, "every example changes something"
    check_result(op_id, BASE, params, res)


# --- hostile params -------------------------------------------------------------------

IDS = sorted(
    {
        "age", "fruit", "consent", "why_pear", "info", "rating", "when", "sorry", "p_demo",
        "p_main", "p_consent", "p_extra", "b_intro", "b_main", "b_extra", "b_full", "yesno",
        "spare", "source", "arm", "age_next", "adults", "n_intro", "n_quota", "n_assign",
        "n_branch", "n_rand", "n_main", "n_extra", "n_end_no", "srv_ops", "/metadata",
        "/settings", "nope", "and", "_x", "id", "q1",
    }
)  # fmt: skip
WORDS = [
    "then", "else", "children", "showIf", "constraint", "if", "when", "expr", "label",
    "required", "choices", "choiceList", "title", "type", "kind", "items", "pages",
    "single", "multi", "note", "text", "end", "block", "branch", "replace", "append",
    "age > 3", "answered(", "${age}", "a\tb\n1\tc", "", " ", "\x00", "é",
]  # fmt: skip
SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-3, max_value=6),
    st.integers(),
    st.floats(allow_nan=True, allow_infinity=True),
    st.sampled_from(IDS + WORDS),
    st.text(max_size=10),
)
JSON = st.recursive(
    SCALARS,
    lambda inner: st.one_of(
        st.lists(inner, max_size=4),
        st.dictionaries(st.sampled_from(WORDS + ["op", "path", "value", "id"]), inner, max_size=4),
    ),
    max_leaves=20,
)


def _seen_values(field: str) -> list[Any]:
    """Values any example uses for a field of this name (plausible, so fuzzing gets past
    the params schema and into the ops themselves)."""
    out: list[Any] = []
    for ps in EXAMPLES.values():
        for p in ps:
            if field in p and not any(jp.same(p[field], v) for v in out):
                out.append(p[field])
    return out


def _value(field: str, hostile: bool) -> st.SearchStrategy[Any]:
    seen = _seen_values(field)
    plausible = [st.sampled_from(seen)] if seen else []
    near = [st.sampled_from(IDS), st.integers(min_value=-1, max_value=6), st.booleans()]
    if not hostile:
        return st.one_of(*plausible, *plausible, *near)
    return st.one_of(*plausible, *near, st.none(), JSON)


def params_strategy(op_id: str, *, hostile: bool = True) -> st.SearchStrategy[Any]:
    fields = list(REGISTRY[op_id].params.model_fields)

    def fill(keys: list[str]) -> st.SearchStrategy[dict[str, Any]]:
        return st.fixed_dictionaries({k: _value(k, hostile) for k in keys})

    mutated = st.tuples(
        st.sampled_from(EXAMPLES[op_id]),
        st.lists(st.sampled_from(fields), unique=True, max_size=2).flatmap(fill),
        st.lists(st.sampled_from(fields), max_size=1),
    ).map(lambda t: {k: v for k, v in {**t[0], **t[1]}.items() if k not in t[2]})
    if not hostile:
        return mutated
    extra = [*fields, "extra"]
    random_dict = st.lists(st.sampled_from(extra), unique=True, max_size=6).flatmap(fill)
    return st.one_of(random_dict, mutated, JSON)


FAST = 60  # per op, every `make check`
NIGHTLY = 1500  # per op, `pytest -m nightly` (minutes, not seconds)


def near_miss(op_id: str, data: st.DataObject) -> None:
    """Examples with one or two fields swapped for other plausible values: mostly valid
    params, so this exercises the ops' own checks and the round trip."""
    params = data.draw(params_strategy(op_id, hostile=False))
    res = run(op_id, copy.deepcopy(BASE), params)
    event("ok" if res.ok else res.diagnostics[0].code)
    check_result(op_id, BASE, params, res)


def hostile(op_id: str, data: st.DataObject) -> None:
    params = data.draw(params_strategy(op_id))
    before = copy.deepcopy(BASE)
    res = run(op_id, before, params)
    event("ok" if res.ok else res.diagnostics[0].code)
    assert jp.same(before, BASE), "ops never mutate their input"
    check_result(op_id, BASE, params, res)


# Written out (not made by a factory) so each test keeps its own Hypothesis database key.
OPS = pytest.mark.parametrize("op_id", sorted(REGISTRY))
SLOW_OK = [HealthCheck.too_slow]


@OPS
@settings(max_examples=FAST, deadline=None, suppress_health_check=SLOW_OK)
@given(data=st.data())
def test_near_miss_params(op_id: str, data: st.DataObject) -> None:
    near_miss(op_id, data)


@OPS
@settings(max_examples=FAST, deadline=None, suppress_health_check=SLOW_OK)
@given(data=st.data())
def test_hostile_params(op_id: str, data: st.DataObject) -> None:
    hostile(op_id, data)


@pytest.mark.nightly
@OPS
@settings(max_examples=NIGHTLY, deadline=None, suppress_health_check=SLOW_OK)
@given(data=st.data())
def test_near_miss_params_nightly(op_id: str, data: st.DataObject) -> None:
    near_miss(op_id, data)


@pytest.mark.nightly
@OPS
@settings(max_examples=NIGHTLY, deadline=None, suppress_health_check=SLOW_OK)
@given(data=st.data())
def test_hostile_params_nightly(op_id: str, data: st.DataObject) -> None:
    hostile(op_id, data)


@pytest.mark.parametrize("op_id", sorted(REGISTRY))
@settings(max_examples=15, deadline=None)
@given(survey=JSON)
def test_hostile_survey(op_id: str, survey: Any) -> None:
    res = run(op_id, survey, EXAMPLES[op_id][0])
    for d in res.diagnostics:
        assert d.code != "op.internal", d
    if res.ok:  # only whole-document ops can accept a broken input
        assert REGISTRY[op_id].whole_document
        assert parse(res.survey)[0] is not None
