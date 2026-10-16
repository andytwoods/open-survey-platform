"""Participant endpoints end to end (TestClient + SQLite store). runtime-design §5."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from osp_api.app import create_app
from osp_api.runtime_repo import StoreParticipantRepo
from osp_engine.random import assign, node_seed
from osp_runtime import SessionService, TokenBucket
from osp_store import Keyring, Store, SystemContext, TenantContext, create_engine, migrate
from osp_store import schema as t
from sqlalchemy import func, select

KEY = "a" * 43 + "="
PLAN = {"checksum": "plan-sha-1", "planVersion": 1, "nodes": []}
CONFIG = {
    "surveyVersion": "1",
    "assignments": [
        {"variable": "framing", "levels": ["gain", "loss"], "seedNode": "a1/framing"},
        {"variable": "arm", "levels": ["x", "y"], "method": "balanced", "seedNode": "a1/arm"},
    ],
    "quotas": [{"node": "qc1", "quota": "women", "limit": 2}],
}


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class Env:
    def __init__(self, tmp_path, start_burst: int = 1000) -> None:
        self.clock = FakeClock()
        self.engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}")
        migrate(self.engine)
        self.store = Store(self.engine, Keyring({"k1": KEY}, "k1"), clock=self.clock)
        self.repo = StoreParticipantRepo(self.store)
        self.service = SessionService(
            self.repo, clock=self.clock, start_limiter=TokenBucket(start_burst, 1, self.clock)
        )
        self.client = TestClient(create_app(self.service))
        sys = SystemContext("system:test")
        self.tenants = []
        for name in ("Lab A", "Lab B"):
            tenant = self.store.create_tenant(sys, name)
            self.tenants.append(TenantContext(tenant.id, "researcher"))

    def publish(self, slug: str, tenant: int = 0, **cfg) -> None:
        ctx = self.tenants[tenant]
        survey, _ = self.store.create_survey(ctx, "S", {"blocks": []})
        version = self.store.publish_version(ctx, survey.id, b"", meta={})
        self.service.publish(ctx.tenant_id, ctx.actor, version.id, slug, PLAN, {**CONFIG, **cfg})

    def start(self, slug: str = "demo", **body):
        r = self.client.post(f"/api/s/{slug}/sessions", json=body or None)
        assert r.status_code == 201, r.text
        return r.json()

    def count(self, table, where=None) -> int:
        q = select(func.count()).select_from(table)
        with self.engine.connect() as conn:
            return conn.execute(q if where is None else q.where(where)).scalar_one()


def auth(start: dict) -> dict:
    return {"Authorization": f"Bearer {start['resumeToken']}"}


def record(st: dict, **extra) -> dict:
    return {
        "sessionId": st["sessionId"],
        "planChecksum": st["planChecksum"],
        "assigned": st["assigned"],
        "answers": {"q1": {"state": "answered", "value": 4}, "q2": {"state": "unanswered"}},
        "orders": {"b1": ["q2", "q1"]},
        "events": [{"kind": "answer", "item": "q1", "at": 1}],
        "engineVersion": "0.1.0",
        **extra,
    }


@pytest.fixture
def env(tmp_path) -> Env:
    e = Env(tmp_path)
    e.publish("demo")
    return e


def test_start_returns_seed_assignment_and_records_them_first(env):
    st = env.start(urlParams={"PROLIFIC_PID": "p-1"})
    assert 1 <= st["sessionSeed"] <= 2**53 - 1
    assert st["revision"] == 0 and st["saveMode"] == "every-page"
    assert st["planUrl"] == "/api/s/demo/plan/plan-sha-1"
    expected = assign(["gain", "loss"], None, node_seed("1", st["sessionSeed"], "a1/framing"))
    assert st["assigned"]["framing"] == expected
    assert st["assigned"]["arm"] in ("x", "y")
    sess = env.repo.get(env.tenants[0].tenant_id, st["sessionId"])
    assert sess.session_seed == st["sessionSeed"] and sess.assigned == st["assigned"]
    assert sess.url_params == {"PROLIFIC_PID": "p-1"}
    # Only the token hash is stored.
    with env.engine.connect() as conn:
        stored = conn.execute(select(t.participant_sessions.c.token_hash)).scalar_one()
    assert stored != st["resumeToken"] and st["resumeToken"] not in stored


def test_seeds_are_random_and_balanced_arms_alternate(env):
    starts = [env.start() for _ in range(10)]
    assert len({s["sessionSeed"] for s in starts}) == 10
    assert Counter(s["assigned"]["arm"] for s in starts) == {"x": 5, "y": 5}


def test_plan_is_served_immutable(env):
    r = env.client.get("/api/s/demo/plan/plan-sha-1")
    assert r.status_code == 200 and r.json() == PLAN
    assert "immutable" in r.headers["cache-control"]
    assert env.client.get("/api/s/demo/plan/other").status_code == 404


def test_unknown_slug_404(env):
    assert env.client.post("/api/s/nope/sessions").status_code == 404


def test_stale_write_gives_409_with_server_snapshot(env):
    st = env.start()
    url = f"/api/sessions/{st['sessionId']}/snapshot"
    ok = env.client.put(url, json={"baseRevision": 0, "snapshot": {"p": 1}}, headers=auth(st))
    assert ok.status_code == 200 and ok.json() == {"revision": 1, "replay": False}
    ok = env.client.put(url, json={"baseRevision": 1, "snapshot": {"p": 2}}, headers=auth(st))
    assert ok.json()["revision"] == 2
    stale = env.client.put(url, json={"baseRevision": 1, "snapshot": {"p": 9}}, headers=auth(st))
    assert stale.status_code == 409
    assert stale.json() == {
        "code": "snapshot.stale",
        "message": "stale baseRevision; the server is at revision 2",
        "revision": 2,
        "snapshot": {"p": 2},
    }
    # The losing copy is kept (R-2), the server copy is unchanged.
    assert env.count(t.session_conflicts) == 1
    res = env.client.get("/api/sessions/resume", headers=auth(st)).json()
    assert (res["revision"], res["snapshot"]) == (2, {"p": 2})


def test_lost_ack_retry_is_a_replay(env):
    st = env.start()
    url = f"/api/sessions/{st['sessionId']}/snapshot"
    body = {"baseRevision": 0, "snapshot": {"p": 1}}
    env.client.put(url, json=body, headers=auth(st))
    again = env.client.put(url, json=body, headers=auth(st))
    assert again.status_code == 200 and again.json() == {"revision": 1, "replay": True}
    assert env.count(t.session_conflicts) == 0


def test_quota_retries_are_idempotent(env):
    a, b, c = env.start(), env.start(), env.start()
    q = lambda st: env.client.post(f"/api/sessions/{st['sessionId']}/quota/qc1", headers=auth(st))  # noqa: E731
    assert q(a).json() == {"nodeId": "qc1", "result": "admitted", "replay": False}
    assert q(a).json() == {"nodeId": "qc1", "result": "admitted", "replay": True}
    assert q(b).json()["result"] == "admitted"
    assert q(c).json()["result"] == "full"  # limit 2
    assert q(c).json() == {"nodeId": "qc1", "result": "full", "replay": True}
    assert (
        env.client.post(f"/api/sessions/{a['sessionId']}/quota/nope", headers=auth(a)).status_code
        == 404
    )


def test_submit_is_idempotent_and_closes_the_session(env):
    st = env.start()
    url = f"/api/sessions/{st['sessionId']}/submit"
    env.client.put(
        f"/api/sessions/{st['sessionId']}/snapshot",
        json={"baseRevision": 0, "snapshot": {"p": 1}},
        headers=auth(st),
    )
    first = env.client.post(url, json=record(st), headers=auth(st))
    again = env.client.post(url, json=record(st), headers=auth(st))
    assert first.status_code == 200 and again.status_code == 200
    assert first.json()["responseId"] == again.json()["responseId"]
    assert (first.json()["replay"], again.json()["replay"]) == (False, True)
    assert env.count(t.responses) == 1
    changed = env.client.post(url, json=record(st, engineVersion="9"), headers=auth(st))
    assert changed.status_code == 409 and changed.json()["code"] == "submit.mismatch"
    late = env.client.put(
        f"/api/sessions/{st['sessionId']}/snapshot",
        json={"baseRevision": 1, "snapshot": {"p": 2}},
        headers=auth(st),
    )
    assert late.status_code == 409 and late.json()["code"] == "session.submitted"
    resp = env.store.get_response(env.tenants[0], first.json()["responseId"])
    assert resp.answers["q1"] == {"state": "answered", "value": 4}
    assert resp.realised_orders == {"b1": ["q2", "q1"]}
    assert resp.session_seed == st["sessionSeed"]
    full = env.repo.ps.get_record(env.tenants[0], resp.id)
    assert full["server"]["saveMode"] == "every-page"
    assert full["record"]["events"] == [{"kind": "answer", "item": "q1", "at": 1}]
    assert env.client.get("/api/sessions/resume", headers=auth(st)).json()["submitted"] is True


@pytest.mark.parametrize(
    ("patch", "code"),
    [
        ({"planChecksum": "other"}, "submit.plan"),
        ({"assigned": {"framing": "nope", "arm": "x"}}, "submit.assignment"),
        ({"answers": {"q1": {"state": "unanswered", "value": 3}}}, "payload.invalid"),
    ],
)
def test_submit_validates_checksum_assignment_and_shape(env, patch, code):
    st = env.start()
    r = env.client.post(
        f"/api/sessions/{st['sessionId']}/submit", json=record(st, **patch), headers=auth(st)
    )
    assert r.status_code == 422 and r.json()["code"] == code
    bad = env.client.post(
        f"/api/sessions/{st['sessionId']}/submit",
        json={**record(st), "answers": {"q1": {"state": "maybe"}}},
        headers=auth(st),
    )
    assert bad.status_code == 422
    assert env.count(t.responses) == 0


def test_end_only_stores_no_answers_or_url_params_before_submit(tmp_path):
    env = Env(tmp_path)
    env.publish("eo", saveMode="end-only")
    st = env.start("eo", urlParams={"PROLIFIC_PID": "secret-pid"})
    assert st["saveMode"] == "end-only"
    put = env.client.put(
        f"/api/sessions/{st['sessionId']}/snapshot",
        json={"baseRevision": 0, "snapshot": {"answers": {"q1": 4}}},
        headers=auth(st),
    )
    assert put.status_code == 403 and put.json()["code"] == "save_mode.end_only"
    assert (
        env.client.post(f"/api/sessions/{st['sessionId']}/quota/qc1", headers=auth(st)).status_code
        == 200
    )  # quota checks still reach the server (§5.0)
    assert env.count(t.sessions, t.sessions.c.instance_ct.is_not(None)) == 0
    assert (
        env.count(t.participant_sessions, t.participant_sessions.c.url_params_ct.is_not(None)) == 0
    )
    assert env.count(t.session_conflicts) == 0 and env.count(t.responses) == 0
    with env.engine.connect() as conn:
        for table in t.metadata.sorted_tables:
            for row in conn.execute(select(table)):
                assert "secret-pid" not in repr(row), table.name
    res = env.client.get("/api/sessions/resume", headers=auth(st)).json()
    assert res["snapshot"] is None and res["saveMode"] == "end-only"
    sub = env.client.post(
        f"/api/sessions/{st['sessionId']}/submit",
        json=record(st, urlParams={"PROLIFIC_PID": "secret-pid"}),
        headers=auth(st),
    )
    assert sub.status_code == 200
    full = env.repo.ps.get_record(env.tenants[0], sub.json()["responseId"])
    assert full["record"]["urlParams"] == {"PROLIFIC_PID": "secret-pid"}
    assert full["server"]["saveMode"] == "end-only"


def test_cross_tenant_and_cross_session_access_fails(tmp_path):
    env = Env(tmp_path)
    env.publish("a", tenant=0)
    env.publish("b", tenant=1)
    sa, sb = env.start("a"), env.start("b")
    # Session B's token cannot touch session A, in either direction.
    for st, other in ((sa, sb), (sb, sa)):
        sid = st["sessionId"]
        h = auth(other)
        snap = {"baseRevision": 0, "snapshot": {"x": 1}}
        assert (
            env.client.put(f"/api/sessions/{sid}/snapshot", json=snap, headers=h).status_code == 401
        )
        assert env.client.post(f"/api/sessions/{sid}/quota/qc1", headers=h).status_code == 401
        assert (
            env.client.post(f"/api/sessions/{sid}/submit", json=record(st), headers=h).status_code
            == 401
        )
    assert (
        env.client.put(
            f"/api/sessions/{sa['sessionId']}/snapshot", json={"baseRevision": 0, "snapshot": {}}
        ).status_code
        == 401
    )  # no token at all
    bad = {"Authorization": "Bearer not-a-token"}
    assert env.client.get("/api/sessions/resume", headers=bad).status_code == 401
    # The store refuses a tenant B context on tenant A's session.
    from osp_store import NotFound

    with pytest.raises(NotFound):
        env.repo.get(env.tenants[1].tenant_id, sa["sessionId"])
    assert env.count(t.sessions, t.sessions.c.instance_ct.is_not(None)) == 0


def test_quota_holds_are_released_after_24h_but_the_resume_link_lasts_30_days(env):
    st = env.start()
    sid = st["sessionId"]
    pub_id = env.repo.find_publication("demo").id
    assert (
        env.client.post(f"/api/sessions/{sid}/quota/qc1", headers=auth(st)).json()["result"]
        == "admitted"
    )
    env.clock.now += timedelta(hours=25)
    report = env.service.release_inactive()
    assert (report.sessions_expired, report.quota_slots_released) == (1, 1)
    assert env.repo.ps.quota_usage(env.tenants[0], pub_id) == {"women": (0, 2)}
    # Resuming after the hold was released takes the place again (S-1).
    env.clock.now += timedelta(days=20)
    assert env.client.get("/api/sessions/resume", headers=auth(st)).status_code == 200
    assert env.repo.ps.quota_usage(env.tenants[0], pub_id) == {"women": (1, 2)}
    # 30 days without activity: the link no longer works for resume or snapshots.
    env.clock.now += timedelta(days=30)
    r = env.client.get("/api/sessions/resume", headers=auth(st))
    assert r.status_code == 410 and r.json()["code"] == "session.expired"
    snap = {"baseRevision": 0, "snapshot": {"x": 1}}
    assert (
        env.client.put(f"/api/sessions/{sid}/snapshot", json=snap, headers=auth(st)).status_code
        == 410
    )
    assert env.client.post(f"/api/sessions/{sid}/quota/qc1", headers=auth(st)).status_code == 410


def test_resume_expiry_is_configurable_per_survey(tmp_path):
    env = Env(tmp_path)
    env.publish("short", resumeExpiryDays=2)
    st = env.start("short")
    env.clock.now += timedelta(days=1, hours=23)
    assert env.client.get("/api/sessions/resume", headers=auth(st)).status_code == 200
    env.clock.now += timedelta(days=2)
    assert env.client.get("/api/sessions/resume", headers=auth(st)).status_code == 410


def test_late_submit_is_accepted_flagged_and_not_counted(env):
    st = env.start()
    sid = st["sessionId"]
    pub_id = env.repo.find_publication("demo").id
    env.client.post(f"/api/sessions/{sid}/quota/qc1", headers=auth(st))
    env.clock.now += timedelta(days=31)  # past the resume expiry; the job has not run
    url = f"/api/sessions/{sid}/submit"
    first = env.client.post(url, json=record(st), headers=auth(st))
    assert first.status_code == 200, first.text
    assert (first.json()["late"], first.json()["replay"]) == (True, False)
    assert env.repo.ps.quota_usage(env.tenants[0], pub_id) == {"women": (0, 2)}
    full = env.repo.ps.get_record(env.tenants[0], first.json()["responseId"])
    assert full["server"]["late"] is True
    # S-4: an identical retry returns the original success; different data is 409.
    again = env.client.post(url, json=record(st), headers=auth(st))
    assert again.status_code == 200
    assert {k: again.json()[k] for k in ("responseId", "submittedAt", "late")} == {
        k: first.json()[k] for k in ("responseId", "submittedAt", "late")
    }
    assert again.json()["replay"] is True
    changed = env.client.post(url, json=record(st, engineVersion="9"), headers=auth(st))
    assert changed.status_code == 409 and changed.json()["code"] == "submit.mismatch"
    assert env.count(t.responses) == 1


def test_submit_after_holds_released_is_late_and_retries_return_the_original(env):
    st = env.start()
    sid = st["sessionId"]
    env.client.post(f"/api/sessions/{sid}/quota/qc1", headers=auth(st))
    env.clock.now += timedelta(hours=25)
    env.service.release_inactive()
    url = f"/api/sessions/{sid}/submit"
    first = env.client.post(url, json=record(st), headers=auth(st))
    assert first.status_code == 200 and first.json()["late"] is True
    again = env.client.post(url, json=record(st), headers=auth(st))
    assert again.json()["responseId"] == first.json()["responseId"]
    assert again.json()["replay"] is True and again.json()["late"] is True


def test_on_time_submit_is_not_late_and_counts(env):
    st = env.start()
    sid = st["sessionId"]
    env.client.post(f"/api/sessions/{sid}/quota/qc1", headers=auth(st))
    r = env.client.post(f"/api/sessions/{sid}/submit", json=record(st), headers=auth(st))
    assert r.status_code == 200 and r.json()["late"] is False
    usage = env.repo.ps.quota_usage(env.tenants[0], env.repo.find_publication("demo").id)
    assert usage == {"women": (1, 2)}


def test_session_start_is_rate_limited(tmp_path):
    env = Env(tmp_path, start_burst=3)
    env.publish("demo")
    codes = [env.client.post("/api/s/demo/sessions").status_code for _ in range(5)]
    assert codes == [201, 201, 201, 429, 429]
    env.clock.now += timedelta(seconds=1)
    assert env.client.post("/api/s/demo/sessions").status_code == 201


def test_endpoints_answer_503_without_a_service():
    client = TestClient(create_app())
    assert client.post("/api/s/demo/sessions").status_code == 503
