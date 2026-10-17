"""The simulation report on hand-made plans and results (pure: no sidecar)."""

from __future__ import annotations

from typing import Any

from osp_qa import REPORT_FORMAT, build_report

PLAN: dict[str, Any] = {
    "items": {
        "q1": {"id": "q1", "type": "single", "required": True},
        "q2": {"id": "q2", "type": "text", "required": True},
    },
    "questions": ["q1", "q2"],
    "pages": {"p1": {"id": "p1"}, "p2": {"id": "p2"}},
    "variables": {"cond": {"id": "cond", "kind": "assigned", "levels": ["a", "b"]}},
    "flow": [
        {"type": "block", "id": "n1", "block": "b1", "pages": ["p1"]},
        {"type": "assign", "id": "as", "variables": ["cond"]},
        {
            "type": "branch",
            "id": "br",
            "if": {"kind": "bool", "value": False},
            "then": [
                {"type": "block", "id": "n2", "block": "b2", "pages": ["p2"]},
                {"type": "end", "id": "end_x", "outcome": "x"},
            ],
            "else": [],
        },
        {
            "type": "randomiser",
            "id": "r",
            "pick": None,
            "children": [
                {"type": "block", "id": "c1", "block": "b1", "pages": []},
                {"type": "block", "id": "c2", "block": "b1", "pages": []},
            ],
        },
    ],
}


def _stats(runs: int, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "runs": runs,
        "outcomes": {"complete": runs},
        "ends": {"end_x": 0},
        "stuck": {},
        "nodes": {
            "n1": runs,
            "as": runs,
            "br": runs,
            "n2": 0,
            "end_x": 0,
            "r": runs,
            "c1": runs,
            "c2": runs,
        },
        "pages": {"p1": {"reached": runs, "shown": runs}, "p2": {"reached": 0, "shown": 0}},
        "questions": {
            "q1": {"answered": runs, "unanswered": 0, "irrelevant": 0, "not-reached": 0},
            "q2": {"answered": 0, "unanswered": 0, "irrelevant": 0, "not-reached": runs},
        },
        "branches": {"br": {"then": 0, "else": runs, "undetermined": 0}},
        "randomisers": {
            "r": {
                "reached": runs,
                "orders": {"c1,c2": runs // 2, "c2,c1": runs - runs // 2},
                "positions": {"c1": [runs // 2, 0], "c2": [runs - runs // 2, 0]},
            }
        },
        "assignments": {"cond": {"a": runs // 2, "b": runs - runs // 2}},
        "quotas": {},
        "diagnostics": {},
        "paths": {"distinct": 1, "top": [{"pages": ["p1"], "end": "complete@x", "count": runs}]},
    }
    return base | over


def _result(sample: dict, exhaustive: dict | None) -> dict[str, Any]:
    return {
        "format": "osp-sim/1",
        "planChecksum": "sha256:x",
        "options": {"n": sample["runs"], "seed": 3, "answerStrategy": "uniform", "quotaFull": 0.1},
        "coverage": "exhaustive" if exhaustive else "sampled",
        "pathSpace": {
            "exhaustive": bool(exhaustive),
            "paths": 1 if exhaustive else None,
            "combinations": 2 if exhaustive else None,
            "randomiserOrders": 2,
            "assignmentCombinations": 2,
            "reasons": [] if exhaustive else ["text question q9 is used in a condition"],
        },
        "sample": sample,
        "exhaustive": exhaustive,
    }


def _codes(report: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for w in report["warnings"]:
        out.setdefault(w["code"], []).append(w)
    return out


def test_exhaustive_unreachable_branch_is_certain():
    report = build_report(PLAN, _result(_stats(1000), _stats(4)))
    assert report["format"] == REPORT_FORMAT
    assert report["coverage"] == "exhaustive"
    w = _codes(report)
    [arm] = w["branch.arm_never_taken"]
    assert arm["target"] == "br.then" and arm["certain"] is True
    assert "never taken on any enumerated path" in arm["message"]
    # Nodes inside the never-taken arm are not reported again.
    assert "node.unreachable" not in w and "end.never_reached" not in w
    [req] = w["question.required_never_shown"]
    assert req["target"] == "q2" and req["certain"]
    assert "coverage.sampled" not in w
    assert {n["id"]: n["covered"] for n in report["nodes"]}["n2"] is False
    assert report["pathSpace"]["paths"] == 1


def test_sampled_coverage_says_so():
    report = build_report(PLAN, _result(_stats(1000), None))
    w = _codes(report)
    assert report["coverage"] == "sampled"
    assert w["branch.arm_never_taken"][0]["certain"] is False
    assert "may still be possible" in w["branch.arm_never_taken"][0]["message"]
    assert "text question q9" in w["coverage.sampled"][0]["message"]
    assert report["pathSpace"]["paths"] is None


def test_balance_checks_flag_imbalance_only():
    report = build_report(PLAN, _result(_stats(1000), None))
    [a] = report["assignments"]
    assert a["balanced"] is True and a["pValue"] == 1.0 and a["test"] == "levels"
    [r] = report["randomisers"]
    assert r["test"] == "orders" and r["balanced"] is True and r["possibleOrders"] == 2
    skewed = _stats(1000, assignments={"cond": {"a": 600, "b": 400}})
    skewed["randomisers"]["r"]["orders"] = {"c1,c2": 1000}
    report = build_report(PLAN, _result(skewed, None))
    w = _codes(report)
    assert w["assignment.imbalanced"][0]["target"] == "cond"
    assert w["randomiser.imbalanced"][0]["target"] == "r"
    assert report["randomisers"][0]["observedOrders"] == 1


def test_few_participants_are_not_tested():
    report = build_report(PLAN, _result(_stats(6), None))
    assert report["assignments"][0]["balanced"] is None
    assert report["randomisers"][0]["test"] is None


def test_stuck_and_diagnostics_are_reported():
    sample = _stats(
        10, stuck={"p1": 3}, diagnostics={"division-by-zero flow.br.if": 2}, outcomes={"stuck": 3}
    )
    w = _codes(build_report(PLAN, _result(sample, None)))
    assert w["participants.stuck"][0]["severity"] == "error"
    assert w["runtime.diagnostic"][0]["target"] == "flow.br.if"


def test_never_crashes_on_junk():
    for junk in ({}, {"sample": None}, {"sample": {"nodes": [1, 2]}, "exhaustive": "x"}):
        report = build_report(PLAN, junk)
        assert report["coverage"] == "sampled"
    assert build_report({}, {})["nodes"] == []
