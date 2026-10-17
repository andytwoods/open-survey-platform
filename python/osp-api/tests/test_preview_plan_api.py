"""POST /api/surveys/{id}/preview-plan (task B11): draft plan, permissions, no publish."""

from __future__ import annotations

import json
from pathlib import Path

from osp_store import TenantContext

REPO = Path(__file__).resolve().parents[3]


def _fixture(name: str) -> dict:
    return json.loads((REPO / f"fixtures/{name}/survey.json").read_text("utf-8"))


def _survey(benv, survey: dict) -> str:
    c = benv.login("owner@a.example")
    r = c.post("/api/surveys", json={"title": "Preview", "survey": survey})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_editor_gets_a_draft_plan(benv):
    sid = _survey(benv, _fixture("05-showif-null"))
    c = benv.login("editor@a.example")
    r = c.post(f"/api/surveys/{sid}/preview-plan")
    assert r.status_code == 200, r.text
    body = r.json()
    plan = body["plan"]
    assert plan["planVersion"] == "osp-runtime-plan/1"
    assert plan["survey"]["seedVersion"] == "draft"
    assert plan["checksum"].startswith("sha256:")
    assert "theme" in plan  # looks like the participant page
    assert body["revision"] >= 0 and body["surveyId"] == sid
    shows = {k: v for k, v in body["conditions"].items() if k.endswith(".showIf")}
    assert shows, body["conditions"]
    # Nothing was published.
    ctx = TenantContext(benv.tenants["A"], "test")
    assert benv.store.list_versions(ctx, sid) == []


def test_published_version_number_is_ignored(benv):
    survey = {**_fixture("13-randomiser-blocks"), "version": 3}
    sid = _survey(benv, survey)
    r = benv.login("editor@a.example").post(f"/api/surveys/{sid}/preview-plan")
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["survey"]["seedVersion"] == "draft"


def test_draft_with_errors_returns_diagnostics(benv):
    survey = _fixture("05-showif-null")
    survey["flow"] = [{"type": "block", "id": "n_x", "block": "missing_block"}]
    sid = _survey(benv, survey)
    r = benv.login("owner@a.example").post(f"/api/surveys/{sid}/preview-plan")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan"] is None
    assert any(d["severity"] == "error" for d in body["diagnostics"])


def test_permissions(benv):
    sid = _survey(benv, _fixture("05-showif-null"))
    url = f"/api/surveys/{sid}/preview-plan"
    assert benv.login("viewer@a.example").post(url).status_code == 403
    assert benv.login("owner@b.example").post(url).status_code == 404
    assert benv.client().post(url).status_code == 401
