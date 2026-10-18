"""DEMO2: the serverless Pages demo's prespecified study and its generated data.

The study (web/builder/demo-site/study.json) is what the demo builder opens and what "Take
the study" runs. It must be a valid osp-survey with no diagnostics at all, compile to a
runtime plan, and show off the features the home page promises. scripts/demo_data.py turns
the real API's answers into the demo's static data file; it must keep working.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from osp_runtime.plan import compile_survey
from osp_spec import validate

REPO = Path(__file__).resolve().parents[1]
STUDY = REPO / "web" / "builder" / "demo-site" / "study.json"


def _study() -> dict[str, Any]:
    return json.loads(STUDY.read_text(encoding="utf-8"))


def _items(survey: dict[str, Any]) -> list[dict[str, Any]]:
    return [q for b in survey["blocks"] for p in b["pages"] for q in p["items"]]


def _nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for n in nodes:
        out.append(n)
        out += _nodes(n.get("then", []) + n.get("else", []) + n.get("children", []))
    return out


def test_study_is_valid_with_no_diagnostics() -> None:
    assert validate(_study()) == []


def test_study_compiles_to_a_plan() -> None:
    plan, diagnostics = compile_survey({**_study(), "version": None})
    assert diagnostics == []
    assert plan is not None
    assert plan["survey"]["seedVersion"] == "draft"
    assert plan["languages"] == ["en", "de"]


def test_study_uses_the_features_the_demo_shows() -> None:
    s = _study()
    items = _items(s)
    types = {q["type"] for q in items}
    assert {
        "integer",
        "decimal",
        "text",
        "single",
        "multi",
        "date",
        "matrix",
        "slider",
        "note",
    } <= types
    assert any("showIf" in q for q in items)
    assert any(q.get("choiceOrder") == "shuffle" for q in items)
    assert any("${" in str(q.get("label")) for q in items)  # piping
    kinds = {n["type"] for n in _nodes(s["flow"])}
    assert {"branch", "randomiser", "end"} <= kinds
    assert s["metadata"]["languages"] == ["en", "de"]
    assert s["consent"]["declineOutcome"] == "declined"
    assert set(s["settings"]["endings"]) == {"complete", "too_young", "declined"}
    assert s["settings"]["theme"]["preset"] == "warm"
    # Every participant-facing label is translated.
    for q in items:
        assert set(q["label"]) == {"en", "de"}, q["id"]


def test_demo_data_comes_from_the_real_api(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "osp_demo_data", REPO / "scripts" / "demo_data.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out = tmp_path / "demo-data.json"
    assert module.main(["--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["get"]["/api/health"] == {"status": "ok"}
    assert "schemas" in data["get"]["/api/meta/property-schemas"]
    bundled = {s["id"] for s in data["get"]["/api/bank/library"]}
    assert {"phq9", "gad7"} <= bundled
    assert bundled == set(data["bankItems"])
    assert {i["id"] for i in data["bankList"]["items"]} >= bundled
    assert "clean" in data["presets"]
