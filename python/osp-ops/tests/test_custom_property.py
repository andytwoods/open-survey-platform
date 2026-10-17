"""`set_custom_property` (task B21): the one editing path for a question's lab-defined
annotations. Round trips and fuzzing are in test_guard.py."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from osp_ops import REGISTRY, run

BASE: dict[str, Any] = json.loads((Path(__file__).parent / "base_survey.json").read_text("utf-8"))


def base() -> dict[str, Any]:
    return copy.deepcopy(BASE)


def question(survey: dict[str, Any], qid: str) -> dict[str, Any]:
    for b in survey["blocks"]:
        for page in b["pages"]:
            for q in page["items"]:
                if q["id"] == qid:
                    return q
    raise KeyError(qid)


def codes(res: Any) -> list[str]:
    return [d.code for d in res.diagnostics]


def test_registered_in_the_questions_area() -> None:
    assert REGISTRY["set_custom_property"].area == "questions"


def test_set_creates_the_object_and_the_inverse_unsets() -> None:
    res = run("set_custom_property", base(), {"target": "age", "key": "construct", "value": "x"})
    assert res.ok and question(res.survey, "age")["custom"] == {"construct": "x"}
    assert res.inverse is not None
    assert res.inverse.params == {"target": "age", "key": "construct", "unset": True}
    undo = run(res.inverse.op, res.survey, res.inverse.params)
    assert undo.ok and "custom" not in question(undo.survey, "age")


def test_overwrite_remembers_the_old_value() -> None:
    s = base()
    question(s, "age")["custom"] = {"weight": 1, "construct": "a"}
    res = run("set_custom_property", s, {"target": "age", "key": "weight", "value": 2.5})
    assert res.ok and question(res.survey, "age")["custom"] == {"weight": 2.5, "construct": "a"}
    assert res.inverse is not None
    assert res.inverse.params == {"target": "age", "key": "weight", "value": 1}


def test_unset_the_last_key_drops_the_object() -> None:
    s = base()
    question(s, "age")["custom"] = {"weight": 1}
    res = run("set_custom_property", s, {"target": "age", "key": "weight", "unset": True})
    assert res.ok and "custom" not in question(res.survey, "age")
    # Unsetting a key that is not there is a no-op with a no-op inverse.
    res = run("set_custom_property", base(), {"target": "age", "key": "nope", "unset": True})
    assert res.ok and res.patch == []


def test_bad_keys_values_and_targets_are_diagnostics() -> None:
    bad_key = run("set_custom_property", base(), {"target": "age", "key": "Bad-Key", "value": 1})
    assert not bad_key.ok and "op.invalid_result" in codes(bad_key)
    no_value = run("set_custom_property", base(), {"target": "age", "key": "k"})
    assert not no_value.ok and "op.params" in codes(no_value)
    not_question = run("set_custom_property", base(), {"target": "p_demo", "key": "k", "value": 1})
    assert not not_question.ok and "op.not_found" in codes(not_question)
    nested = run("set_custom_property", base(), {"target": "age", "key": "k", "value": {"a": 1}})
    assert not nested.ok and "op.params" in codes(nested)


def test_too_many_keys_is_refused() -> None:
    s = base()
    question(s, "age")["custom"] = {f"k{i}": i for i in range(40)}
    res = run("set_custom_property", s, {"target": "age", "key": "k40", "value": 1})
    assert not res.ok and "op.not_allowed" in codes(res)
    # Replacing an existing key is still fine at the limit.
    res = run("set_custom_property", s, {"target": "age", "key": "k0", "value": "new"})
    assert res.ok


def test_add_question_applies_profile_defaults() -> None:
    defaults = {"required": True, "custom.weight": 2.5, "custom.prereg": False}
    res = run("add_question", base(), {"page": "p_demo", "type": "text", "defaults": defaults})
    assert res.ok, [d.message for d in res.diagnostics]

    def page_items(survey):  # p_demo's items, wherever the page sits
        return next(p["items"] for b in survey["blocks"] for p in b["pages"] if p["id"] == "p_demo")

    before = page_items(base())
    added = [x for x in page_items(res.survey) if x not in before][0]
    assert added["required"] is True and added["custom"] == {"weight": 2.5, "prereg": False}
    for bad in ({"id": "x"}, {"type": "note"}, {"custom": {}}, {"metadata.title": "x"}):
        res = run("add_question", base(), {"page": "p_demo", "defaults": bad})
        assert not res.ok and "op.params" in codes(res)
    # A default the model refuses is an invalid result, as for any other edit.
    res = run("add_question", base(), {"page": "p_demo", "defaults": {"required": "yes"}})
    assert not res.ok and "op.invalid_result" in codes(res)


def test_set_property_refuses_the_custom_object() -> None:
    res = run("set_property", base(), {"target": "age", "property": "custom", "value": {"a": 1}})
    assert not res.ok and "op.not_allowed" in codes(res)
