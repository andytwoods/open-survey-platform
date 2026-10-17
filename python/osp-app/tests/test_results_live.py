"""Live results backend (task LV2, ``planning/live-results.md`` LV-D2, LV-D3, LV-D7):
the watermark command, the ``live`` flag, the coalesced ``results.live`` audit and the
single-flight cache. Fixture data from ``results_data.py`` (invented, rule 7)."""

from __future__ import annotations

import json
import threading
from datetime import timedelta

import pytest
from osp_app import Forbidden, InvalidRequest, NotFoundError, build_services, make_identity
from osp_app.auth.testing import FakeClock
from osp_app.results import LIVE_WINDOW, LiveAudit, ResultsCache, live_audit_for
from osp_store import Keyring, Store, TenantContext, create_engine, migrate

from .results_data import SURVEY, A, add_response, publish, seed

KEY = "a" * 43 + "="


@pytest.fixture
def env(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'live.db'}")
    migrate(engine)
    store = Store(engine, Keyring({"k1": KEY}, active="k1"))
    clock = FakeClock()
    svc = build_services(store, clock=clock)
    owner = svc.admit(make_identity("owner-a", {"lab-a": "owner"}))
    editor = svc.admit(make_identity("editor-a", {"lab-a": "editor"}))
    viewer = svc.admit(make_identity("viewer-a", {"lab-a": "viewer"}))
    other = svc.admit(make_identity("owner-b", {"lab-b": "owner"}))
    sid = svc.builder.run("survey.create", owner, title="L", survey=SURVEY).survey.id
    ctx = TenantContext(next(iter(owner.roles)), "system:test")
    v1 = publish(store, ctx, sid, SURVEY)
    ids = seed(store, ctx, v1.id)
    live_audit_for(svc.builder).clock = clock.now  # the 15-minute window under test control

    class Env:
        pass

    e = Env()
    e.svc, e.store, e.sid, e.ctx, e.v1, e.ids, e.clock = svc, store, sid, ctx, v1, ids, clock
    e.owner, e.editor, e.viewer, e.other = owner, editor, viewer, other

    def q(actor=owner, **query):
        return svc.builder.run("survey.results_query", actor, survey_id=sid, query=query)

    def wm(actor=owner, **params):
        return svc.builder.run("survey.results_watermark", actor, survey_id=sid, **params)

    def rows(action):
        return [a for a in store.list_audit(ctx) if a.action == action]

    e.q, e.wm, e.rows = q, wm, rows
    return e


# -- watermark -----------------------------------------------------------------------------


def test_watermark_matches_the_query_and_counts_every_stored_response(env):
    out = env.wm()
    assert out == {"watermark": env.q()["watermark"], "responses": 5, "versionsUsed": [1]}
    assert out["responses"] == env.q(status="all")["responses"]
    add_response(env.store, env.ctx, env.v1.id, {"fruit": A("cherry")})
    changed = env.wm()
    assert changed["watermark"] != out["watermark"] and changed["responses"] == 6
    assert changed["watermark"] == env.q()["watermark"]
    env.store.delete_response(env.ctx, env.ids[0])
    deleted = env.wm()
    assert deleted["watermark"] not in (out["watermark"], changed["watermark"])
    assert deleted["responses"] == 5


def test_watermark_versions(env):
    body = {**SURVEY, "blocks": SURVEY["blocks"]}
    v2 = publish(env.store, env.ctx, env.sid, body)
    add_response(env.store, env.ctx, v2.id, {"fruit": A("apple")})
    latest = env.wm()
    assert latest["versionsUsed"] == [2] and latest["responses"] == 1
    both = env.wm(versions=[2, 1])
    assert both["versionsUsed"] == [1, 2] and both["responses"] == 6
    assert both["watermark"] == env.q(versions=[1, 2])["watermark"]
    assert env.wm(versions=[1]) == {**env.wm(versions=[1]), "versionsUsed": [1]}
    with pytest.raises(NotFoundError):
        env.wm(versions=[7])
    with pytest.raises(InvalidRequest):
        env.wm(versions=[0])
    with pytest.raises(InvalidRequest):
        env.wm(versions="1")


def test_watermark_access_and_no_audit(env):
    before = len(env.store.list_audit(env.ctx))
    assert env.wm(actor=env.editor)["responses"] == 5
    assert len(env.store.list_audit(env.ctx)) == before  # reads no answers: not audited
    with pytest.raises(Forbidden):
        env.wm(actor=env.viewer)
    with pytest.raises(NotFoundError):
        env.wm(actor=env.other)
    assert len(env.store.list_audit(env.ctx)) == before


# -- the live flag and the coalesced audit -------------------------------------------------


def test_live_is_not_part_of_the_hash_or_the_cache_key(env):
    manual = env.q(cards=[{"question": "fruit"}])
    live = env.q(cards=[{"question": "fruit"}], live=True)
    assert live["queryHash"] == manual["queryHash"] and live["cached"] is True
    assert live["generatedAt"] == manual["generatedAt"]
    for bad in ("true", 1, None):
        with pytest.raises(InvalidRequest):
            env.q(live=bad)


def test_live_audit_one_row_per_window_then_a_row_carrying_the_tally(env):
    first = env.q(live=True)
    for _ in range(4):
        env.clock.advance(seconds=10)
        env.q(live=True)
    rows = env.rows("results.live")
    assert len(rows) == 1 and env.rows("results.read") == []
    d = rows[0].detail
    assert rows[0].actor == "owner-a" and d["queryHash"] == first["queryHash"]
    assert d["query"]["versions"] == [1] and d["cached"] is False
    assert d["watermark"] == first["watermark"] and d["previous"] is None
    # A new response mid-window: the refresh recomputes but still writes nothing.
    add_response(env.store, env.ctx, env.v1.id, {"fruit": A("cherry")})
    env.clock.advance(seconds=10)
    sixth = env.q(live=True)
    assert sixth["cached"] is False and len(env.rows("results.live")) == 1
    # Past the window: the next refresh opens a new window and carries the old tally.
    env.clock.advance(seconds=LIVE_WINDOW.total_seconds())
    env.q(live=True)
    rows = env.rows("results.live")
    assert len(rows) == 2
    prev = rows[1].detail["previous"]
    assert prev["refreshes"] == 6 and prev["queryHash"] == first["queryHash"]
    assert prev["firstWatermark"] == first["watermark"]
    assert prev["lastWatermark"] == sixth["watermark"] != first["watermark"]
    assert prev["openedAt"] < prev["lastAt"]
    assert rows[1].detail["watermark"] == sixth["watermark"] and rows[1].detail["cached"] is True
    for value in ("sunny", "rain!", "banana", "durian"):
        assert value not in json.dumps([r.detail for r in rows])


def test_live_audit_a_changed_query_writes_a_row_at_once(env):
    env.q(live=True)
    env.clock.advance(seconds=10)
    env.q(live=True, denominator="shown")  # a different hash: its own window
    env.clock.advance(seconds=10)
    env.q(live=True)  # back to the first: still inside its window
    env.q(live=True, denominator="shown")
    rows = env.rows("results.live")
    assert [r.detail["query"]["denominator"] for r in rows] == ["answered", "shown"]
    assert len(live_audit_for(env.svc.builder)) == 2


def test_live_audit_is_per_actor_and_manual_reads_stay_results_read(env):
    env.q(live=True)
    env.q(actor=env.editor, live=True)
    env.q(live=True)
    env.q()  # a click on Show results
    live = env.rows("results.live")
    assert [r.actor for r in live] == ["owner-a", "editor-a"]
    read = env.rows("results.read")
    assert len(read) == 1 and read[0].actor == "owner-a" and read[0].detail["cached"] is True


def test_live_audit_flush_writes_closing_rows_for_coalesced_windows(env):
    env.q(live=True)  # one refresh: its opening row says everything already
    env.q(live=True, denominator="shown")
    env.clock.advance(seconds=5)
    env.q(live=True, denominator="shown")
    env.q(live=True, denominator="shown")
    audit = live_audit_for(env.svc.builder)
    assert len(audit) == 2
    assert audit.flush("exit") == 1 and len(audit) == 0
    rows = env.rows("results.live")
    assert len(rows) == 3
    closing = rows[2].detail
    assert closing["closed"] == "exit" and closing["refreshes"] == 3
    assert closing["queryHash"] == rows[1].detail["queryHash"] and "query" not in closing
    assert audit.flush("exit") == 0
    env.q(live=True)  # after a flush the next refresh opens a fresh window
    assert len(env.rows("results.live")) == 4


def test_live_audit_evicts_the_oldest_window_with_its_tally(env):
    audit = live_audit_for(env.svc.builder)
    audit.max_windows = 2
    env.q(live=True)
    env.q(live=True)
    env.q(live=True, denominator="shown")
    env.q(live=True, intervals=True)  # a third window: the first is evicted
    rows = env.rows("results.live")
    assert len(rows) == 4 and len(audit) == 2
    assert rows[3].detail["closed"] == "evicted" and rows[3].detail["refreshes"] == 2


def test_live_audit_unit_window_boundary(env):
    """Exactly ``window`` after opening a window is already outside it."""
    writes: list[dict] = []

    class FakeStore:
        def audit(self, ctx, action, target_type, target_id, detail):
            writes.append({"action": action, "target": target_id, **detail})

    clock = FakeClock()
    audit = LiveAudit(FakeStore(), clock=clock.now, window=timedelta(minutes=15))
    ctx = TenantContext("lab", "user")
    detail = {"query": {}, "versions": [1], "queryHash": "h", "cached": False}
    assert audit.record(ctx, "s", "h", "w1", detail) is True
    clock.advance(minutes=14, seconds=59)
    assert audit.record(ctx, "s", "h", "w2", detail) is False
    clock.advance(seconds=1)
    assert audit.record(ctx, "s", "h", "w3", detail) is True
    assert [w["action"] for w in writes] == ["results.live", "results.live"]
    assert writes[1]["previous"]["refreshes"] == 2
    assert writes[1]["previous"]["lastWatermark"] == "w2" and writes[1]["watermark"] == "w3"


# -- single-flight cache -----------------------------------------------------------------


def test_cache_single_flight_computes_once_for_concurrent_identical_misses():
    cache = ResultsCache()
    key = ("t", "s", (1,), "wm", "hash")
    waiters = 8
    go = threading.Event()
    arrived = threading.Barrier(waiters + 1)
    calls = []
    results: list[tuple] = []

    def compute():
        calls.append(1)
        go.wait(5)
        return {"responses": 42}

    def worker():
        arrived.wait(5)
        results.append(cache.get_or_compute(key, compute))

    threads = [threading.Thread(target=worker) for _ in range(waiters)]
    for th in threads:
        th.start()
    arrived.wait(5)  # every worker is about to ask
    deadline = threading.Event()
    for _ in range(200):  # until the leader is inside compute() and the rest are waiting
        if calls and cache.in_flight == 1:
            break
        deadline.wait(0.01)
    assert len(calls) == 1 and cache.in_flight == 1
    go.set()
    for th in threads:
        th.join(5)
    assert len(calls) == 1 and len(results) == waiters
    values = {id(v) for v, _hit in results}
    assert len(values) == 1 and results[0][0] == {"responses": 42}
    assert sorted(hit for _v, hit in results) == [False] + [True] * (waiters - 1)
    assert cache.in_flight == 0 and len(cache) == 1
    assert cache.get_or_compute(key, compute) == ({"responses": 42}, True)
    assert len(calls) == 1


def test_cache_single_flight_errors_reach_every_waiter_and_do_not_stick():
    cache = ResultsCache()
    key = ("t", "s", (1,), "wm", "hash")
    go = threading.Event()
    calls = []
    outcomes: list[str] = []

    def failing():
        calls.append(1)
        go.wait(5)
        raise InvalidRequest("split question 'x' not found")

    def worker():
        try:
            cache.get_or_compute(key, failing)
        except InvalidRequest as exc:
            outcomes.append(exc.message)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for th in threads:
        th.start()
    for _ in range(200):
        if calls and cache.in_flight == 1:
            break
        go.wait(0.01)
    go.set()
    for th in threads:
        th.join(5)
    assert len(calls) == 1 and outcomes == ["split question 'x' not found"] * 4
    assert cache.in_flight == 0 and len(cache) == 0
    assert cache.get_or_compute(key, lambda: "fixed") == ("fixed", False)
