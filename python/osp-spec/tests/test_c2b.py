"""C2b gaps: page titles, re-exports, `Condition` vs `Expression`, unknown choice codes."""

from __future__ import annotations

import copy
import json
from typing import Any, get_args

import osp_spec
import pytest
from osp_spec import Condition, Expression, Page, Survey, json_schema, parse, validate
from osp_spec import model as m
from osp_spec.property_schema import property_schemas

P0 = "/blocks/0/pages/0"


def base() -> dict[str, Any]:
    return {
        "specVersion": "osp-survey/0.1",
        "id": "srv",
        "metadata": {"title": "T", "languages": ["en", "de"]},
        "blocks": [
            {"id": "b1", "pages": [{"id": "p1", "items": [
                {"id": "q1", "type": "single", "label": {"en": "Q1", "de": "F1"},
                 "choices": [{"value": 1, "label": {"en": "A", "de": "A"}},
                             {"value": 2, "label": {"en": "B", "de": "B"}}]},
            ]}, {"id": "p2", "items": [
                {"id": "q2", "type": "integer", "label": {"en": "Q2", "de": "F2"}},
            ]}]},
        ],
        "flow": [{"type": "block", "id": "f1", "block": "b1"}],
    }  # fmt: skip


def codes(s: dict) -> list[tuple[str, str]]:
    return sorted((d.code, d.pointer) for d in validate(s))


# --- 1. Page titles ---------------------------------------------------------------------


def test_page_title_is_optional_and_translatable() -> None:
    s = base()
    assert codes(s) == []
    s["blocks"][0]["pages"][0]["title"] = "Intro"
    assert codes(s) == []
    s["blocks"][0]["pages"][1]["title"] = {"en": "About ${q1}", "de": "Über ${q1}"}
    survey, diags = parse(s)
    assert diags == [] and survey is not None
    assert survey.blocks[0].pages[1].title == {"en": "About ${q1}", "de": "Über ${q1}"}


def test_page_title_round_trips_and_absent_title_is_not_serialised() -> None:
    s = base()
    survey, _ = parse(s)
    assert survey is not None
    assert "title" not in survey.model_dump(mode="json", exclude_none=True)["blocks"][0]["pages"][0]
    s["blocks"][0]["pages"][0]["title"] = {"en": "Hi", "de": "Hallo"}
    survey, _ = parse(s)
    dumped = survey.model_dump(mode="json", exclude_none=True)
    assert dumped["blocks"][0]["pages"][0]["title"] == {"en": "Hi", "de": "Hallo"}


def test_page_title_text_checks() -> None:
    s = base()
    s["blocks"][0]["pages"][0]["title"] = {"en": "Hi", "fr": "Salut"}
    s["blocks"][0]["pages"][1]["title"] = "${q2} and ${ghost}"
    assert (
        codes(s)
        == [
            ("ref.forward", f"{P0[:-1]}1/title"),  # a page title sits before its own items
            ("ref.unknown", f"{P0[:-1]}1/title"),
            ("text.missing_translation", f"{P0}/title"),
            ("text.unknown_language", f"{P0}/title/fr"),
        ]
    )


def test_page_title_in_unplaced_block_is_still_checked() -> None:
    s = base()
    s["flow"] = []
    s["blocks"][0]["pages"][0]["title"] = {"en": "Hi", "xx": "?"}
    assert ("text.unknown_language", f"{P0}/title/xx") in codes(s)


def test_page_title_is_in_schema_and_property_schema() -> None:
    page = json_schema()["$defs"]["Page"]["properties"]
    assert "title" in page
    spec = property_schemas()["page"].properties["title"]
    assert spec.kind == "text" and spec.translatable and not spec.required


def test_block_title_unchanged() -> None:
    assert m.Block.model_fields["title"].annotation == (m.StrictStr | None)  # type: ignore[attr-defined]


# --- 3. Re-exports ----------------------------------------------------------------------


def test_public_model_classes_are_re_exported() -> None:
    for name in osp_spec.__all__:
        assert hasattr(osp_spec, name), name
    for name in ("Page", "Block", "SingleQuestion", "BranchNode", "Quota", "Metadata"):
        assert name in osp_spec.__all__
        assert getattr(osp_spec, name) is getattr(m, name)
    assert osp_spec.Survey is Survey and Page is m.Page


# --- 5. Condition vs Expression ---------------------------------------------------------


def _alias_of(cls: type, field: str) -> Any:
    annotation = cls.model_fields[field].annotation
    args = [a for a in get_args(annotation) if a is not type(None)]
    return args[0] if args else annotation


@pytest.mark.parametrize(
    "cls, field",
    [
        (m.IntegerQuestion, "showIf"),
        (m.NoteQuestion, "showIf"),
        (m.SingleQuestion, "constraint"),
        (m.BranchNode, "if_"),
        (m.Quota, "when"),
    ],
)
def test_condition_fields(cls: type, field: str) -> None:
    assert _alias_of(cls, field) is Condition


def test_computed_expr_stays_an_expression() -> None:
    assert _alias_of(m.ComputedVariable, "expr") is Expression


def test_condition_kinds_in_property_schemas() -> None:
    for name, schema in property_schemas().items():
        for key in ("showIf", "constraint"):
            if key in schema.properties:
                assert schema.properties[key].kind == "condition", (name, key)


def test_non_boolean_condition_is_a_type_error() -> None:
    s = base()
    q2 = s["blocks"][0]["pages"][1]["items"][0]
    q2["showIf"] = {"kind": "ref", "id": "q1"}
    q2["constraint"] = {"kind": "bool", "value": True}
    assert codes(s) == [("expr.type", f"{P0[:-1]}1/items/0/showIf")]


def test_serialised_json_is_unchanged_by_the_alias() -> None:
    s = base()
    cond = {"kind": "answered", "ref": {"kind": "ref", "id": "q1"}}
    s["blocks"][0]["pages"][1]["items"][0]["showIf"] = cond
    survey, _ = parse(copy.deepcopy(s))
    dumped = json.loads(survey.model_dump_json(exclude_none=True))
    assert dumped["blocks"][0]["pages"][1]["items"][0]["showIf"] == cond


# --- 4. Unknown choice codes ------------------------------------------------------------


def test_unknown_choice_code_through_shared_list_and_computed() -> None:
    s = base()
    s["choiceLists"] = [{"id": "yn", "choices": [{"value": "y", "label": "Y"}]}]
    q1 = s["blocks"][0]["pages"][0]["items"][0]
    del q1["choices"]
    q1["choiceList"] = "yn"
    s["variables"] = [
        {
            "id": "c1",
            "kind": "computed",
            "expr": {
                "kind": "compare",
                "op": "==",
                "left": {"kind": "ref", "id": "q1"},
                "right": {"kind": "text", "value": "n"},
            },
        }
    ]
    diags = validate(s)
    hits = [d for d in diags if d.code == "ref.unknown_choice_code"]
    assert [(d.pointer, d.severity) for d in hits] == [("/variables/0/expr/right", "warning")]
    assert "'n'" in hits[0].message and "y" in hits[0].message


def test_unknown_choice_list_does_not_also_report_codes() -> None:
    s = base()
    q1 = s["blocks"][0]["pages"][0]["items"][0]
    del q1["choices"]
    q1["choiceList"] = "nope"
    s["blocks"][0]["pages"][1]["items"][0]["showIf"] = {
        "kind": "compare",
        "op": "==",
        "left": {"kind": "ref", "id": "q1"},
        "right": {"kind": "int", "value": 9},
    }
    assert "ref.unknown_choice_code" not in {d.code for d in validate(s)}
