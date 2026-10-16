"""Publish -> runtime, end to end over HTTP (task R2b): create a survey, apply ops,
publish, start a participant session, fetch the plan, and check the checksum."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from osp_runtime.plan import canonical_json
from osp_store import TenantContext

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
SET_TITLE = {"op": "set_title", "params": {"title": {"en": "Mood study"}}}


def _plan_checksum(plan: dict) -> str:
    body = {k: v for k, v in plan.items() if k != "checksum"}
    return "sha256:" + hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def test_create_ops_publish_start_fetch_plan(benv):
    c = benv.login("editor@a.example")
    s = c.post("/api/surveys", json={"title": "First"}).json()
    assert s["publicSlug"]  # generated at creation
    r = c.post(f"/api/surveys/{s['id']}/ops", json={"ops": [SET_TITLE], "baseRevision": 0})
    assert r.status_code == 200, r.text

    pub = c.post(f"/api/surveys/{s['id']}/publish", json={"baseRevision": 1})
    assert pub.status_code == 201, pub.text
    pub = pub.json()
    assert pub["slug"] == s["publicSlug"] and pub["saveMode"] == "every-page"

    participant = benv.client()  # no researcher cookie
    st = participant.post(f"/api/s/{pub['slug']}/sessions")
    assert st.status_code == 201, st.text
    st = st.json()
    assert st["planChecksum"] == pub["planChecksum"] and st["planUrl"] == pub["planUrl"]

    got = participant.get(st["planUrl"])
    assert got.status_code == 200
    assert "immutable" in got.headers["cache-control"]
    plan = got.json()
    assert plan["checksum"] == st["planChecksum"] == _plan_checksum(plan)
    assert plan["title"] == {"en": ["Mood study"]}  # the op landed in the published plan
    assert plan["survey"]["version"] == 1 and plan["survey"]["seedVersion"] == "1"

    # The version keeps the plan checksum, runtime config and the XLSForm artefact.
    ctx = TenantContext(benv.tenants["A"], "test")
    (version,) = benv.store.list_versions(ctx, s["id"])
    assert version.body["version"] == 1
    assert version.meta["planChecksum"] == plan["checksum"]
    assert version.meta["runtimeConfig"]["surveyVersion"] == "1"
    assert version.meta["xform"] == "xlsform" and version.xform[:2] == b"PK"


def test_republish_keeps_the_slug_and_old_plans_stay_servable(benv):
    c = benv.login("editor@a.example")
    s = c.post("/api/surveys", json={"title": "First"}).json()
    v1 = c.post(f"/api/surveys/{s['id']}/publish").json()
    participant = benv.client()
    old = participant.post(f"/api/s/{v1['slug']}/sessions").json()

    c.post(f"/api/surveys/{s['id']}/ops", json={"ops": [SET_TITLE], "baseRevision": 0})
    v2 = c.post(f"/api/surveys/{s['id']}/publish", json={"saveMode": "end-only"}).json()
    assert v2["slug"] == v1["slug"] and v2["planChecksum"] != v1["planChecksum"]

    new = participant.post(f"/api/s/{v2['slug']}/sessions").json()
    assert new["planChecksum"] == v2["planChecksum"] and new["saveMode"] == "end-only"
    # A session already running on version 1 can still fetch its plan.
    assert participant.get(old["planUrl"]).json()["checksum"] == v1["planChecksum"]
    assert participant.get(f"/api/s/{v1['slug']}/plan/sha256:nope").status_code == 404


def test_fixture_with_assignment_publishes_a_runnable_config(benv):
    c = benv.login("editor@a.example")
    survey = json.loads((FIXTURES / "16-assign" / "survey.json").read_text())
    s = c.post("/api/surveys", json={"title": "Assign", "survey": survey})
    assert s.status_code == 201, s.text
    pub = c.post(f"/api/surveys/{s.json()['id']}/publish").json()
    st = benv.client().post(f"/api/s/{pub['slug']}/sessions").json()
    assert st["assigned"]["cond"] in ("control", "treatment")
    plan = benv.client().get(st["planUrl"]).json()
    assert plan["variables"]["cond"]["seedNode"] == "assign_design/cond"


def test_publish_rejects_a_bad_save_mode_and_unknown_slugs_404(benv):
    c = benv.login("editor@a.example")
    s = c.post("/api/surveys", json={"title": "First"}).json()
    r = c.post(f"/api/surveys/{s['id']}/publish", json={"saveMode": "never"})
    assert r.status_code == 422
    assert benv.client().post(f"/api/s/{s['publicSlug']}/sessions").status_code == 404
