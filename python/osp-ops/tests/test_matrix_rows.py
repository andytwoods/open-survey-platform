"""Grid (matrix) row ops (task B15). Round trips and fuzzing are in test_guard.py."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from osp_ops import REGISTRY, run

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


def rows(survey: dict[str, Any], qid: str = "grid") -> list[str]:
    return [r["id"] for r in question(survey, qid)["rows"]]


ROW_OPS = {
    "add_matrix_row",
    "delete_matrix_row",
    "move_matrix_row",
    "rename_matrix_row",
    "set_matrix_row_required",
}


def test_row_ops_are_registered_in_their_own_area() -> None:
    assert {k for k, v in REGISTRY.items() if v.area == "rows"} == ROW_OPS


def test_add_row_claims_a_fresh_id_that_skips_taken_variables() -> None:
    res = run("add_matrix_row", base(), {"question": "grid", "label": "Smell"})
    assert res.ok and rows(res.survey) == ["taste", "price", "look", "r4"]
    assert res.inverse is not None and res.inverse.op == "delete_matrix_row"
    # `grid_r4` is taken by another question: the next free id is used.
    s = base()
    question(s, "grid_why")["id"] = "grid_r4"
    res = run("add_matrix_row", s, {"question": "grid"})
    assert res.ok and rows(res.survey)[-1] == "r5"
    # ... case-insensitively, like data names.
    question(s, "grid_r4")["id"] = "GRID_R5"
    res = run("add_matrix_row", s, {"question": "grid"})
    assert res.ok and rows(res.survey)[-1] == "r4"


def test_add_row_with_a_given_id_and_position() -> None:
    res = run("add_matrix_row", base(), {"question": "grid", "id": "smell", "index": 1})
    assert res.ok and rows(res.survey) == ["taste", "smell", "price", "look"]
    assert question(res.survey, "grid")["rows"][1] == {"id": "smell", "label": ""}


def test_add_row_rejects_taken_and_invalid_ids() -> None:
    assert codes(run("add_matrix_row", base(), {"question": "grid", "id": "taste"}))[0] == (
        "op.duplicate_id"
    )
    s = base()
    question(s, "grid_why")["id"] = "grid_smell"
    assert codes(run("add_matrix_row", s, {"question": "grid", "id": "smell"}))[0] == (
        "op.duplicate_id"
    )
    assert codes(run("add_matrix_row", base(), {"question": "grid", "id": "1bad"}))[0] == (
        "op.params"
    )
    long = "x" * 60
    res = run("add_matrix_row", base(), {"question": "grid", "id": long})
    assert not res.ok and "longer than 64" in res.diagnostics[0].message


def test_row_ops_need_a_grid_and_a_known_row() -> None:
    assert codes(run("add_matrix_row", base(), {"question": "age"}))[0] == "op.not_allowed"
    assert codes(run("add_matrix_row", base(), {"question": "nope"}))[0] == "op.not_found"
    res = run("rename_matrix_row", base(), {"question": "grid", "row": "nope", "label": "x"})
    assert codes(res)[0] == "op.not_found"
    res = run("move_matrix_row", base(), {"question": "grid", "row": "taste", "index": 9})
    assert codes(res)[0] == "op.not_allowed"


def test_delete_referenced_row_is_rejected_with_every_site() -> None:
    res = run("delete_matrix_row", base(), {"question": "grid", "row": "taste"})
    assert not res.ok and codes(res)[0] == "op.dangling_ref"
    msg = res.diagnostics[0].message
    assert "row 'taste' of 'grid'" in msg and "force: true" not in msg
    pointers = {d.pointer for d in res.diagnostics[1:]}
    assert pointers == {
        "/blocks/1/pages/0/items/3/label/en",
        "/blocks/1/pages/0/items/3/label/de",
    }
    res = run("delete_matrix_row", base(), {"question": "grid", "row": "price"})
    assert codes(res)[0] == "op.dangling_ref"
    assert res.diagnostics[0].pointer == "/blocks/1/pages/0/items/3/showIf"


def test_delete_row_force_and_cascade() -> None:
    res = run("delete_matrix_row", base(), {"question": "grid", "row": "price", "force": True})
    assert res.ok and rows(res.survey) == ["taste", "look"]
    assert "ref.unknown" in codes(res)  # left dangling, reported
    assert res.inverse is not None and res.inverse.params == {
        "question": "grid",
        "id": "price",
        "label": {"en": "Price", "de": "Preis"},
        "index": 1,
        "required": False,
    }
    res = run("delete_matrix_row", base(), {"question": "grid", "row": "price", "cascade": True})
    assert res.ok and "showIf" not in question(res.survey, "grid_why")
    res = run("delete_matrix_row", base(), {"question": "grid", "row": "taste", "cascade": True})
    assert res.ok and question(res.survey, "grid_why")["label"] == {"en": "Why ?", "de": "Warum ?"}


def test_last_row_cannot_be_deleted() -> None:
    s = base()
    question(s, "grid")["rows"] = [{"id": "only", "label": "Only"}]
    res = run("delete_matrix_row", s, {"question": "grid", "row": "only", "force": True})
    assert codes(res)[0] == "op.not_allowed"


def test_a_pipe_in_another_rows_label_counts_as_a_reference() -> None:
    s = base()
    question(s, "grid")["rows"][2]["label"] = {"en": "Look (${grid_price})", "de": "Aussehen"}
    question(s, "grid_why").pop("showIf")
    res = run("delete_matrix_row", s, {"question": "grid", "row": "price"})
    assert codes(res)[0] == "op.dangling_ref"
    assert res.diagnostics[1].pointer == "/blocks/1/pages/0/items/2/rows/2/label/en"
    # Its own label referring to itself goes with it.
    question(s, "grid")["rows"][2]["label"] = "Look"
    question(s, "grid")["rows"][1]["label"] = "Price ${grid_price}"
    assert run("delete_matrix_row", s, {"question": "grid", "row": "price"}).ok


def test_move_rename_and_required_keep_the_row_id() -> None:
    res = run("move_matrix_row", base(), {"question": "grid", "row": "look", "index": 0})
    assert res.ok and rows(res.survey) == ["look", "taste", "price"]
    assert res.patch == [
        {
            "op": "move",
            "from": "/blocks/1/pages/0/items/2/rows/2",
            "path": "/blocks/1/pages/0/items/2/rows/0",
        }
    ]
    params = {"question": "grid", "row": "taste", "label": {"en": "Flavour", "de": "Aroma"}}
    res = run("rename_matrix_row", base(), params)
    assert res.ok and question(res.survey, "grid")["rows"][0] == {
        "id": "taste",
        "label": {"en": "Flavour", "de": "Aroma"},
    }
    res = run(
        "set_matrix_row_required", base(), {"question": "grid", "row": "price", "required": None}
    )
    assert res.ok and "required" not in question(res.survey, "grid")["rows"][1]
    assert res.inverse is not None and res.inverse.params["required"] is False
    res = run(
        "set_matrix_row_required", base(), {"question": "grid", "row": "taste", "required": True}
    )
    assert res.ok and question(res.survey, "grid")["rows"][0]["required"] is True
    # `required` must be given (null means "follow the grid").
    res = run("set_matrix_row_required", base(), {"question": "grid", "row": "taste"})
    assert codes(res) == ["op.params"]


def test_deleting_the_grid_reports_references_to_its_rows() -> None:
    res = run("delete_question", base(), {"id": "grid"})
    assert codes(res)[0] == "op.dangling_ref"
    assert "/blocks/1/pages/0/items/3/showIf" in res.diagnostics[0].message


def test_removing_a_language_strips_row_label_translations() -> None:
    res = run("set_languages", base(), {"languages": ["en"], "cascade": True})
    assert res.ok and question(res.survey, "grid")["rows"][0]["label"] == {"en": "Taste"}
    assert "text.unknown_language" not in codes(res)
