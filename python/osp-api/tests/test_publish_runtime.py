"""Publish -> runtime, end to end over HTTP (task R2b): create a survey, apply ops,
publish, start a participant session, fetch the plan, and check the checksum."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import get_args

from osp_runtime.plan import canonical_json
from osp_spec.model import Retention
from osp_spec.theme import PRESETS
from osp_store import TenantContext

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
SET_TITLE = {"op": "set_title", "params": {"title": {"en": "Mood study"}}}
# Publishing needs an explicit retention policy (semantics decisions, 16 Oct 2026).
RETENTION = {
    "op": "set_property",
    "params": {"target": "/settings", "property": "retention", "value": {"kind": "indefinite"}},
}


def _plan_checksum(plan: dict) -> str:
    body = {k: v for k, v in plan.items() if k != "checksum"}
    return "sha256:" + hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def test_create_ops_publish_start_fetch_plan(benv):
    c = benv.login("editor@a.example")
    s = c.post("/api/surveys", json={"title": "First"}).json()
    assert s["publicSlug"]  # generated at creation
    ops = {"ops": [SET_TITLE, RETENTION], "baseRevision": 0}
    r = c.post(f"/api/surveys/{s['id']}/ops", json=ops)
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
    no_retention = c.post(f"/api/surveys/{s['id']}/publish")
    assert no_retention.status_code == 422
    assert "publish.retention_required" in no_retention.text
    c.post(f"/api/surveys/{s['id']}/ops", json={"ops": [RETENTION], "baseRevision": 0})
    v1 = c.post(f"/api/surveys/{s['id']}/publish").json()
    participant = benv.client()
    old = participant.post(f"/api/s/{v1['slug']}/sessions").json()

    c.post(f"/api/surveys/{s['id']}/ops", json={"ops": [SET_TITLE], "baseRevision": 1})
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
    survey["settings"] = {**survey.get("settings", {}), "retention": {"kind": "indefinite"}}
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


def _publishable(c) -> str:
    s = c.post("/api/surveys", json={"title": "Themed"}).json()
    r = c.post(f"/api/surveys/{s['id']}/ops", json={"ops": [RETENTION], "baseRevision": 0})
    assert r.status_code == 200, r.text
    return s["id"]


def _preset(name: str) -> dict:
    return PRESETS[name].model_dump(mode="json", by_alias=True)


def test_publish_embeds_the_clean_preset_when_the_lab_has_no_default(benv):
    c = benv.login("editor@a.example")
    pub = c.post(f"/api/surveys/{_publishable(c)}/publish").json()
    plan = benv.client().get(pub["planUrl"]).json()
    assert plan["theme"] == _preset("clean")
    assert plan["checksum"] == _plan_checksum(plan) == pub["planChecksum"]


def test_publish_embeds_the_lab_default_theme(benv):
    ctx = TenantContext(benv.tenants["A"], "test")
    warm = _preset("warm")
    benv.store.set_lab_default_theme(ctx, benv.store.create_theme(ctx, "Warm", warm).id)
    c = benv.login("editor@a.example")
    pub = c.post(f"/api/surveys/{_publishable(c)}/publish").json()
    plan = benv.client().get(pub["planUrl"]).json()
    assert plan["theme"]["preset"] == "warm" and plan["theme"] == warm


def test_a_theme_failing_the_contrast_guard_blocks_publish(benv):
    ctx = TenantContext(benv.tenants["A"], "test")
    bad = _preset("clean")
    bad["colours"]["light"]["text"] = "#f0f0f0"  # light grey on white
    benv.store.set_lab_default_theme(ctx, benv.store.create_theme(ctx, "Pale", bad).id)
    c = benv.login("editor@a.example")
    sid = _publishable(c)
    r = c.post(f"/api/surveys/{sid}/publish")
    assert r.status_code == 422
    body = r.json()
    assert "accessibility" in body["message"]
    assert {d["code"] for d in body["diagnostics"]} == {"theme.contrast"}
    first = body["diagnostics"][0]
    assert first["pointer"].startswith("/labTheme/colours/light/")
    assert "'Pale'" in first["message"] and "Nearest passing value" in first["message"]
    assert benv.store.list_versions(ctx, sid) == []  # nothing was frozen


def test_missing_retention_is_named_in_the_publish_error(benv):
    c = benv.login("editor@a.example")
    s = c.post("/api/surveys", json={"title": "First"}).json()
    r = c.post(f"/api/surveys/{s['id']}/publish")
    assert r.status_code == 422
    body = r.json()
    assert body["message"].startswith("Choose how long participant data is kept")
    (d,) = [d for d in body["diagnostics"] if d["code"] == "publish.retention_required"]
    assert d["pointer"] == "/settings/retention" and d["severity"] == "error"


def test_meta_lists_the_retention_options(benv):
    c = benv.login("viewer@a.example")
    r = c.get("/api/meta/retention")
    assert r.status_code == 200
    body = r.json()
    assert body["required"] is True and body["pointer"] == "/settings/retention"
    kinds = {k["kind"]: k["field"] for k in body["kinds"]}
    assert kinds == {"days-after-close": "days", "after-date": "until", "indefinite": None}
    assert set(kinds) == set(get_args(Retention.model_fields["kind"].annotation))
    assert benv.client().get("/api/meta/retention").status_code == 401
