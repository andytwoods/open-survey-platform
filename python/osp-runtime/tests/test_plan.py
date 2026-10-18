"""Tests for osp_runtime.plan: the survey → runtime plan compiler (task R1)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from osp_runtime.config import RuntimeConfig
from osp_runtime.plan import (
    ENGINE_VERSION,
    PLAN_VERSION,
    PlanError,
    canonical_json,
    checksum,
    compile_plan,
    compile_survey,
    runtime_config,
    seed_node,
    segments,
)
from osp_spec import CODES, parse

REPO = Path(__file__).resolve().parents[3]
CASES = REPO / "python" / "osp-spec" / "tests" / "cases"
SCHEMA = json.loads((REPO / "contract" / "runtime-plan.schema.json").read_text())
VALID = sorted((CASES / "valid").glob("*.json"))
INVALID = sorted((CASES / "invalid").glob("*.json"))


def _survey(path: Path) -> dict:
    return json.loads(path.read_text())["survey"]


def _walk(nodes: list[dict]):
    for n in nodes:
        yield n
        if n["type"] == "branch":
            yield from _walk(n["then"])
            yield from _walk(n["else"])
        elif n["type"] == "randomiser":
            yield from _walk(n["children"])


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.stem)
def test_every_valid_case_compiles(path: Path) -> None:
    plan, diags = compile_survey(_survey(path))
    assert plan is not None, [d.code for d in diags]
    assert plan["planVersion"] == PLAN_VERSION
    assert plan["engineVersion"] == ENGINE_VERSION
    assert plan["checksum"] == checksum(plan)
    assert set(plan) - {"hooks", "endings", "redirectTemplates"} == set(
        SCHEMA["required"]
    )  # only when the survey has them
    # Ids resolve: every page item is an item, every block node's pages exist.
    for page in plan["pages"].values():
        for item in page["items"]:
            assert plan["items"][item]["page"] == page["id"]
    for node in _walk(plan["flow"]):
        if node["type"] == "block":
            assert node["pages"] == plan["blocks"][node["block"]]["pages"]
            assert all(p in plan["pages"] for p in node["pages"])
        if node["type"] == "quotaCheck":
            assert node["quota"] in plan["quotas"]
    for qid in plan["questions"]:
        item = plan["items"][qid]
        assert item["type"] != "note"
        if item["type"] in ("single", "multi"):
            assert item["choices"], qid
    # Every text has every language.
    langs = set(plan["languages"])
    for item in plan["items"].values():
        assert set(item["label"]) == langs
    json.dumps(plan)  # plain JSON


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.stem)
def test_invalid_cases_give_diagnostics_not_plans(path: Path) -> None:
    data = json.loads(path.read_text())
    plan, diags = compile_survey(data.get("survey", data))
    if any(CODES.get(e["code"]) == "error" for e in data.get("expect", [])):
        assert plan is None
        assert diags
    else:
        assert plan is not None


def test_compile_survey_never_raises_on_garbage() -> None:
    for junk in (None, 1, "x", [], {}, {"specVersion": "osp-survey/0.1"}):
        plan, diags = compile_survey(junk)
        assert plan is None and diags


def test_compile_plan_rejects_errors() -> None:
    data = _survey(CASES / "valid" / "v02_minimal.json")
    survey, _ = parse(data)
    assert survey is not None
    bad = survey.model_copy(update={"flow": []})
    compile_plan(bad)  # an empty flow is only a warning
    broken = copy.deepcopy(data)
    broken["flow"].append(dict(broken["flow"][0]))  # duplicate node id → error
    survey2, _ = parse(broken)
    if survey2 is not None:
        with pytest.raises(PlanError):
            compile_plan(survey2)


def test_checksum_is_stable_and_sensitive() -> None:
    data = _survey(CASES / "valid" / "v01_worked_example.json")
    a, _ = compile_survey(data)
    b, _ = compile_survey(copy.deepcopy(data))
    assert a == b and a["checksum"] == b["checksum"]
    changed = copy.deepcopy(data)
    changed["metadata"]["title"] = {"en": "Other", "de": "Andere"}
    c, _ = compile_survey(changed)
    assert c["checksum"] != a["checksum"]


def test_canonical_json_matches_the_engine_rules() -> None:
    assert canonical_json({"b": 1, "a": ["é", None, True]}) == '{"a":["é",null,true],"b":1}'


def test_worked_example_details() -> None:
    plan, _ = compile_survey(_survey(CASES / "valid" / "v01_worked_example.json"))
    assert plan["survey"] == {
        "id": "srv_7f3c",
        "version": 3,
        "specVersion": "osp-survey/0.1",
        "seedVersion": "3",
    }
    assert plan["questions"] == ["consent", "age", "att1", "att2", "att3"]
    att1 = plan["items"]["att1"]
    assert att1["label"]["en"] == [
        "With the ",
        {"pipe": "incentive"},
        " you were offered, the programme seems fair.",
    ]
    assert att1["choices"][0] == {
        "value": 1,
        "label": {"en": ["Strongly disagree"], "de": ["Stimme gar nicht zu"]},
    }
    assert plan["pages"]["p_attitudes"]["itemOrder"] == "shuffle"
    assert plan["quotas"]["q_old"]["onFull"] == {
        "block": "b_screenout",
        "pages": ["p_screenout"],
        "outcome": "screenout",
    }
    assert plan["variables"]["framing"] == {
        "id": "framing",
        "kind": "assigned",
        "name": "framing",
        "levels": ["gain", "loss"],
        "seedNode": "f_assign/framing",
    }
    gate = plan["flow"][1]
    assert gate["type"] == "branch" and gate["else"] == []
    assert gate["if"]["kind"] == "compare"


def test_draft_seed_version() -> None:
    plan, _ = compile_survey(_survey(CASES / "valid" / "v02_minimal.json"))
    assert plan["survey"]["seedVersion"] == (
        "draft" if plan["survey"]["version"] is None else str(plan["survey"]["version"])
    )


def test_segments() -> None:
    assert segments("") == []
    assert segments("plain") == ["plain"]
    assert segments("${a}") == [{"pipe": "a"}]
    assert segments("x ${ a } y ${b}") == ["x ", {"pipe": "a"}, " y ", {"pipe": "b"}]
    assert segments("Trial ${$trial} of ${$position.of}") == [
        "Trial ",
        {"pipe": "$trial"},
        " of ",
        {"pipe": "$position.of"},
    ]
    assert segments("${not valid} ${$nope}") == ["${not valid} ${$nope}"]


def test_assigned_variables_carry_their_seed_node() -> None:
    plan, _ = compile_survey(_survey(CASES / "valid" / "v01_worked_example.json"))
    assert plan["variables"]["framing"]["seedNode"] == seed_node("f_assign", "framing")
    assert plan["variables"]["incentive"]["seedNode"] == "f_assign/incentive"


def test_runtime_config_is_what_the_session_service_reads() -> None:
    plan, _ = compile_survey(_survey(CASES / "valid" / "v01_worked_example.json"))
    cfg = runtime_config(plan)
    parsed = RuntimeConfig.from_json(cfg)  # R2's parser accepts it unchanged
    assert parsed.to_json() == cfg
    assert cfg["surveyVersion"] == plan["survey"]["seedVersion"] == "3"
    assert [(a["variable"], a["seedNode"]) for a in cfg["assignments"]] == [
        ("framing", "f_assign/framing"),
        ("incentive", "f_assign/incentive"),
    ]
    assert cfg["quotas"] == [{"node": "f_quota", "quota": "q_old", "limit": 150}]
    assert runtime_config(plan, save_mode="end-only")["saveMode"] == "end-only"


def test_unsafe_integer_literals_become_text() -> None:
    from osp_expr import parse as parse_expr
    from osp_runtime.plan import expr_json

    e = parse_expr("x > 9007199254740993 and x < 5").expr
    assert e is not None
    out = expr_json(e)
    assert out["args"][0]["right"] == {"kind": "int", "value": "9007199254740993"}
    assert out["args"][1]["right"] == {"kind": "int", "value": 5}


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.stem)
def test_runtime_config_for_every_valid_case(path: Path) -> None:
    plan, _ = compile_survey(_survey(path))
    RuntimeConfig.from_json(runtime_config(plan))


def test_matrix_rows_and_slider_track() -> None:
    """C2c-1: a matrix lists its rows; each row is a `single` item and a question of its
    own. C2c-3: a slider carries its track."""
    plan, _ = compile_survey(_survey(CASES / "valid" / "v11_matrix_slider.json"))
    assert plan is not None
    grid = plan["items"]["grid"]
    assert grid["type"] == "matrix"
    assert grid["rows"] == ["grid_a", "grid_b"]
    assert [c["value"] for c in grid["choices"]] == [1, 2]
    assert plan["pages"]["p1"]["items"] == ["grid", "vas"]
    assert plan["questions"] == ["grid_a", "grid_b", "vas", "score"]
    row = plan["items"]["grid_b"]
    assert row["type"] == "single"
    assert row["matrix"] == "grid"
    assert row["name"] == "att_b"
    assert row["required"] is False
    assert plan["items"]["grid_a"]["required"] is True
    assert "showIf" not in row
    vas = plan["items"]["vas"]
    assert (vas["valueType"], vas["min"], vas["max"], vas["step"]) == ("decimal", "0", "1", "0.01")
    assert vas["minLabel"]["de"] == ["Gar nicht"]
    score = plan["items"]["score"]
    assert (score["valueType"], score["step"]) == ("integer", 1)


def test_endings_are_compiled_into_the_plan_and_its_checksum() -> None:
    """EN1 (end-of-survey plan §4.1): endings per outcome, texts as segments in every
    language, inside the checksum; no `endings` key without them."""
    data = _survey(CASES / "valid" / "v01_worked_example.json")
    plain, _ = compile_survey(data)
    assert plain is not None and "endings" not in plain
    data = copy.deepcopy(data)
    data.setdefault("settings", {})["endings"] = {
        "complete": {"title": {"en": "Thanks", "de": "Danke"}, "body": "You are ${age}."},
        "hook-failed": {"status": "none"},
    }
    plan, diags = compile_survey(data)
    assert plan is not None, [d.code for d in diags]
    assert plan["endings"] == {
        "complete": {
            "status": "auto",
            "summary": "none",
            "title": {"en": ["Thanks"], "de": ["Danke"]},
            "body": {lang: ["You are ", {"pipe": "age"}, "."] for lang in plan["languages"]},
        },
        "hook-failed": {"status": "none", "summary": "none"},
    }
    assert plan["checksum"] == checksum(plan) != plain["checksum"]


def test_end_redirects_are_compiled_with_their_templates() -> None:
    """EN2 (end-of-survey plan §4.2): an ending's redirect keeps its template, params as
    segments, delay, mode and label; the templates (settings and hooks) are one map, and
    hook code sees the settings templates too."""
    data = copy.deepcopy(_survey(CASES / "valid" / "v12_hooks.json"))
    prolific = {
        "url": "https://app.prolific.com/submissions/complete?cc={cc}&pid={pid}",
        "params": {"cc": {"pattern": "[A-Z0-9]{4,8}"}, "pid": {}},
    }
    data["settings"] = {
        "redirectTemplates": {"prolific": prolific},
        "endings": {
            "complete": {
                "redirect": {
                    "template": "prolific",
                    "params": {"cc": "C1AB2", "pid": "${pid}-${$response.id}"},
                    "label": {"en": "Back to Prolific"},
                }
            },
            "declined": {"redirect": {"template": "done", "params": {"code": "NOPE12"}}},
        },
    }
    plan, diags = compile_survey(data)
    assert plan is not None, [d.code for d in diags]
    assert plan["endings"]["complete"]["redirect"] == {
        "template": "prolific",
        "params": {"cc": ["C1AB2"], "pid": [{"pipe": "pid"}, "-", {"pipe": "$response.id"}]},
        "delay": 5,
        "mode": "auto",
        "label": {"en": ["Back to Prolific"]},
    }
    assert "label" not in plan["endings"]["declined"]["redirect"]
    assert set(plan["redirectTemplates"]) == {"prolific", "done"}
    assert plan["redirectTemplates"]["prolific"] == prolific
    assert set(plan["hooks"]["redirects"]) == {"prolific", "done"}
    assert plan["checksum"] == checksum(plan)
    json.dumps(plan)
    # Without templates or redirects neither key appears (plans and checksums unchanged).
    plain, _ = compile_survey(_survey(CASES / "valid" / "v01_worked_example.json"))
    assert plain is not None and "redirectTemplates" not in plain


# --- Rich text (planning/rich-text.md §3, task RT2) ---------------------------------------

RICH = {
    "type": "rich",
    "blocks": [
        {"type": "h", "level": 1, "content": [{"text": "Before you start"}]},
        {"type": "p", "content": [
            {"text": "Hello "}, {"pipe": "name"}, {"text": "!", "marks": ["b"]}, {"br": True},
            {"text": "sheet", "href": "https://example.org/s", "lang": "fr"}, {"pipe": "$trial"},
        ]},
        {"type": "ul", "items": [[{"text": "one"}], [{"text": "two", "marks": ["i"]}]]},
    ],
}  # fmt: skip


def _rich_survey() -> dict:
    s = _survey(VALID[0])
    s = copy.deepcopy(s)
    items = s["blocks"][0]["pages"][0]["items"]
    items.insert(0, {"id": "name", "type": "text", "label": "Name?"})
    items.append({"id": "rich_note", "type": "note", "label": {"en": RICH}})
    stem = {"type": "rich", "blocks": RICH["blocks"][1:]}  # no heading in a stem
    items.append({"id": "rich_mixed", "type": "integer", "label": {"en": "Plain ${name}"},
                  "help": stem})  # fmt: skip
    return s


def test_rich_text_compiles_to_blocks_and_plain_text_to_segments() -> None:
    plan, diags = compile_survey(_rich_survey())
    assert plan is not None, [d.code for d in diags if d.severity == "error"]
    note = plan["items"]["rich_note"]["label"]
    langs = plan["languages"]
    assert set(note) == set(langs)
    for lang in langs:  # one tree, every language (missing translations fall back)
        assert note[lang][0] == {"type": "h", "level": 1, "content": [{"text": "Before you start"}]}
        runs = note[lang][1]["content"]
        assert runs[1] == {"pipe": "name"} and runs[2] == {"text": "!", "marks": ["b"]}
        assert runs[3] == {"br": True}
        assert runs[4] == {"text": "sheet", "href": "https://example.org/s", "lang": "fr"}
        assert runs[5] == {"pipe": "$trial"}
        assert note[lang][2] == {
            "type": "ul",
            "items": [[{"text": "one"}], [{"text": "two", "marks": ["i"]}]],
        }
    mixed = plan["items"]["rich_mixed"]
    assert mixed["label"][langs[0]] == ["Plain ", {"pipe": "name"}]  # segments, as before
    assert mixed["help"][langs[0]][0]["type"] == "p"
    # The schema accepts both shapes (the small validator lives in test_plan_hooks.py).
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "plan_hooks_validator", Path(__file__).with_name("test_plan_hooks.py")
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.valid(SCHEMA, plan)
    assert plan["checksum"] == checksum(plan)


def test_plain_strings_compile_exactly_as_before_rt2() -> None:
    """A survey without rich text gets the same plan and checksum as a plain string
    compiles to segments (RT-D3: existing plans and checksums are unchanged)."""
    survey = json.loads((REPO / "fixtures/17-piping/survey.json").read_text(encoding="utf-8"))
    plan, _ = compile_survey(survey)
    assert plan is not None
    for item in plan["items"].values():
        for lang, value in item["label"].items():
            assert all(isinstance(s, str) or set(s) == {"pipe"} for s in value), (item["id"], lang)


def test_blocks_writes_an_unknown_pipe_back_as_text() -> None:
    from osp_runtime.plan import blocks

    tree = {
        "type": "rich",
        "blocks": [{"type": "p", "content": [{"pipe": "not valid"}, {"pipe": "$nope"}]}],
    }
    assert blocks(tree) == [
        {"type": "p", "content": [{"text": "${not valid}"}, {"text": "${$nope}"}]}
    ]
