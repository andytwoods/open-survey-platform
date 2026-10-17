"""Consent before collection, decline, withdrawal, researcher deletion, no IPs in logs
(M5, semantics.md §11, runtime-design §7)."""

from __future__ import annotations

import csv
import io
import json
import logging

import pytest
from osp_api.serve import NoClientAddress, log_config
from osp_store import NotFound
from osp_store import schema as t

from .test_participant import Env, auth, record

VERSION = "sha256:" + "c" * 64


@pytest.fixture
def env(tmp_path) -> Env:
    e = Env(tmp_path)
    e.publish("demo", consent={"version": VERSION, "countDeclines": True})
    e.publish("plain", tenant=1)
    return e


def _consent(env, st, version=VERSION):
    return env.client.post(
        f"/api/sessions/{st['sessionId']}/consent",
        json={"consentVersion": version},
        headers=auth(st),
    )


def _snapshot(env, st, base=0):
    return env.client.put(
        f"/api/sessions/{st['sessionId']}/snapshot",
        json={"baseRevision": base, "snapshot": {"p": 1}},
        headers=auth(st),
    )


def test_nothing_is_accepted_before_agreement(env):
    st = env.start(urlParams={"PROLIFIC_PID": "p-1"})
    sess = env.repo.get(env.tenants[0].tenant_id, st["sessionId"])
    assert sess.url_params is None  # not stored before consent, even in every-page mode
    r = _snapshot(env, st)
    assert (r.status_code, r.json()["code"]) == (403, "consent.required")
    q = env.client.post(f"/api/sessions/{st['sessionId']}/quota/qc1", headers=auth(st))
    assert q.status_code == 403
    sub = env.client.post(
        f"/api/sessions/{st['sessionId']}/submit",
        json=record(st, consentVersion=VERSION),
        headers=auth(st),
    )
    assert sub.status_code == 403
    assert env.count(t.response_records) == 0


def test_agree_then_save_and_submit_records_consent(env):
    st = env.start()
    bad = _consent(env, st, "sha256:" + "0" * 64)
    assert (bad.status_code, bad.json()["code"]) == (422, "consent.version")
    ok = _consent(env, st)
    assert ok.status_code == 200 and ok.json()["consentVersion"] == VERSION
    assert ok.json()["replay"] is False and _consent(env, st).json()["replay"] is True
    assert _snapshot(env, st).status_code == 200
    wrong = env.client.post(
        f"/api/sessions/{st['sessionId']}/submit", json=record(st), headers=auth(st)
    )
    assert (wrong.status_code, wrong.json()["code"]) == (422, "submit.consent")
    sub = env.client.post(
        f"/api/sessions/{st['sessionId']}/submit",
        json=record(st, consentVersion=VERSION),
        headers=auth(st),
    )
    assert sub.status_code == 200, sub.text
    stored = env.repo.ps.get_record(env.tenants[0], sub.json()["responseId"])
    assert stored["server"]["consentVersion"] == VERSION
    assert stored["server"]["consentedAt"] == ok.json()["consentedAt"].replace("Z", "+00:00")


def test_decline_deletes_the_session_and_counts_anonymously(env):
    st = env.start()
    r = env.client.post(f"/api/sessions/{st['sessionId']}/decline", headers=auth(st))
    assert r.status_code == 204
    assert env.count(t.participant_sessions) == 0 and env.count(t.sessions) == 0
    pub = env.repo.find_publication("demo")
    assert env.repo.ps.decline_count(env.tenants[0], pub.id) == 1
    # The token is gone with the session.
    assert env.client.get("/api/sessions/resume", headers=auth(st)).status_code == 401


def test_decline_after_agreeing_is_refused(env):
    st = env.start()
    _consent(env, st)
    r = env.client.post(f"/api/sessions/{st['sessionId']}/decline", headers=auth(st))
    assert (r.status_code, r.json()["code"]) == (422, "consent.already_given")


def test_survey_without_consent_page_is_unchanged(env):
    st = env.start("plain", urlParams={"PROLIFIC_PID": "p-2"})
    assert _snapshot(env, st).status_code == 200
    assert _consent(env, st).status_code == 404
    sess = env.repo.get(env.tenants[1].tenant_id, st["sessionId"])
    assert sess.url_params == {"PROLIFIC_PID": "p-2"}


def test_withdraw_after_submit_deletes_everything_and_audits_without_answers(env):
    st = env.start()
    _consent(env, st)
    sub = env.client.post(
        f"/api/sessions/{st['sessionId']}/submit",
        json=record(st, consentVersion=VERSION),
        headers=auth(st),
    )
    rid = sub.json()["responseId"]
    w = env.client.post(f"/api/sessions/{st['sessionId']}/withdraw", headers=auth(st))
    assert w.status_code == 200 and w.json() == {"withdrawn": True, "responsesDeleted": 1}
    with pytest.raises(NotFound):
        env.store.get_response(env.tenants[0], rid)
    assert env.count(t.response_records) == 0 and env.count(t.participant_sessions) == 0
    entry = next(e for e in env.store.list_audit(env.tenants[0]) if e.action == "session.delete")
    assert entry.detail == {"reason": "participant withdrawal", "responses_deleted": 1}
    again = env.client.post(f"/api/sessions/{st['sessionId']}/withdraw", headers=auth(st))
    assert again.status_code == 401


def test_withdraw_needs_the_sessions_own_token(env):
    a, b = env.start(), env.start()
    r = env.client.post(f"/api/sessions/{a['sessionId']}/withdraw", headers=auth(b))
    assert r.status_code == 401
    assert env.client.post(f"/api/sessions/{a['sessionId']}/withdraw").status_code == 401


# -- no IP addresses in logs --------------------------------------------------------------


def test_participant_flow_logs_no_client_address(env, caplog):
    caplog.set_level(logging.DEBUG)
    st = env.start()
    _consent(env, st)
    _snapshot(env, st)
    env.client.get("/api/sessions/resume", headers=auth(st))
    env.client.post(f"/api/sessions/{st['sessionId']}/withdraw", headers=auth(st))
    text = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "testclient" not in text  # TestClient's client host


def test_access_log_has_no_client_address():
    cfg = log_config()
    assert "client_addr" not in cfg["formatters"]["access"]["fmt"]
    from uvicorn.logging import AccessFormatter

    fmt = AccessFormatter(cfg["formatters"]["access"]["fmt"], use_colors=False)
    rec = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("203.0.113.7:5555", "POST", "/api/s/demo/sessions", "1.1", 201),
        None,
    )
    assert NoClientAddress().filter(rec) is True
    line = fmt.format(rec)
    assert "203.0.113.7" not in line and "/api/s/demo/sessions" in line
    assert "203.0.113.7" not in rec.getMessage()  # other handlers can't print it either
    assert all(cfg["loggers"][n]["filters"] == ["no_client_address"] for n in ("uvicorn.access",))


# -- researcher deletion and export (builder API) -----------------------------------------

SURVEY = {
    "specVersion": "osp-survey/0.1",
    "id": "consent_demo",
    "metadata": {"title": "Consent demo", "languages": ["en"]},
    "settings": {"retention": {"kind": "indefinite"}},
    "consent": {"text": "You may stop at any time.", "countDeclines": True},
    "blocks": [{"id": "b1", "pages": [{"id": "p1", "items": [
        {"id": "q1", "type": "integer", "label": "Q1"},
    ]}]}],
    "flow": [{"type": "block", "id": "n_b1", "block": "b1"}],
}  # fmt: skip


def _published_with_response(benv):
    c = benv.login("editor@a.example")
    sid = c.post("/api/surveys", json={"title": "Consent", "survey": SURVEY}).json()["id"]
    pub = c.post(f"/api/surveys/{sid}/publish", json={})
    assert pub.status_code == 201, pub.text
    p = benv.client()
    slug = benv.store.ensure_public_slug(_ctx(benv), sid)
    st = p.post(f"/api/s/{slug}/sessions", json={}).json()
    plan = p.get(st["planUrl"]).json()
    version = plan["consent"]["version"]
    assert p.post(
        f"/api/sessions/{st['sessionId']}/consent",
        json={"consentVersion": version},
        headers=auth(st),
    ).status_code == 200  # fmt: skip
    rec = {
        "sessionId": st["sessionId"],
        "planChecksum": st["planChecksum"],
        "assigned": st["assigned"],
        "answers": {"q1": {"state": "answered", "value": 4}},
        "consentVersion": version,
        "consentedAt": 1_700_000_000_000,
    }
    r = p.post(f"/api/sessions/{st['sessionId']}/submit", json=rec, headers=auth(st))
    assert r.status_code == 200, r.text
    return c, sid, r.json()["responseId"], version


def _ctx(benv):
    from osp_store import TenantContext

    return TenantContext(benv.tenants["A"], "system:test")


def _rows(c, sid):
    r = c.get(f"/api/surveys/{sid}/export/responses")
    assert r.status_code == 200, r.text
    return list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"), newline="")))


def test_export_has_consent_columns_and_codebook_the_text(benv):
    c, sid, rid, version = _published_with_response(benv)
    rows = _rows(c, sid)
    assert [r["_response_id"] for r in rows] == [rid]
    assert rows[0]["_consent_version"] == version and rows[0]["_consented_at"].endswith("Z")
    j = json.loads(c.get(f"/api/surveys/{sid}/export/responses?format=json").content)
    assert j["responses"][0]["consentVersion"] == version
    book = json.loads(c.get(f"/api/surveys/{sid}/export/codebook?format=json").content)
    assert book["consent"]["text"] == {"en": "You may stop at any time."}
    assert "_consent_version" in [m["column"] for m in book["metaColumns"]]
    assert "## Consent" in c.get(f"/api/surveys/{sid}/export/codebook").text


def test_researcher_delete_needs_permission_and_removes_from_export(benv):
    c, sid, rid, _ = _published_with_response(benv)
    viewer = benv.login("viewer@a.example")
    assert viewer.delete(f"/api/surveys/{sid}/responses/{rid}").status_code == 403
    other = benv.login("owner@b.example")
    assert other.delete(f"/api/surveys/{sid}/responses/{rid}").status_code == 404
    assert c.delete(f"/api/surveys/{sid}/responses/nope").status_code == 404
    assert c.delete(f"/api/surveys/{sid}/responses/{rid}").status_code == 204
    assert _rows(c, sid) == []
    assert c.delete(f"/api/surveys/{sid}/responses/{rid}").status_code == 404
    entry = next(e for e in benv.store.list_audit(_ctx(benv)) if e.action == "response.delete")
    assert entry.target_id == rid
    assert entry.detail == {"reason": "researcher deletion", "session_deleted": True}
