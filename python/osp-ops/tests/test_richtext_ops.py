"""Rich text through the ops (planning/rich-text.md §3, task RT2): normalisation on write
(RT-D3), the write guard (`op.invalid_text`), pipe nodes in cascades and duplicates, and
the text walker's coverage of page titles, slider labels and consent."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from osp_ops import run
from osp_ops.doc import text_sites
from osp_ops.patch import to_pointer

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


def _rich(*blocks: dict) -> dict:
    return {"type": "rich", "blocks": list(blocks)}


def _p(*content: dict) -> dict:
    return {"type": "p", "content": list(content)}


PLAIN_TREE = _rich(_p({"text": "You are "}, {"pipe": "age"}, {"text": " years old"}))
BOLD_TREE = _rich(_p({"text": "You are "}, {"pipe": "age"}, {"text": "!", "marks": ["b"]}))


# --- normalisation on write (RT-D3) ------------------------------------------------------


def test_set_property_stores_formatting_free_rich_text_as_a_string() -> None:
    res = run(
        "set_property", base(), {"target": "rating", "property": "label", "value": PLAIN_TREE}
    )
    assert res.ok
    assert question(res.survey, "rating")["label"] == "You are ${age} years old"
    assert (
        res.inverse is not None
        and res.inverse.params["value"] == BASE["blocks"][1]["pages"][0]["items"][1]["label"]
    )


def test_set_property_keeps_a_formatted_tree() -> None:
    res = run("set_property", base(), {"target": "rating", "property": "label", "value": BOLD_TREE})
    assert res.ok
    assert question(res.survey, "rating")["label"] == BOLD_TREE
    assert "op.invalid_text" not in codes(res)
    # Per language: each value on its own.
    both = {"en": BOLD_TREE, "de": PLAIN_TREE}
    res = run("set_property", base(), {"target": "rating", "property": "label", "value": both})
    assert res.ok
    assert question(res.survey, "rating")["label"] == {
        "en": BOLD_TREE,
        "de": "You are ${age} years old",
    }


@pytest.mark.parametrize(
    ("op", "params", "path"),
    [
        (
            "add_choice",
            {"owner": "fruit", "label": PLAIN_TREE, "value": 4},
            ("choices", -1, "label"),
        ),
        (
            "set_choice",
            {"owner": "fruit", "value": 1, "label": PLAIN_TREE},
            ("choices", 0, "label"),
        ),
        (
            "add_matrix_row",
            {"question": "grid", "id": "r9", "label": PLAIN_TREE},
            ("rows", -1, "label"),
        ),
        (
            "rename_matrix_row",
            {"question": "grid", "row": "taste", "label": PLAIN_TREE},
            ("rows", 0, "label"),
        ),
    ],
)
def test_choice_and_row_ops_normalise(op: str, params: dict, path: tuple) -> None:
    res = run(op, base(), params)
    assert res.ok, codes(res)
    q = question(res.survey, params.get("owner") or params["question"])
    assert q[path[0]][path[1]][path[2]] == "You are ${age} years old"


def test_add_question_normalises_its_label_and_a_whole_object() -> None:
    res = run("add_question", base(), {"page": "p_demo", "type": "note", "label": PLAIN_TREE})
    assert res.ok and question(res.survey, "q1")["label"] == "You are ${age} years old"
    obj = {"type": "single", "label": PLAIN_TREE, "help": BOLD_TREE,
           "choices": [{"value": 1, "label": _rich(_p({"text": "A"}))}]}  # fmt: skip
    res = run("add_question", base(), {"page": "p_demo", "question": obj, "id": "nq"})
    assert res.ok, codes(res)
    q = question(res.survey, "nq")
    assert q["label"] == "You are ${age} years old" and q["help"] == BOLD_TREE
    assert q["choices"][0]["label"] == "A"


def test_set_consent_and_set_ending_normalise() -> None:
    consent = {"text": _rich(_p({"text": "Please agree"})), "agreeLabel": BOLD_TREE_NO_PIPE}
    res = run("set_consent", base(), {"consent": consent})
    assert res.ok, codes(res)
    assert res.survey["consent"] == {"text": "Please agree", "agreeLabel": BOLD_TREE_NO_PIPE}
    ending = {"title": _rich(_p({"text": "Done"})), "body": BOLD_TREE,
              "redirect": None}  # fmt: skip
    ending.pop("redirect")
    res = run("set_ending", base(), {"outcome": "complete", "ending": ending})
    assert res.ok, codes(res)
    assert res.survey["settings"]["endings"]["complete"] == {"title": "Done", "body": BOLD_TREE}


BOLD_TREE_NO_PIPE = _rich(_p({"text": "Yes", "marks": ["b"]}))


# --- the write guard -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (_rich(_p({"text": "x", "href": "http://example.org"})), "link.scheme"),
        (_rich(_p({"text": "", "href": "https://example.org"})), "link.empty"),
        (_rich({"type": "h", "level": 1, "content": [{"text": "H"}]}), "text.block_not_allowed"),
        ("x" * 2001, "text.too_long"),
        (_rich(*([_p({"text": "p"})] * 201)), "text.too_many_blocks"),
    ],
)
def test_writes_that_break_the_text_rules_are_refused(value: Any, code: str) -> None:
    res = run("set_property", base(), {"target": "rating", "property": "label", "value": value})
    assert not res.ok
    assert codes(res)[0] == "op.invalid_text" and code in codes(res)
    assert res.survey == BASE  # unchanged input comes back


def test_headings_are_allowed_in_a_note() -> None:
    heading = _rich({"type": "h", "level": 1, "content": [{"text": "Welcome"}]})
    res = run("set_property", base(), {"target": "info", "property": "label", "value": heading})
    assert res.ok and question(res.survey, "info")["label"] == heading


def test_whole_document_ops_are_guarded_too() -> None:
    s = base()
    question(s, "rating")["label"] = _rich(_p({"text": "x", "href": "javascript:alert(1)"}))
    res = run("replace_survey", base(), {"survey": s})
    assert not res.ok and codes(res)[0] == "op.invalid_text"
    patch = [{"op": "replace", "path": "/blocks/1/pages/0/items/1/label", "value": "y" * 3000}]
    res = run("apply_patch", base(), {"patch": patch})
    assert not res.ok and codes(res)[0] == "op.invalid_text"


def test_a_pre_existing_problem_is_reported_not_blocking() -> None:
    s = base()
    question(s, "rating")["label"] = "x" * 2001  # an old survey over the limit
    res = run("set_title", s, {"title": "New title"})
    assert res.ok and "text.too_long" in codes(res)


def test_a_malformed_tree_is_structurally_invalid() -> None:
    tree = {"type": "rich", "blocks": [{"type": "img"}]}
    res = run("set_property", base(), {"target": "rating", "property": "label", "value": tree})
    assert not res.ok and codes(res)[0] == "op.invalid_result"


# --- pipe nodes in cascades, duplicates and the walker -----------------------------------


PEAR_TREE = _rich(_p({"text": "Why "}, {"pipe": "why_pear"}, {"text": "?", "marks": ["b"]}))


def test_delete_cascade_drops_pipe_nodes() -> None:
    s = base()
    question(s, "rating")["label"] = {
        "en": PEAR_TREE,
        "de": _rich(_p({"pipe": "why_pear"}, {"text": " J"})),
    }
    res = run("delete_question", s, {"id": "why_pear", "cascade": True})
    assert res.ok, codes(res)
    label = question(res.survey, "rating")["label"]
    assert label["en"] == _rich(_p({"text": "Why "}, {"text": "?", "marks": ["b"]}))
    assert label["de"] == _rich(_p({"text": " J"}))
    assert "ref.unknown" not in codes(res)


def test_delete_without_cascade_names_the_pipe_node() -> None:
    s = base()
    question(s, "rating")["label"] = PEAR_TREE
    res = run("delete_question", s, {"id": "why_pear"})
    assert not res.ok and codes(res)[0] == "op.dangling_ref"
    ptr = "/blocks/1/pages/0/items/1/label/blocks/0/content/1"
    assert any(d.pointer == ptr for d in res.diagnostics)


def test_duplicate_question_renames_pipe_nodes_to_the_copy() -> None:
    s = base()
    question(s, "rating")["help"] = _rich(
        _p({"text": "You said "}, {"pipe": "rating"}, {"text": "!", "marks": ["i"]})
    )
    res = run("duplicate_question", s, {"id": "rating"})
    assert res.ok, codes(res)
    copy_ = question(res.survey, "rating_copy")
    assert copy_["help"]["blocks"][0]["content"][1] == {"pipe": "rating_copy"}


def test_duplicate_page_remaps_pipe_nodes() -> None:
    s = base()
    question(s, "why_pear")["label"] = _rich(_p({"pipe": "age"}, {"text": "?", "marks": ["b"]}))
    res = run("duplicate_page", s, {"id": "p_demo"})
    assert res.ok, codes(res)
    page = res.survey["blocks"][0]["pages"][2]
    labels = [q["label"] for q in page["items"] if q["type"] == "text"]
    assert labels[0]["blocks"][0]["content"][0] == {"pipe": page["items"][0]["id"]}


def test_text_sites_cover_page_titles_slider_labels_and_consent() -> None:
    s = base()
    s["blocks"][0]["pages"][0]["title"] = {"en": "Intro", "de": "Einführung"}
    s["consent"] = {"text": {"en": "Agree?", "de": "Einverstanden?"}, "agreeLabel": "Yes"}
    s["blocks"][0]["pages"][0]["items"].append(
        {"id": "sl", "type": "slider", "label": "S", "minLabel": {"en": "low", "de": "niedrig"}}
    )
    pointers = {to_pointer(path) for path, _ in text_sites(s)}
    assert {"/blocks/0/pages/0/title", "/consent/text", "/consent/agreeLabel",
            "/blocks/0/pages/0/items/1/minLabel"} <= pointers  # fmt: skip
    res = run("set_languages", s, {"languages": ["en"]})
    assert not res.ok and codes(res)[0] == "op.dangling_ref"
    res = run("set_languages", s, {"languages": ["en"], "cascade": True})
    assert res.ok
    assert res.survey["consent"]["text"] == {"en": "Agree?"}
    assert res.survey["blocks"][0]["pages"][0]["title"] == {"en": "Intro"}
