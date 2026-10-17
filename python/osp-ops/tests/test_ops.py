"""Behaviour of individual ops, transactions and the catalogue."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from osp_ops import (
    REGISTRY,
    Draft,
    Invocation,
    apply_transaction,
    enabled,
    op_catalogue,
    openapi_components,
    run,
)
from osp_ops import patch as jp
from osp_spec import Survey, parse

BASE: dict[str, Any] = json.loads((Path(__file__).parent / "base_survey.json").read_text("utf-8"))


def base() -> dict[str, Any]:
    return copy.deepcopy(BASE)


def codes(res: Any) -> list[str]:
    return [d.code for d in res.diagnostics]


def question(survey: dict[str, Any], qid: str) -> dict[str, Any]:
    for b in survey["blocks"]:
        for page in b["pages"]:
            for q in page["items"]:
                if q["id"] == qid:
                    return q
    raise KeyError(qid)


# --- registry basics ------------------------------------------------------------------


def test_unknown_op_and_bad_params_are_diagnostics() -> None:
    assert codes(run("nope", base(), {})) == ["op.unknown"]
    assert codes(run("delete_question", base(), [1, 2])) == ["op.params"]
    res = run("delete_question", base(), {"id": "age", "surprise": 1})
    assert not res.ok and set(codes(res)) == {"op.params"}


def test_invalid_input_survey_is_rejected() -> None:
    res = run("set_title", {"specVersion": "osp-survey/0.1"}, {"title": "x"})
    assert codes(res)[0] == "op.invalid_survey"


def test_accepts_a_parsed_survey_model() -> None:
    model = Survey.model_validate(base())
    res = run("set_title", model, {"title": "From a model"})
    assert res.ok and res.survey["metadata"]["title"] == "From a model"


def test_enabled_is_a_dry_run() -> None:
    assert enabled("delete_question", base(), {"id": "why_pear"}) is True
    reason = enabled("delete_question", base(), {"id": "age"})
    assert isinstance(reason, str) and "/quotas/0/when" in reason


def test_diagnostics_are_the_validators_after_the_edit() -> None:
    res = run("set_condition", base(), {"target": "consent", "condition": "rating > 1"})
    assert res.ok
    assert "ref.forward" in codes(res)  # allowed in a draft, reported


# --- dangling references --------------------------------------------------------------


def test_delete_referenced_question_is_rejected_with_pointers_into_the_input() -> None:
    res = run("delete_question", base(), {"id": "age"})
    assert not res.ok and codes(res)[0] == "op.dangling_ref"
    ptrs = {d.pointer for d in res.diagnostics[1:]}
    assert ptrs == {
        "/variables/2/expr",
        "/quotas/0/when",
        "/blocks/0/pages/1/items/2/label/en",
        "/blocks/0/pages/1/items/2/label/de",
    }


def test_cascade_clears_optional_conditions_only() -> None:
    res = run("delete_question", base(), {"id": "fruit", "cascade": True})
    assert res.ok
    assert "showIf" not in question(res.survey, "why_pear")
    assert res.inverse is not None and res.inverse.op == "apply_patch"
    blocked = run("delete_question", base(), {"id": "age", "cascade": True})
    assert codes(blocked)[0] == "op.cascade_blocked"


def test_cascade_drops_pipes() -> None:
    res = run("delete_variable", base(), {"id": "source", "cascade": True})
    assert res.ok
    msg = res.survey["flow"][3]["else"][0]["message"]
    assert msg == {"en": "Bye ", "de": "Tschüss "}


def test_force_keeps_dangling_references_and_reports_them() -> None:
    res = run("delete_question", base(), {"id": "age", "force": True})
    assert res.ok and "ref.unknown" in codes(res)


def test_delete_block_cascade_removes_flow_nodes_and_quota_block() -> None:
    res = run("delete_block", base(), {"id": "b_extra", "cascade": True})
    assert res.ok
    rand = res.survey["flow"][3]["then"][0]
    assert [c["id"] for c in rand["children"]] == ["n_main"]
    res = run("delete_block", base(), {"id": "b_full", "cascade": True})
    assert res.ok and "block" not in res.survey["quotas"][0]["onFull"]
    assert codes(run("delete_block", base(), {"id": "b_main"}))[0] == "op.dangling_ref"


def test_delete_choice_list_cascade_inlines_choices() -> None:
    res = run("delete_choice_list", base(), {"id": "yesno", "cascade": True})
    assert res.ok
    consent = question(res.survey, "consent")
    assert "choiceList" not in consent
    assert consent["choices"] == BASE["choiceLists"][0]["choices"]


def test_delete_variable_cascade_removes_empty_assign_node() -> None:
    res = run("delete_variable", base(), {"id": "arm", "cascade": True})
    assert res.ok and "n_assign" not in json.dumps(res.survey["flow"])


def test_delete_choice_checks_code_references() -> None:
    res = run("delete_choice", base(), {"owner": "fruit", "value": 2})
    assert codes(res)[0] == "op.dangling_ref"
    res = run("delete_choice", base(), {"owner": "yesno", "value": 1})
    assert codes(res)[0] == "op.dangling_ref"  # consent == 1 via the shared list
    res = run("set_choice", base(), {"owner": "yesno", "value": 1, "new_value": 7})
    assert codes(res)[0] == "op.dangling_ref"
    assert run("set_choice", base(), {"owner": "yesno", "value": 1, "label": "Y"}).ok


def test_set_languages_guards_translations() -> None:
    assert codes(run("set_languages", base(), {"languages": ["en"]}))[0] == "op.dangling_ref"
    res = run("set_languages", base(), {"languages": ["en"], "cascade": True})
    assert res.ok and res.survey["metadata"]["title"] == {"en": "Ops test survey"}


# --- individual ops -------------------------------------------------------------------


def test_add_question_generates_ids_and_rejects_duplicates() -> None:
    res = run("add_question", base(), {"page": "p_main", "type": "single"})
    assert res.ok
    new = res.survey["blocks"][1]["pages"][0]["items"][-1]
    assert new["id"] == "q1" and new["choices"] == [{"value": 1, "label": "Option 1"}]
    dup = run("add_question", base(), {"page": "p_main", "id": "age"})
    assert codes(dup)[0] == "op.duplicate_id"


@pytest.mark.parametrize("qtype", ["matrix", "slider"])
def test_add_matrix_and_slider_questions_validate(qtype: str) -> None:
    res = run("add_question", base(), {"page": "p_main", "type": qtype, "id": "qx"})
    assert res.ok, codes(res)
    survey, diags = parse(res.survey)
    assert survey is not None and not [d for d in diags if d.severity == "error"]
    if qtype == "matrix":
        assert [r["id"] for r in question(res.survey, "qx")["rows"]] == ["r1", "r2"]
        col = run("add_choice", res.survey, {"owner": "qx", "label": "Option 2"})
        assert col.ok, codes(col)
        prop = run(
            "set_property", res.survey, {"target": "qx", "property": "required", "value": True}
        )
        assert prop.ok, codes(prop)
    else:
        prop = run("set_property", res.survey, {"target": "qx", "property": "max", "value": 10})
        assert prop.ok, codes(prop)


def test_duplicate_question_points_self_references_at_the_copy() -> None:
    res = run("duplicate_question", base(), {"id": "age"})
    assert res.ok
    copy_ = question(res.survey, "age_copy")
    assert copy_["constraint"]["left"] == {"kind": "ref", "id": "age_copy"}


def test_move_question_between_blocks_and_never_empties_a_page() -> None:
    res = run("move_question", base(), {"id": "rating", "page": "p_extra", "index": 0})
    assert res.ok
    assert [q["id"] for q in res.survey["blocks"][2]["pages"][0]["items"]] == ["rating", "when"]
    assert any(p["op"] == "remove" for p in res.patch)
    empty = run("move_question", base(), {"id": "consent", "page": "p_demo"})
    assert codes(empty)[0] == "op.not_allowed"


def test_move_within_list_is_one_patch_move() -> None:
    res = run("move_question", base(), {"id": "age", "page": "p_demo", "index": 2})
    assert res.patch == [
        {"op": "move", "from": "/blocks/0/pages/1/items/0", "path": "/blocks/0/pages/1/items/2"}
    ]


def test_set_property_is_validated_against_the_model() -> None:
    assert run("set_property", base(), {"target": "age", "property": "required", "value": True}).ok
    for prop in ("id", "type", "items", "nonsense"):
        res = run("set_property", base(), {"target": "age", "property": prop, "value": 1})
        assert codes(res)[0] == "op.not_allowed", prop
    # A field of another question type: integers have no `choices`, notes no `constraint`.
    res = run("set_property", base(), {"target": "age", "property": "choices", "value": 1})
    assert codes(res)[0] == "op.not_applicable"
    for params in ({"value": None}, {"unset": True}):
        res = run("set_property", base(), {"target": "info", "property": "constraint", **params})
        assert codes(res)[0] == "op.not_applicable", params
    res = run("set_property", base(), {"target": "age", "property": "required", "value": "yes"})
    assert codes(res)[0] == "op.invalid_result"
    res = run("set_property", base(), {"target": "age", "property": "label", "unset": True})
    assert codes(res)[0] == "op.invalid_result"


def test_set_condition_parses_text() -> None:
    res = run("set_condition", base(), {"target": "rating", "condition": "age >= 21"})
    assert res.ok
    assert question(res.survey, "rating")["showIf"] == {
        "kind": "compare",
        "op": ">=",
        "left": {"kind": "ref", "id": "age"},
        "right": {"kind": "int", "value": 21},
    }
    bad = run("set_condition", base(), {"target": "rating", "condition": "age >="})
    assert codes(bad)[0] == "op.expr_syntax" and bad.diagnostics[0].pointer == "/condition"
    req = run("set_condition", base(), {"target": "n_branch", "condition": ""})
    assert codes(req)[0] == "op.not_allowed"
    note = run("set_condition", base(), {"target": "info", "field": "constraint", "condition": "1"})
    assert codes(note)[0] == "op.not_applicable"  # notes have no constraint


@pytest.mark.parametrize("condition", [None, "", "age > 3"])
def test_set_condition_on_a_field_the_type_lacks_is_rejected(condition: object) -> None:
    """Regression (found by Hypothesis in test_guard): clearing a note's `constraint` was a
    no-op whose inverse, `set_property(unset)`, set_property then rejected, so undo failed.
    Setting and clearing now both reject up front: the model has no such field."""
    params = {"target": "info", "field": "constraint", "condition": condition}
    res = run("set_condition", base(), params)
    assert not res.ok and codes(res) == ["op.not_applicable"]
    assert "showIf" in res.diagnostics[0].message  # says what the note does have
    # The field a note does have still round-trips, set and cleared.
    shown = run("set_condition", base(), {"target": "info", "condition": "age > 3"})
    assert shown.ok and shown.inverse is not None
    undo = run(shown.inverse.op, shown.survey, shown.inverse.params)
    assert undo.ok and undo.survey == base()


def test_bulk_paste_codes() -> None:
    text = "A\n\n2\tPear\n9\tNine\nB"
    res = run("bulk_paste_choices", base(), {"owner": "fruit", "text": text})
    assert res.ok
    assert [c["value"] for c in question(res.survey, "fruit")["choices"]] == [1, 2, 9, 10]
    gone = run("bulk_paste_choices", base(), {"owner": "fruit", "text": "A\nB\tB"})
    assert codes(gone)[0] == "op.dangling_ref"  # code 2 is used by why_pear's showIf
    assert question(res.survey, "fruit")["choices"][0]["label"] == {"en": "A"}
    res = run("bulk_paste_choices", base(), {"owner": "fruit", "text": "Z", "mode": "append"})
    assert [c["value"] for c in question(res.survey, "fruit")["choices"]] == [1, 2, 3, 4]
    dup = run("bulk_paste_choices", base(), {"owner": "spare", "text": "a\tA\na\tB"})
    assert codes(dup)[0] == "op.not_allowed"
    shared = run("add_choice", base(), {"owner": "consent", "label": "x"})
    assert "shared list" in shared.diagnostics[0].message


def test_flow_node_cannot_move_into_itself() -> None:
    res = run("move_flow_node", base(), {"id": "n_branch", "parent": "n_rand"})
    assert codes(res)[0] == "op.not_allowed"


def test_replace_survey_requires_structural_validity_but_repairs_broken_drafts() -> None:
    res = run("replace_survey", base(), {"survey": {"id": "x"}})
    assert codes(res)[0] == "op.invalid_result"
    fixed = run("replace_survey", {"broken": True}, {"survey": base()})
    assert fixed.ok and fixed.inverse is not None


# --- transactions ---------------------------------------------------------------------


def test_transaction_is_all_or_nothing() -> None:
    draft = Draft(survey=base(), revision=4)
    ops = [
        {"op": "set_title", "params": {"title": "T"}},
        {"op": "delete_question", "params": {"id": "age"}},  # rejected: referenced
    ]
    res = apply_transaction(draft, ops, 4)
    assert res.status == "rejected" and res.failed_index == 1
    assert res.draft is draft and jp.same(draft.survey, BASE)


def test_transaction_conflict_on_stale_revision() -> None:
    res = apply_transaction(Draft(survey=base(), revision=4), [], 3)
    assert res.status == "conflict" and codes(res) == ["op.conflict"]


def test_transaction_undo_and_redo() -> None:
    draft = Draft(survey=base(), revision=0)
    ops = [
        Invocation(op="add_block", params={"id": "b_new"}),
        Invocation(op="insert_flow_node", params={"node": {"type": "block", "block": "b_new"}}),
        Invocation(op="move_question", params={"id": "rating", "page": "page1"}),
        Invocation(op="delete_block", params={"id": "b_extra", "cascade": True}),
    ]
    done = apply_transaction(draft, ops, 0)
    assert done.ok and done.draft.revision == 1, done.diagnostics
    assert jp.same(jp.apply(BASE, done.patch), done.draft.survey)
    undone = apply_transaction(done.draft, done.inverse, 1)
    assert undone.ok and jp.same(undone.draft.survey, BASE) and undone.draft.revision == 2
    redone = apply_transaction(undone.draft, undone.inverse, 2)
    assert redone.ok and jp.same(redone.draft.survey, done.draft.survey)


def test_empty_transaction_keeps_revision() -> None:
    res = apply_transaction(Draft(survey=base(), revision=2), [], 2)
    assert res.ok and res.draft.revision == 2


@pytest.mark.parametrize("ops", [None, "x", [1], [{"op": 1}], [{"op": "set_title"}]])
def test_transaction_hostile_ops(ops: Any) -> None:
    res = apply_transaction(Draft(survey=base()), ops, 0)
    assert res.status == "rejected" and "op.internal" not in codes(res)


# --- catalogue ------------------------------------------------------------------------


def test_catalogue_lists_every_op_with_a_schema() -> None:
    cat = op_catalogue()
    assert [c["id"] for c in cat] == sorted(REGISTRY)
    for c in cat:
        assert c["label"] and c["description"] and c["paramsSchema"]["type"] == "object"


def test_openapi_components_refs_resolve() -> None:
    schemas = openapi_components()
    refs: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("$ref"), str):
                refs.append(node["$ref"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schemas)
    prefix = "#/components/schemas/"
    assert all(r.startswith(prefix) and r[len(prefix) :] in schemas for r in refs), refs
    assert "SetPropertyParams" in schemas and "Invocation" in schemas
    json.dumps(schemas)  # serialisable


# --- JSON Patch -----------------------------------------------------------------------


def test_patch_diff_and_apply() -> None:
    a = {"x": [1, 2, 3, 4], "y": {"k": 1}, "z": True}
    b = {"x": [2, 3, 4, 1], "y": {"k": 1.0}, "w": None}
    p = jp.diff(a, b)
    assert jp.same(jp.apply(a, p), b)
    assert {"op": "move", "from": "/x/0", "path": "/x/3"} in p
    assert jp.apply(a, [{"op": "replace", "path": "", "value": 5}]) == 5
    bad_patches: list[Any] = [
        [{"op": "remove", "path": "/nope"}],
        [{"op": "add", "path": "/x/9", "value": 0}],
        [{"op": "move", "from": "/y", "path": "/y/k"}],
        [{"op": "zap", "path": ""}],
        "x",
    ]
    for bad in bad_patches:
        with pytest.raises(jp.PatchError):
            jp.apply(a, bad)
    assert parse(jp.apply(BASE, jp.diff(BASE, base())))[0] is not None


def test_set_theme_stores_a_full_copy_and_unsets_cleanly() -> None:
    from osp_spec.theme import PRESETS

    warm = PRESETS["warm"].model_dump(mode="json", by_alias=True)
    res = run("set_theme", base(), {"theme": {"colours": warm["colours"]}})
    assert res.ok, res.diagnostics
    stored = res.survey["settings"]["theme"]
    assert stored["colours"] == warm["colours"] and stored["themeVersion"] == "osp-theme/0.1"
    back = run("set_theme", res.survey, {"theme": None})
    assert back.ok and back.survey == base()


def test_set_theme_rejects_a_bad_theme_with_a_pointer() -> None:
    res = run("set_theme", base(), {"theme": {"colours": {"light": {}}}})
    assert not res.ok
    assert res.diagnostics[0].code == "op.invalid_result"
    assert res.diagnostics[0].pointer.startswith("/settings/theme/colours")
