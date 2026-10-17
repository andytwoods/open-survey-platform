"""End redirects over HTTP (task EN2, end-of-survey plan §4.2, lead decision 3): a change to
redirect templates or to an ending's redirect is audited with what it sends (never the
data), viewers may not make it, a piped answer is flagged as a data export, the templates
reach the published plan, and the codebook lists where participants are sent."""

from __future__ import annotations

import json
from pathlib import Path

from osp_store import TenantContext

REPO = Path(__file__).resolve().parents[3]
FIXTURE = json.loads((REPO / "fixtures/05-showif-null/survey.json").read_text("utf-8"))
RETENTION = {
    "op": "set_property",
    "params": {"target": "/settings", "property": "retention", "value": {"kind": "indefinite"}},
}
PROLIFIC = {
    "url": "https://app.prolific.com/submissions/complete?cc={cc}&a={a}",
    "params": {"cc": {"pattern": "[A-Z0-9]{4,8}"}, "a": {}},
}
TEMPLATE = {"op": "set_redirect_template", "params": {"name": "prolific", "template": PROLIFIC}}


def _ending(params: dict, **extra: object) -> dict:
    return {
        "op": "set_ending",
        "params": {
            "outcome": "complete",
            "ending": {"redirect": {"template": "prolific", "params": params, **extra}},
        },
    }


def _create(benv, who: str = "owner@a.example") -> tuple[object, dict]:
    c = benv.login(who)
    r = c.post("/api/surveys", json={"title": "Redirects", "survey": FIXTURE})
    assert r.status_code == 201, r.text
    return c, r.json()


def _ops(c, s: dict, ops: list[dict], base: int):
    return c.post(f"/api/surveys/{s['id']}/ops", json={"ops": ops, "baseRevision": base})


def _audit(benv, action: str = "survey.redirects_changed") -> list:
    ctx = TenantContext(benv.tenants["A"], "test")
    return [a for a in benv.store.list_audit(ctx) if a.action == action]


def test_redirect_changes_are_audited_with_what_they_send(benv):
    c, s = _create(benv)
    assert _ops(c, s, [TEMPLATE], 0).status_code == 200
    rows = _audit(benv)
    assert len(rows) == 1 and rows[0].target_id == s["id"]
    assert rows[0].detail["before"] is None
    assert rows[0].detail["after"] == {"templates": ["prolific"], "redirects": []}
    assert rows[0].detail["ops"] == ["set_redirect_template"]
    # An ending's redirect with a literal and a piped answer: the kinds are named, the
    # answer itself never is; the validator flags the piped answer as a data export.
    r = _ops(c, s, [_ending({"cc": "C1AB2", "a": "${a}"})], 1)
    assert r.status_code == 200, r.text
    assert "redirect.param_question" in {d["code"] for d in r.json()["diagnostics"]}
    rows = _audit(benv)
    assert len(rows) == 2
    assert rows[1].detail["after"]["redirects"] == [
        {
            "outcome": "complete",
            "template": "prolific",
            "host": "app.prolific.com",
            "mode": "auto",
            "delay": 5,
            "params": {"cc": "literal", "a": "question"},
        }
    ]
    assert "C1AB2" not in json.dumps(rows[1].detail["after"]["redirects"][0]["params"])
    # Unrelated edits are not redirect changes; changing the delay is.
    assert _ops(c, s, [RETENTION], 2).status_code == 200
    assert len(_audit(benv)) == 2
    assert (
        _ops(c, s, [_ending({"cc": "C1AB2", "a": "${a}"}, delay=0, mode="link")], 3).status_code
        == 200
    )
    rows = _audit(benv)
    assert len(rows) == 3 and rows[2].detail["after"]["redirects"][0]["mode"] == "link"
    # Undo is audited too (it brings the earlier redirect back).
    txn = rows[2].detail["transaction"]
    u = c.post(f"/api/surveys/{s['id']}/undo", json={"transactionId": txn, "baseRevision": 4})
    assert u.status_code == 200, u.text
    rows = _audit(benv)
    assert len(rows) == 4 and rows[3].detail["kind"] == "undo"
    assert rows[3].detail["after"]["redirects"][0]["mode"] == "auto"


def test_viewers_may_not_change_redirects(benv):
    _, s = _create(benv)
    v = benv.login("viewer@a.example")
    assert _ops(v, s, [TEMPLATE], 0).status_code == 403
    assert _audit(benv) == []


def test_a_bad_template_is_refused_at_publish_and_a_good_one_reaches_the_plan(benv):
    c, s = _create(benv)
    evil = {"op": "set_redirect_template", "params": {"name": "evil", "template": {
        "url": "https://{host}.example/x", "params": {"host": {}}}}}  # fmt: skip
    r = _ops(c, s, [RETENTION, evil], 0)
    assert r.status_code == 200
    codes = {d["code"] for d in r.json()["diagnostics"]}
    assert "redirect.template" in codes
    p = c.post(f"/api/surveys/{s['id']}/publish", json={"baseRevision": 1})
    assert p.status_code == 422, p.text
    fix = {"op": "set_redirect_template", "params": {"name": "evil", "template": None}}
    assert _ops(c, s, [fix, TEMPLATE, _ending({"cc": "C1AB2", "a": "x"})], 1).status_code == 200
    p = c.post(f"/api/surveys/{s['id']}/publish", json={"baseRevision": 2})
    assert p.status_code == 201, p.text
    slug = p.json()["slug"]
    participant = benv.client()
    start = participant.post(f"/api/s/{slug}/sessions")
    assert start.status_code == 201, start.text
    plan = participant.get(start.json()["planUrl"]).json()
    assert plan["redirectTemplates"] == {"prolific": PROLIFIC}
    assert plan["endings"]["complete"]["redirect"]["params"] == {"cc": ["C1AB2"], "a": ["x"]}
    book = c.get(f"/api/surveys/{s['id']}/export/codebook?format=json").json()
    assert book["redirects"][0]["host"] == "app.prolific.com"
