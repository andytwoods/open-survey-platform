"""Tests for osp_runtime.plan: the survey → runtime plan compiler (task R1)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from osp_runtime.plan import (
    ENGINE_VERSION,
    PLAN_VERSION,
    PlanError,
    canonical_json,
    checksum,
    compile_plan,
    compile_survey,
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
    assert set(plan) == set(SCHEMA["required"])
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
