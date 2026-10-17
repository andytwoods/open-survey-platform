"""POST /api/surveys/{id}/simulate (task M1): permissions, limits, report shape."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from osp_runtime.sim_sidecar import DEFAULT_CLI

REPO = Path(__file__).resolve().parents[3]
SURVEY = json.loads((REPO / "fixtures/13-randomiser-blocks/survey.json").read_text("utf-8"))
needs_cli = pytest.mark.skipif(
    shutil.which("node") is None or not DEFAULT_CLI.is_file(),
    reason="needs node and web/engine-sim/dist/cli.js (make sim-build)",
)


def _survey(benv) -> str:
    c = benv.login("owner@a.example")
    r = c.post("/api/surveys", json={"title": "Randomiser", "survey": SURVEY})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@needs_cli
def test_editor_simulates_the_draft(benv):
    sid = _survey(benv)
    c = benv.login("editor@a.example")
    r = c.post(f"/api/surveys/{sid}/simulate", json={"n": 600, "seed": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["format"] == "osp-sim-report/1"
    assert body["surveyId"] == sid and body["participants"] == 600
    assert body["coverage"] == "exhaustive" and body["pathSpace"]["paths"] == 6
    [rand] = body["randomisers"]
    assert rand["id"] == "r_blocks" and rand["reached"] == 600 and rand["possibleOrders"] == 6
    assert {"id", "type", "reached", "covered"} <= set(body["nodes"][0])
    assert body["outcomes"] == {"complete": 600}
    # Same request, same report.
    assert c.post(f"/api/surveys/{sid}/simulate", json={"n": 600, "seed": 5}).json() == body


@needs_cli
def test_weights_strategy(benv):
    sid = _survey(benv)
    c = benv.login("editor@a.example")
    weights = {"intro_q": {"": 1}}
    r = c.post(
        f"/api/surveys/{sid}/simulate",
        json={"n": 50, "answerStrategy": "weights", "weights": weights},
    )
    assert r.status_code == 200, r.text
    q = {x["id"]: x for x in r.json()["questions"]}["intro_q"]
    assert q["states"]["answered"] == 0


def test_permissions(benv):
    sid = _survey(benv)
    assert (
        benv.login("viewer@a.example").post(f"/api/surveys/{sid}/simulate", json={}).status_code
        == 403
    )
    assert (
        benv.login("owner@b.example").post(f"/api/surveys/{sid}/simulate", json={}).status_code
        == 404
    )
    assert benv.client().post(f"/api/surveys/{sid}/simulate", json={}).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"n": 10_001},
        {"n": 0},
        {"seed": -1},
        {"answerStrategy": "random"},
        {"quotaFull": 2},
        {"extra": 1},
        {"answerStrategy": "uniform", "weights": {"q": {"a": 1}}},
        {"answerStrategy": "weights"},
    ],
)
def test_bad_requests_are_422(benv, body):
    sid = _survey(benv)
    r = benv.login("editor@a.example").post(f"/api/surveys/{sid}/simulate", json=body)
    assert r.status_code == 422, r.text


def test_simulator_unavailable_is_503(benv, monkeypatch, tmp_path):
    sid = _survey(benv)
    monkeypatch.setenv("OSP_SIM_CLI", str(tmp_path / "missing.js"))
    r = benv.login("editor@a.example").post(f"/api/surveys/{sid}/simulate", json={"n": 5})
    assert r.status_code == 503
    assert r.json()["code"] == "unavailable"
