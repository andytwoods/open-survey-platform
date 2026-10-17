"""Researcher hooks end to end over HTTP (task R11, runtime-design.md §7a): `set_hooks` is an
audited code change only owners and editors may make, the draft's hooks reach the preview
plan, publishing puts them inside the served plan and its checksum, and the exports report
them as not exported."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from osp_runtime.plan import canonical_json
from osp_store import TenantContext

REPO = Path(__file__).resolve().parents[3]
FIXTURE = json.loads((REPO / "fixtures/05-showif-null/survey.json").read_text("utf-8"))
RETENTION = {
    "op": "set_property",
    "params": {"target": "/settings", "property": "retention", "value": {"kind": "indefinite"}},
}
HOOKS = {
    "format": "osp-hooks/1",
    "source": "osp.on('onPageShown', function (ctx, d, act) { act.addParadata('t', ctx.trial); });",
    "handlers": {"onPageShown": {"reads": ["a"], "writes": []}},
}


def _create(benv, who: str = "owner@a.example") -> tuple[object, dict]:
    c = benv.login(who)
    r = c.post("/api/surveys", json={"title": "Hooks", "survey": FIXTURE})
    assert r.status_code == 201, r.text
    return c, r.json()


def _ops(c, s: dict, ops: list[dict], base: int):
    return c.post(f"/api/surveys/{s['id']}/ops", json={"ops": ops, "baseRevision": base})


def _audit(benv, action: str) -> list:
    ctx = TenantContext(benv.tenants["A"], "test")
    return [a for a in benv.store.list_audit(ctx) if a.action == action]


def test_set_hooks_is_audited_as_a_code_change(benv):
    c, s = _create(benv, "editor@a.example")
    r = _ops(c, s, [{"op": "set_hooks", "params": {"hooks": HOOKS}}], 0)
    assert r.status_code == 200, r.text
    assert r.json()["patch"] == [{"op": "add", "path": "/hooks", "value": HOOKS}]
    rows = _audit(benv, "survey.hooks_changed")
    assert len(rows) == 1 and rows[0].target_id == s["id"]
    detail = rows[0].detail
    expected = "sha256:" + hashlib.sha256(HOOKS["source"].encode()).hexdigest()
    assert detail["before"] is None
    assert detail["after"]["sourceChecksum"] == expected
    assert detail["after"]["events"] == ["onPageShown"]
    assert detail["ops"] == ["set_hooks"] and detail["kind"] == "edit"
    assert HOOKS["source"] not in json.dumps(detail)  # the code itself is not copied
    # Other edits are not hook changes; removing the manifest is one.
    assert _ops(c, s, [RETENTION], 1).status_code == 200
    assert len(_audit(benv, "survey.hooks_changed")) == 1
    assert _ops(c, s, [{"op": "set_hooks", "params": {"hooks": None}}], 2).status_code == 200
    rows = _audit(benv, "survey.hooks_changed")
    assert len(rows) == 2 and rows[1].detail["after"] is None
    # Undo of that removal is audited too (it brings the code back).
    txn = rows[1].detail["transaction"]
    u = c.post(f"/api/surveys/{s['id']}/undo", json={"transactionId": txn, "baseRevision": 3})
    assert u.status_code == 200, u.text
    rows = _audit(benv, "survey.hooks_changed")
    assert len(rows) == 3 and rows[2].detail["kind"] == "undo"
    assert rows[2].detail["after"]["sourceChecksum"] == expected


def test_viewers_may_not_set_hooks(benv):
    _, s = _create(benv)
    v = benv.login("viewer@a.example")
    assert _ops(v, s, [{"op": "set_hooks", "params": {"hooks": HOOKS}}], 0).status_code == 403
    assert _audit(benv, "survey.hooks_changed") == []


def test_a_malformed_manifest_is_refused_with_a_pointer(benv):
    c, s = _create(benv)
    bad = {**HOOKS, "handlers": {"onExplode": {"reads": [], "writes": []}}}
    r = _ops(c, s, [{"op": "set_hooks", "params": {"hooks": bad}}], 0)
    assert r.status_code == 422, r.text
    diags = r.json()["diagnostics"]
    assert diags[0]["code"] == "op.invalid_result"
    assert diags[0]["pointer"].startswith("/hooks/handlers")
    assert _audit(benv, "survey.hooks_changed") == []


def test_draft_hooks_reach_the_preview_plan_and_reference_errors_block_it(benv):
    c, s = _create(benv)
    assert _ops(c, s, [{"op": "set_hooks", "params": {"hooks": HOOKS}}], 0).status_code == 200
    r = c.post(f"/api/surveys/{s['id']}/preview-plan")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan"]["hooks"] == HOOKS
    assert body["plan"]["checksum"].startswith("sha256:")
    # A handler reading an unknown id: the op lands (a draft may be mid-edit), the preview
    # plan does not build, and the diagnostic points at the read.
    broken = {**HOOKS, "handlers": {"onPageShown": {"reads": ["a", "nope"], "writes": []}}}
    r = _ops(c, s, [{"op": "set_hooks", "params": {"hooks": broken}}], 1)
    assert r.status_code == 200, r.text
    found = [d for d in r.json()["diagnostics"] if d["code"] == "hooks.unknown_ref"]
    assert [d["pointer"] for d in found] == ["/hooks/handlers/onPageShown/reads/1"]
    r = c.post(f"/api/surveys/{s['id']}/preview-plan")
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] is None
    assert [d["code"] for d in body["diagnostics"]] == ["hooks.unknown_ref"]


def test_published_plan_carries_the_hooks_inside_its_checksum(benv):
    c, s = _create(benv)
    r = _ops(c, s, [{"op": "set_hooks", "params": {"hooks": HOOKS}}, RETENTION], 0)
    assert r.status_code == 200, r.text
    pub = c.post(f"/api/surveys/{s['id']}/publish", json={"baseRevision": 1})
    assert pub.status_code == 201, pub.text
    pub = pub.json()
    participant = benv.client()
    st = participant.post(f"/api/s/{pub['slug']}/sessions")
    assert st.status_code == 201, st.text
    plan = participant.get(st.json()["planUrl"]).json()
    assert plan["hooks"] == HOOKS
    body = {k: v for k, v in plan.items() if k != "checksum"}
    assert plan["checksum"] == "sha256:" + hashlib.sha256(canonical_json(body).encode()).hexdigest()
    # The same survey without hooks publishes under a different checksum.
    c2, s2 = _create(benv)
    assert _ops(c2, s2, [RETENTION], 0).status_code == 200
    pub2 = c2.post(f"/api/surveys/{s2['id']}/publish", json={"baseRevision": 1}).json()
    assert pub2["planChecksum"] != pub["planChecksum"]


def test_exports_report_hooks_as_not_exported(benv):
    c, s = _create(benv)
    assert _ops(c, s, [{"op": "set_hooks", "params": {"hooks": HOOKS}}], 0).status_code == 200
    for target in ("xlsform", "lss"):
        r = c.get(f"/api/surveys/{s['id']}/export-check", params={"target": target})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["exportable"] is True
        about = [d for d in body["diagnostics"] if d["pointer"] == "/hooks"]
        assert len(about) == 1 and about[0]["level"] == "unsupported", body["diagnostics"]
        assert "not exported" in about[0]["message"]
