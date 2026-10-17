"""Drafting over a real store: create, build, validate, preview, undo; refusals are
readable errors with diagnostics, never exceptions (AGENTS.md rule 3)."""

from __future__ import annotations

import pytest
from osp_mcp.drafting import Drafting, DraftingError, outline
from osp_mcp.recipes import PageSpec, QuestionSpec


def _create(d: Drafting) -> str:
    return d.create_survey("Coffee and sleep")["surveyId"]


def test_create_lists_and_outlines(drafting: Drafting):
    made = drafting.create_survey("Coffee and sleep")
    sid = made["surveyId"]
    assert made["revision"] == 0 and made["builderUrl"] == f"http://builder.test/surveys/{sid}"
    assert made["outline"]["blocks"][0]["pages"][0]["items"][0] == {
        "id": "intro",
        "type": "note",
        "label": "",
    }
    listed = drafting.list_surveys()
    assert [s["surveyId"] for s in listed] == [sid]
    assert listed[0]["lab"] == "mcp-lab" and listed[0]["title"] == "Coffee and sleep"
    got = drafting.get_survey(sid)
    assert got["publishedVersions"] == 0 and "survey" not in got
    assert got["problems"] == {"errors": 0, "warnings": 0}
    assert drafting.get_survey(sid, full=True)["survey"]["metadata"]["title"] == {
        "en": "Coffee and sleep"
    }


def test_create_from_a_whole_document_is_validated(drafting: Drafting):
    with pytest.raises(DraftingError) as err:
        drafting.create_survey("x", {"specVersion": "nope"})
    assert err.value.code == "rejected" and err.value.diagnostics
    assert "schema" in err.value.render() or "specVersion" in err.value.render()
    with pytest.raises(DraftingError, match="JSON object"):
        drafting.create_survey("x", ["not", "a", "survey"])
    with pytest.raises(DraftingError, match="title"):
        drafting.create_survey("")


def test_typed_edits_build_a_survey_and_undo_reverses_one_step(drafting: Drafting):
    sid = _create(drafting)
    r = drafting.add_block(
        sid,
        "screening",
        title="Screening",
        pages=[
            PageSpec(
                id="screen",
                questions=[
                    QuestionSpec(
                        id="age",
                        type="integer",
                        label="How old are you?",
                        required=True,
                        properties={"min": 0, "max": 120},
                    ),
                    QuestionSpec(
                        id="coffee",
                        type="single",
                        label="Do you drink coffee?",
                        required=True,
                        choices=["Yes", "No"],
                    ),
                ],
            )
        ],
    )
    assert r["revision"] == 1 and r["changed"] and r["transactionId"]
    assert [b["id"] for b in r["outline"]["blocks"]] == ["b1", "screening"]
    assert [n["block"] for n in r["outline"]["flow"]] == ["b1", "screening"]

    r = drafting.add_page(
        sid,
        "screening",
        PageSpec(
            id="habits",
            title="Your coffee",
            showIf="coffee == 1",
            questions=[
                QuestionSpec(id="cups", type="integer", label="Cups per day?"),
                QuestionSpec(
                    id="last_cup",
                    type="single",
                    label="When is your last cup?",
                    choices=["Morning", "Afternoon", "Evening"],
                ),
            ],
        ),
    )
    page = r["outline"]["blocks"][1]["pages"][1]
    assert page["id"] == "habits" and page["showIf"] is True and page["title"] == "Your coffee"

    r = drafting.add_question(
        sid,
        "habits",
        QuestionSpec(
            id="sleep_quality",
            type="matrix",
            label="How is your sleep?",
            choices=["Poor", "Fair", "Good"],
            rows=["Falling asleep", "Staying asleep"],
        ),
    )
    item = r["outline"]["blocks"][1]["pages"][1]["items"][2]
    assert item["rows"] == ["r1", "r2"] and len(item["choices"]) == 3

    r = drafting.add_choice(sid, "last_cup", "Night")
    assert r["outline"]["blocks"][1]["pages"][1]["items"][1]["choices"][-1] == {
        "value": 4,
        "label": "Night",
    }
    r = drafting.set_condition(sid, "cups", "cups <= 20", field="constraint")
    assert r["outline"]["blocks"][1]["pages"][1]["items"][0]["constraint"] is True
    r = drafting.set_property(sid, "cups", "constraintMessage", "That is a lot of coffee.")
    rev = r["revision"]
    undo_txn = r["transactionId"]

    full = drafting.get_survey(sid, full=True)["survey"]
    assert full["blocks"][1]["pages"][1]["items"][0]["constraintMessage"]

    undone = drafting.undo(sid, undo_txn)
    assert undone["revision"] == rev + 1 and undone["transactionId"].startswith("u:")
    full = drafting.get_survey(sid, full=True)["survey"]
    assert "constraintMessage" not in full["blocks"][1]["pages"][1]["items"][0]
    redone = drafting.undo(sid, undone["transactionId"])
    assert redone["transactionId"].startswith("r:")

    kinds = [h["kind"] for h in drafting.history(sid)]
    assert kinds[-2:] == ["undo", "redo"] and kinds[0] == "edit"


def test_validate_and_preview_report_without_publishing(drafting: Drafting):
    sid = _create(drafting)
    drafting.add_question(sid, "p1", QuestionSpec(id="age", type="integer", label="Age?"))
    v = drafting.validate(sid)
    assert v["valid"] is True and v["problems"]["errors"] == 0
    codes = {d["code"] for d in v["publishChecks"]}
    assert codes == {"publish.retention_required", "publish.consent_missing"}
    assert "cannot publish" in v["note"]

    drafting.set_property(sid, "/settings", "retention", {"kind": "days-after-close", "days": 90})
    drafting.apply_ops(
        sid, [{"op": "set_consent", "params": {"consent": {"text": "You may stop at any time."}}}]
    )
    v = drafting.validate(sid)
    assert v["publishChecks"] == []

    p = drafting.preview(sid)
    assert p["compiles"] is True and p["planChecksum"].startswith("sha256:")
    assert p["pages"] == 1 and p["items"] == 2
    assert p["builderUrl"].endswith(sid) and "Preview" in p["howToPreview"]
    # Nothing was published: no version exists.
    assert drafting.get_survey(sid)["publishedVersions"] == 0


def test_preview_of_a_broken_draft_says_what_is_wrong(drafting: Drafting):
    sid = _create(drafting)
    # A forward reference is a validation error: the plan cannot be compiled.
    drafting.add_block(
        sid,
        "later",
        pages=[PageSpec(questions=[QuestionSpec(id="late", type="integer", label="?")])],
    )
    r = drafting.apply_ops(
        sid,
        [
            {
                "op": "set_property",
                "params": {
                    "target": "intro",
                    "property": "showIf",
                    "value": {"kind": "ref", "id": "late"},
                },
            }
        ],
    )
    assert any(d["severity"] == "error" for d in r["diagnostics"])  # saved, but flagged
    p = drafting.preview(sid)
    assert p["compiles"] is False and p["problems"]["errors"] >= 1
    assert drafting.validate(sid)["valid"] is False


def test_apply_ops_is_all_or_nothing_and_refusals_carry_diagnostics(drafting: Drafting):
    sid = _create(drafting)
    with pytest.raises(DraftingError) as err:
        drafting.apply_ops(
            sid,
            [
                {"op": "add_block", "params": {"id": "ok_block"}},
                {"op": "add_question", "params": {"page": "no_such_page"}},
            ],
        )
    assert err.value.code == "rejected"
    text = err.value.render()
    assert "no_such_page" in text and "[error]" in text
    assert drafting.get_survey(sid)["revision"] == 0  # nothing applied

    with pytest.raises(DraftingError, match=r"ops\[0\] is not an op invocation"):
        drafting.apply_ops(sid, ["add_block"])
    with pytest.raises(DraftingError, match="is not an op; see list_ops"):
        drafting.apply_ops(sid, [{"op": "publish_survey", "params": {}}])
    with pytest.raises(DraftingError, match="non-empty list"):
        drafting.apply_ops(sid, [])
    with pytest.raises(DraftingError, match="baseRevision must be"):
        drafting.apply_ops(sid, [{"op": "add_block", "params": {}}], base_revision=-1)
    with pytest.raises(DraftingError, match="without baseRevision"):
        drafting.apply_ops(sid, [{"op": "add_block", "params": {}}], base_revision=7)
    assert drafting.get_survey(sid)["revision"] == 0


def test_bad_params_and_condition_text_are_diagnostics(drafting: Drafting):
    sid = _create(drafting)
    with pytest.raises(DraftingError) as err:
        drafting.set_condition(sid, "intro", "age >= ")
    assert any(d["code"] == "op.expr_syntax" for d in err.value.diagnostics)
    with pytest.raises(DraftingError) as err:
        drafting.set_property(sid, "intro", "required", True)  # a note has no `required`
    assert any(d["code"] in ("op.not_applicable", "op.not_allowed") for d in err.value.diagnostics)
    with pytest.raises(DraftingError, match="must be letters, digits and _"):
        drafting.add_block(sid, "1 bad id")
    with pytest.raises(DraftingError) as err:
        drafting.add_question(
            sid, "p1", QuestionSpec(id="age", type="integer", label="?", properties={"min": "x"})
        )
    assert err.value.diagnostics  # the survey model refused the value


def test_unknown_surveys_and_ops_are_not_found(drafting: Drafting):
    for sid in ("nope", "", "x" * 40, 12, None):
        with pytest.raises(DraftingError, match="Survey not found"):
            drafting.get_survey(sid)  # type: ignore[arg-type]
    with pytest.raises(DraftingError, match="Survey not found"):
        drafting.undo("nope", "t1")
    with pytest.raises(DraftingError, match="Transaction not found"):
        drafting.undo(_create(drafting), "t-never")
    with pytest.raises(DraftingError, match="no drafting op"):
        drafting.describe_op("teleport")
    assert drafting.describe_op("add_question")["paramsSchema"]["properties"]["page"]


def test_list_ops_is_the_catalogue_without_blocked_ops(drafting: Drafting):
    ops = drafting.list_ops()
    ids = {o["id"] for o in ops}
    assert {"add_block", "add_page", "add_question", "add_choice", "set_condition"} <= ids
    assert "set_hooks" not in ids and "apply_patch" not in ids
    assert all(o["summary"] and "." not in o["summary"][-1:] for o in ops)
    assert {o["area"] for o in drafting.list_ops("pages")} == {"pages"}


def test_outline_never_crashes():
    assert outline(None) == {"problem": "the draft is not a JSON object"}
    assert outline({"blocks": "nope"})["blocks"] == []  # not a list: nothing to show
    assert outline({"blocks": [{"pages": 5}]})["problem"].startswith("could not outline")
    weird = outline(
        {
            "metadata": {"title": {"fr": "Bonjour"}, "languages": ["fr"]},
            "flow": [
                {
                    "type": "branch",
                    "id": "br",
                    "then": [{"type": "end", "id": "e", "outcome": "done"}],
                }
            ],
        }
    )
    assert weird["title"] == "Bonjour" and weird["flow"][0]["then"][0]["outcome"] == "done"
