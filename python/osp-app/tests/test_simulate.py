"""Simulator end to end on the fixtures (task M1): survey → plan → Node sidecar (the TS
engine) → osp-qa report. Needs node and web/engine-sim/dist/cli.js (`make sim-build`,
which `make py-test` runs first)."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from osp_qa import build_report
from osp_runtime.plan import compile_survey
from osp_runtime.sim_sidecar import DEFAULT_CLI, simulate_plan

REPO = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not DEFAULT_CLI.is_file(),
    reason="needs node and web/engine-sim/dist/cli.js (make sim-build)",
)


def _survey(fixture: str) -> dict[str, Any]:
    return json.loads((REPO / "fixtures" / fixture / "survey.json").read_text(encoding="utf-8"))


def _report(survey: dict[str, Any], **options: Any) -> dict[str, Any]:
    plan, diags = compile_survey(survey)
    assert plan is not None, diags
    result = simulate_plan(plan, {"seed": 1, **options})
    return build_report(plan, result)


def _codes(report: dict[str, Any]) -> set[str]:
    return {w["code"] for w in report["warnings"]}


def test_fixture_13_randomiser_orders_are_balanced_at_5000():
    report = _report(_survey("13-randomiser-blocks"), n=5000, seed=13)
    [r] = report["randomisers"]
    assert r["id"] == "r_blocks"
    assert r["reached"] == 5000
    assert r["possibleOrders"] == 6 and r["observedOrders"] == 6
    assert r["test"] == "orders" and r["df"] == 5
    assert r["balanced"] is True and r["pValue"] > 0.001
    assert r["maxDeviation"] < 0.10  # every order within 10% of 5000/6
    assert report["coverage"] == "exhaustive"
    assert report["pathSpace"]["paths"] == 6
    assert "randomiser.imbalanced" not in _codes(report)


def test_fixture_16_assignment_is_balanced():
    report = _report(_survey("16-assign"), n=4000)
    [a] = report["assignments"]
    assert a["variable"] == "cond" and a["reached"] == 4000
    assert a["balanced"] is True


def test_fixture_11_reaches_every_end():
    report = _report(_survey("11-end-nodes"), n=2000)
    ends = {e["id"]: e for e in report["ends"]}
    assert set(ends) == {"end_ineligible", "end_early_exit", "end_complete"}
    assert all(e["covered"] and e["reached"] > 0 for e in ends.values())
    assert report["coverage"] == "exhaustive"
    assert report["pathSpace"] == {
        "exhaustive": True,
        "paths": 3,
        "combinations": 4,
        "randomiserOrders": 1,
        "assignmentCombinations": 1,
        "reasons": [],
    }
    assert sum(report["outcomes"].values()) == 2000
    assert not _codes(report) & {"end.never_reached", "node.unreachable", "participants.stuck"}


def test_deliberately_unreachable_branch_is_flagged():
    survey = copy.deepcopy(_survey("11-end-nodes"))
    branch = next(n for n in survey["flow"] if n.get("id") == "branch_2")
    rating = {"kind": "ref", "id": "rating"}
    # rating < 3 and rating > 5: no answer satisfies both.
    branch["if"] = {
        "kind": "and",
        "args": [
            {"kind": "compare", "op": "<", "left": rating, "right": {"kind": "int", "value": 3}},
            {"kind": "compare", "op": ">", "left": rating, "right": {"kind": "int", "value": 5}},
        ],
    }
    report = _report(survey, n=1000)
    assert report["coverage"] == "exhaustive"
    [w] = [w for w in report["warnings"] if w["code"] == "branch.arm_never_taken"]
    assert w["target"] == "branch_2.then"
    assert w["certain"] is True
    assert {e["id"]: e["covered"] for e in report["ends"]}["end_early_exit"] is False


def test_sampled_fixture_is_labelled_sampled():
    report = _report(_survey("19-expressions"), n=200)
    assert report["coverage"] == "sampled"
    assert report["pathSpace"]["paths"] is None
    assert any(w["code"] == "coverage.sampled" for w in report["warnings"])
