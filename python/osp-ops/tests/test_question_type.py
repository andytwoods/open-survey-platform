"""`change_question_type`: every conversion pair, what carries over, undo, and the
reference check (rejected unless `force`)."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from osp_ops import patch as jp
from osp_ops import run
from osp_ops.question_ops import DEFAULT_CHOICES, DEFAULT_ROWS
from osp_spec import parse

TYPES = ["integer", "decimal", "text", "single", "multi", "date", "matrix", "slider", "note"]
LABEL = {"en": "The question", "de": "Die Frage"}
HELP = {"en": "Some help", "de": "Etwas Hilfe"}
SHOW_IF = {
    "kind": "compare",
    "op": "==",
    "left": {"kind": "ref", "id": "gate"},
    "right": {"kind": "int", "value": 1},
}
CHOICES = [{"value": 1, "label": {"en": "One", "de": "Eins"}}, {"value": 2, "label": "Two"}]


def ref(qid: str) -> dict[str, Any]:
    return {"kind": "ref", "id": qid}


def example(qtype: str) -> dict[str, Any]:
    """A fully dressed question of `qtype`, id `q`."""
    q: dict[str, Any] = {"id": "q", "type": qtype, "label": LABEL, "help": HELP, "showIf": SHOW_IF}
    if qtype != "note":
        q["name"] = "q_var"
        q["required"] = True
    if qtype in ("integer", "decimal", "text", "single", "multi", "date"):
        q["constraint"] = {"kind": "answered", "ref": ref("q")}
        q["constraintMessage"] = "Nope"
    if qtype == "integer":
        q.update(min=1, max=10)
    if qtype == "decimal":
        q.update(min="0.5", max=10)
    if qtype == "text":
        q["multiline"] = True
    if qtype in ("single", "multi"):
        q.update(choices=copy.deepcopy(CHOICES), choiceOrder="shuffle")
    if qtype == "matrix":
        rows = [{"id": "a", "label": "A", "required": False}]
        q.update(choices=copy.deepcopy(CHOICES), rows=rows)
    if qtype == "slider":
        q.update(valueType="integer", min=0, max=10, step=2, minLabel="Low", maxLabel="High")
    return q


def survey(*items: dict[str, Any], later: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    yes = [{"value": 1, "label": "Y"}]
    gate = {"id": "gate", "type": "single", "label": "Gate", "choices": yes}
    pages = [{"id": "p1", "items": [gate, *items]}]
    if later:
        pages.append({"id": "p2", "items": later})
    return {
        "specVersion": "osp-survey/0.1",
        "id": "s",
        "metadata": {"title": "T", "languages": ["en", "de"], "defaultLanguage": "en"},
        "choiceLists": [{"id": "shared", "choices": [{"value": "x", "label": "X"}]}],
        "blocks": [{"id": "b", "pages": pages}],
        "flow": [{"type": "block", "id": "n", "block": "b"}],
    }


def q_of(s: dict[str, Any], qid: str = "q") -> dict[str, Any]:
    for b in s["blocks"]:
        for page in b["pages"]:
            for q in page["items"]:
                if q["id"] == qid:
                    return q
    raise KeyError(qid)


def change(s: dict[str, Any], qtype: str, **extra: Any) -> Any:
    return run("change_question_type", s, {"id": "q", "type": qtype, **extra})


def round_trips(before: dict[str, Any], res: Any) -> None:
    assert res.ok, [d.message for d in res.diagnostics]
    assert parse(res.survey)[0] is not None
    assert jp.same(jp.apply(before, res.patch), res.survey)
    undo = run(res.inverse.op, res.survey, res.inverse.params)
    assert undo.ok and jp.same(undo.survey, before), "undo restores the exact old question"
    redo = run(undo.inverse.op, undo.survey, undo.inverse.params)
    assert redo.ok and jp.same(redo.survey, res.survey), "redo"


# --- every pair -----------------------------------------------------------------------

PAIRS = [(a, b) for a in TYPES for b in TYPES if a != b]


@pytest.mark.parametrize(("old", "new"), PAIRS)
def test_every_pair_converts_keeps_identity_and_undoes(old: str, new: str) -> None:
    before = survey(example(old))
    res = change(copy.deepcopy(before), new)
    round_trips(before, res)
    q = q_of(res.survey)
    assert q["type"] == new and q["id"] == "q"
    assert q["label"] == LABEL and q["help"] == HELP and q["showIf"] == SHOW_IF
    if new == "note":
        assert not {"name", "required", "constraint", "constraintMessage"} & set(q)
    elif old != "note":
        assert q["name"] == "q_var" and q["required"] is True
    if new in ("single", "multi", "matrix"):
        assert "choices" in q or "choiceList" in q
    else:
        assert not {"choices", "choiceList", "choiceOrder", "rows"} & set(q)
    if new != "text":
        assert "multiline" not in q
    if new != "slider":
        assert not {"step", "minLabel", "maxLabel", "valueType"} & set(q)
    # No new error-level diagnostics beyond what the old question had.
    errors = [d for d in res.diagnostics if d.severity == "error"]
    assert errors == [], errors


def test_same_type_is_not_allowed() -> None:
    res = change(survey(example("text")), "text")
    assert not res.ok and res.diagnostics[0].code == "op.not_allowed"


def test_unknown_question_and_type() -> None:
    assert (
        run("change_question_type", survey(), {"id": "nope", "type": "text"}).diagnostics[0].code
        == "op.not_found"
    )
    assert change(survey(example("text")), "essay").diagnostics[0].code == "op.params"
    page = run("change_question_type", survey(), {"id": "p1", "type": "text"})
    assert page.diagnostics[0].code == "op.not_found"


def test_question_param_must_match_id_and_type() -> None:
    s = survey(example("text"))
    bad = change(s, "note", question={"id": "other", "type": "note", "label": "x"})
    assert not bad.ok and bad.diagnostics[0].code == "op.params"
    ok = change(s, "note", question={"id": "q", "type": "note", "label": "x"})
    assert ok.ok and q_of(ok.survey) == {"id": "q", "type": "note", "label": "x"}


# --- what carries over ----------------------------------------------------------------


@pytest.mark.parametrize(("old", "new"), [("single", "multi"), ("multi", "single")])
def test_single_multi_keep_choices_and_order(old: str, new: str) -> None:
    res = change(survey(example(old)), new)
    q = q_of(res.survey)
    assert q["choices"] == CHOICES and q["choiceOrder"] == "shuffle"


def test_shared_choice_list_is_kept() -> None:
    src = {"id": "q", "type": "single", "label": "L", "choiceList": "shared"}
    for new in ("multi", "matrix"):
        q = q_of(change(survey(copy.deepcopy(src)), new).survey)
        assert q["choiceList"] == "shared" and "choices" not in q


def test_choice_to_matrix_keeps_columns_adds_rows_and_back() -> None:
    q = q_of(change(survey(example("single")), "matrix").survey)
    assert q["choices"] == CHOICES and q["rows"] == DEFAULT_ROWS and "choiceOrder" not in q
    back = q_of(change(survey(example("matrix")), "multi").survey)
    assert back["choices"] == CHOICES and "rows" not in back


@pytest.mark.parametrize("old", ["text", "integer", "decimal", "date", "slider", "note"])
@pytest.mark.parametrize("new", ["single", "multi", "matrix"])
def test_non_choice_to_choice_gets_default_choices(old: str, new: str) -> None:
    q = q_of(change(survey(example(old)), new).survey)
    assert q["choices"] == DEFAULT_CHOICES
    if new == "matrix":
        assert q["rows"] == DEFAULT_ROWS


@pytest.mark.parametrize("old", ["single", "multi", "matrix"])
def test_choice_to_text_drops_choices(old: str) -> None:
    q = q_of(change(survey(example(old)), "text").survey)
    assert not {"choices", "choiceList", "choiceOrder", "rows"} & set(q)


def test_integer_decimal_keep_bounds() -> None:
    q = q_of(change(survey(example("integer")), "decimal").survey)
    assert (q["min"], q["max"]) == (1, 10)
    q = q_of(change(survey(example("decimal")), "integer").survey)
    assert "min" not in q and q["max"] == 10, "a fractional bound cannot be an integer bound"
    whole = {**example("decimal"), "min": "2", "max": "7.0"}
    q = q_of(change(survey(whole), "integer").survey)
    assert (q["min"], q["max"]) == (2, 7)


def test_numbers_to_slider_carry_a_usable_track() -> None:
    q = q_of(change(survey(example("integer")), "slider").survey)
    assert (q["valueType"], q["min"], q["max"]) == ("integer", 1, 10)
    q = q_of(change(survey({**example("decimal"), "min": "0.5", "max": "5.5"}), "slider").survey)
    assert (q["valueType"], q["min"], q["max"]) == ("decimal", "0.5", "5.5")
    # Unusable (one bound, or a span that is not whole steps): the slider's defaults.
    q = q_of(change(survey({**example("integer"), "max": 5}), "slider").survey)
    assert (q["min"], q["max"]) == (1, 5)
    one = {k: v for k, v in example("integer").items() if k != "max"}
    q = q_of(change(survey(one), "slider").survey)
    assert (q["min"], q["max"]) == (0, 100)
    q = q_of(change(survey(example("decimal")), "slider").survey)  # 0.5 .. 10: 9.5 steps
    assert (q["min"], q["max"]) == (0, 100)
    q = q_of(change(survey(example("text")), "slider").survey)
    assert "min" not in q and "valueType" not in q, "the model defaults (0-100) apply"


def test_slider_to_numbers_keeps_the_track_ends() -> None:
    for new in ("integer", "decimal"):
        q = q_of(change(survey(example("slider")), new).survey)
        assert (q["min"], q["max"]) == (0, 10)
        assert not {"step", "minLabel", "maxLabel", "valueType"} & set(q)


def test_constraint_kept_only_between_number_types() -> None:
    q = q_of(change(survey(example("integer")), "decimal").survey)
    assert q["constraintMessage"] == "Nope" and "constraint" in q
    for new in ("text", "single", "date"):
        q = q_of(change(survey(example("integer")), new).survey)
        assert "constraint" not in q and "constraintMessage" not in q


def test_translations_of_texts_are_kept() -> None:
    q = q_of(change(survey(example("single")), "multi").survey)
    assert q["choices"][0]["label"] == {"en": "One", "de": "Eins"}


# --- references -----------------------------------------------------------------------


def later_question(condition: dict[str, Any], label: str = "Later") -> dict[str, Any]:
    return {"id": "later", "type": "text", "label": label, "showIf": condition}


EQ_1 = {"kind": "compare", "op": "==", "left": ref("q"), "right": {"kind": "int", "value": 1}}
CONTAINS_2 = {"kind": "contains", "ref": ref("q"), "value": {"kind": "int", "value": 2}}
ANSWERED = {"kind": "answered", "ref": ref("q")}


@pytest.mark.parametrize(
    ("old", "new", "condition"),
    [
        ("single", "text", EQ_1),
        ("multi", "single", CONTAINS_2),
        ("single", "multi", EQ_1),
        ("integer", "note", ANSWERED),
        ("integer", "matrix", ANSWERED),
        ("integer", "text", {**EQ_1, "op": ">"}),
    ],
)
def test_breaking_a_condition_is_rejected_unless_forced(
    old: str, new: str, condition: dict[str, Any]
) -> None:
    before = survey(example(old), later=[later_question(condition)])
    res = change(copy.deepcopy(before), new)
    assert not res.ok
    assert {d.code for d in res.diagnostics} == {"op.type_conflict"}
    assert "/blocks/0/pages/1/items/0/showIf" in res.diagnostics[0].message
    assert "1 reference" in res.diagnostics[0].message
    assert any(d.pointer.startswith("/blocks/0/pages/1/items/0/showIf") for d in res.diagnostics)

    forced = change(copy.deepcopy(before), new, force=True)
    round_trips(before, forced)
    assert q_of(forced.survey)["type"] == new
    assert any(d.severity == "error" for d in forced.diagnostics), "the problem stays visible"


def test_choice_code_that_is_no_longer_offered_counts() -> None:
    # text compared with "yes" -> single with default choices: the code is not a choice.
    cond = {**EQ_1, "right": {"kind": "text", "value": "y"}}
    res = change(survey(example("text"), later=[later_question(cond)]), "single")
    assert not res.ok and res.diagnostics[0].code == "op.type_conflict"


def test_piping_into_a_note_or_matrix_counts() -> None:
    later = {"id": "later", "type": "text", "label": {"en": "You said ${q}", "de": "${q}"}}
    for new in ("note", "matrix"):
        res = change(survey(example("text"), later=[copy.deepcopy(later)]), new)
        assert not res.ok, new
        assert "2 references" in res.diagnostics[0].message


def test_matrix_row_references_count() -> None:
    row_ref = {"kind": "answered", "ref": ref("q_a")}
    res = change(survey(example("matrix"), later=[later_question(row_ref)]), "single")
    assert not res.ok and res.diagnostics[0].code == "op.type_conflict"


def test_compatible_references_pass() -> None:
    # integer -> decimal: `q > 1` still compares two numbers; single -> multi keeps the
    # codes but `q == 1` is a type error for multi, so only answered() is safe there.
    gt = {**EQ_1, "op": ">"}
    assert change(survey(example("integer"), later=[later_question(gt)]), "decimal").ok
    assert change(survey(example("single"), later=[later_question(ANSWERED)]), "multi").ok
    piped = later_question(ANSWERED, label="Hello ${q}")
    assert change(survey(example("integer"), later=[piped]), "text").ok


def test_existing_problems_are_not_blamed_on_the_change() -> None:
    # A condition already broken (on another question) does not block this change.
    stale = {**EQ_1, "left": ref("gate"), "right": {"kind": "text", "value": "zzz"}}
    res = change(survey(example("integer"), later=[later_question(stale)]), "decimal")
    assert res.ok
    assert any(d.code == "ref.unknown_choice_code" for d in res.diagnostics)
