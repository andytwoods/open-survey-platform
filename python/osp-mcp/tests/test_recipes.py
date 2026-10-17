"""recipes.py: typed drafting requests become ordinary op invocations (pure)."""

from __future__ import annotations

import pytest
from osp_app.builder import default_survey
from osp_mcp.recipes import (
    ChoiceSpec,
    PageSpec,
    QuestionSpec,
    RowSpec,
    add_block_ops,
    add_page_ops,
    add_question_ops,
    question_object,
)
from osp_ops import Draft, apply_transaction


def _apply(body, ops):
    res = apply_transaction(Draft(survey=body, revision=0), ops, 0)
    assert res.status == "ok", [d.model_dump() for d in res.diagnostics]
    return res.draft.survey


def test_question_object_choices_rows_and_properties():
    q = question_object(
        QuestionSpec(
            type="matrix",
            label="Rate",
            required=True,
            help="Pick one per row",
            choices=["Poor", ChoiceSpec(label="Good", value="g"), "Great"],
            rows=["Falling asleep", RowSpec(id="stay", label="Staying asleep")],
            properties={"name": "sleep_q"},
        ),
        "sleep",
    )
    assert q["choices"] == [
        {"value": 1, "label": "Poor"},
        {"value": "g", "label": "Good"},
        {"value": 2, "label": "Great"},
    ]
    assert q["rows"] == [
        {"id": "r1", "label": "Falling asleep"},
        {"id": "stay", "label": "Staying asleep"},
    ]
    assert q["required"] is True and q["help"] == "Pick one per row" and q["name"] == "sleep_q"


def test_choice_questions_get_a_starter_choice_and_properties_cannot_rename():
    q = question_object(QuestionSpec(type="single", label="?"), "q1")
    assert q["choices"] == [{"value": 1, "label": "Option 1"}]
    shared = question_object(
        QuestionSpec(type="single", label="?", properties={"choiceList": "yesno"}), "q2"
    )
    assert "choices" not in shared and shared["choiceList"] == "yesno"
    with pytest.raises(ValueError, match="properties may not set 'type'"):
        question_object(QuestionSpec(label="?", properties={"type": "multi"}), "q3")


def test_add_block_with_pages_generates_ids_and_a_flow_node():
    body = default_survey("T")
    ops = add_block_ops(
        body,
        "screening",
        title="Screening",
        pages=[
            PageSpec(
                questions=[
                    QuestionSpec(id="age", type="integer", label="Age?", required=True),
                    QuestionSpec(type="single", label="Coffee?", choices=["Yes", "No"]),
                    QuestionSpec(type="note", label="Thanks", showIf="age >= 18"),
                ]
            ),
            PageSpec(id="habits", title="Habits", questions=[QuestionSpec(label="Describe")]),
        ],
    )
    assert [o["op"] for o in ops] == ["add_block", "insert_flow_node"]
    block = ops[0]["params"]["block"]
    assert block["title"] == "Screening"
    p1, p2 = block["pages"]
    assert p1["id"] == "screening_p1" and p2["id"] == "habits" and p2["title"] == "Habits"
    assert [q["id"] for q in p1["items"]] == ["age", "screening_p1_q1", "screening_p1_q2"]
    assert ops[1]["params"]["node"] == {"type": "block", "block": "screening"}
    assert p1["items"][2]["showIf"] == {
        "kind": "compare",
        "op": ">=",
        "left": {"kind": "ref", "id": "age"},
        "right": {"kind": "int", "value": 18},
    }
    after = _apply(body, ops)
    assert [b["id"] for b in after["blocks"]] == ["b1", "screening"]
    assert after["flow"][-1]["block"] == "screening"
    assert after["blocks"][1]["pages"][0]["items"][2]["showIf"]["kind"] == "compare"


def test_add_block_without_pages_or_flow():
    ops = add_block_ops(default_survey("T"), "demo", in_flow=False)
    assert ops == [{"op": "add_block", "params": {"id": "demo"}}]
    ops = add_block_ops(default_survey("T"), "demo", flow_index=0)
    assert ops[1]["params"]["index"] == 0


def test_add_page_and_add_question_ops_apply():
    body = default_survey("T")
    ops = add_page_ops(
        body,
        "b1",
        PageSpec(
            title="About you",
            showIf="true",
            questions=[QuestionSpec(id="age", type="integer", label="Age?")],
        ),
        index=0,
    )
    assert ops[0]["params"]["index"] == 0 and ops[0]["params"]["id"] == "page1"
    assert ops[0]["params"]["page"]["showIf"] == {"kind": "bool", "value": True}
    body = _apply(body, ops)
    ops = add_question_ops(
        body,
        "page1",
        QuestionSpec(
            type="multi", label="Symptoms", choices=["Headache", "Nausea"], showIf="age >= 18"
        ),
    )
    assert [o["op"] for o in ops] == ["add_question"]
    assert ops[0]["params"]["id"] == "q1"  # fresh: `intro` and `age` are taken, q1 is free
    assert ops[0]["params"]["question"]["showIf"]["kind"] == "compare"
    body = _apply(body, ops)
    nausea = body["blocks"][0]["pages"][0]["items"][1]["choices"][1]
    assert nausea == {"value": 2, "label": "Nausea"}


def test_condition_text_that_does_not_parse_is_a_value_error():
    with pytest.raises(ValueError, match="question 'q' condition does not parse"):
        question_object(QuestionSpec(label="?", showIf="age >= "), "q")
    with pytest.raises(ValueError, match="page 'p' condition does not parse"):
        add_page_ops(
            default_survey("T"),
            "b1",
            PageSpec(id="p", showIf="(", questions=[QuestionSpec(label="?")]),
        )


@pytest.mark.parametrize("bad", ["1abc", "has space", "a-b", "x" * 65, ""])
def test_bad_ids_are_refused_before_any_op(bad):
    with pytest.raises(ValueError, match="must be letters, digits and _"):
        add_block_ops(default_survey("T"), bad)
    with pytest.raises(ValueError):
        add_question_ops(default_survey("T"), "p1", QuestionSpec(id=bad, label="?"))
