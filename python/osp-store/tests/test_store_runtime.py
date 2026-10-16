"""Participant runtime tables (task R2): conditional snapshots, atomic + idempotent quotas,
balanced assignment, submit-once, inactivity release, tenancy. SQLite and Postgres."""

from __future__ import annotations

import threading
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from osp_store import NotFound, ParticipantStore, SystemContext, TenantContext
from osp_store import schema as t
from sqlalchemy import select

ANS = {"q1": {"state": "answered", "value": 3}, "q2": {"state": "not-reached"}}
SYS = SystemContext("system:test")


@pytest.fixture
def ps(store):
    return ParticipantStore(store)


@pytest.fixture
def pub(store, ps, tenants):
    a, _ = tenants
    survey, _ = store.create_survey(a, "S", {"blocks": []})
    version = store.publish_version(a, survey.id, b"", meta={})
    return ps.create_publication(
        a,
        version.id,
        "slug-" + uuid.uuid4().hex[:8],
        {"checksum": "abc", "nodes": []},
        "abc",
        "every-page",
        {"surveyVersion": "1"},
        quotas={"women": 50},
        balanced={"arm": ["a", "b", "c"]},
    )


def least(_variable, counts):
    low = min(n for _, n in counts)
    return next(lv for lv, n in counts if n == low)


def start(ps, ctx, pub, **kw):
    return ps.start(
        ctx, pub.id, 12345, {"framing": "gain"}, uuid.uuid4().hex * 2, choose=least, **kw
    )


def test_publication_lookup_by_slug(ps, pub):
    assert ps.find_publication(SYS, pub.slug).id == pub.id
    assert ps.find_publication(SYS, "nope") is None
    assert pub.plan == {"checksum": "abc", "nodes": []}


def test_start_records_seed_assignment_and_encrypted_url_params(ps, pub, tenants, engine):
    a, _ = tenants
    s = start(ps, a, pub, url_params={"PROLIFIC_PID": "x1"}, balanced=("arm",))
    got = ps.get(a, s.id)
    assert got.session_seed == 12345 and got.revision == 0
    assert got.assigned == {"framing": "gain", "arm": "a"}
    assert got.url_params == {"PROLIFIC_PID": "x1"}
    with engine.connect() as conn:
        raw = conn.execute(select(t.participant_sessions.c.url_params_ct)).scalar_one()
    assert b"x1" not in bytes(raw)  # encrypted at rest


def test_conditional_snapshot_write_and_conflict_kept(ps, pub, tenants, store):
    a, _ = tenants
    s = start(ps, a, pub)
    assert ps.write_snapshot(a, s.id, 0, {"v": 1}).status == "ok"
    assert ps.write_snapshot(a, s.id, 1, {"v": 2}).revision == 2
    # Lost ack: the same write again is a replay, not a conflict.
    r = ps.write_snapshot(a, s.id, 1, {"v": 2})
    assert (r.status, r.revision) == ("replay", 2)
    # Second device, stale base: server copy wins, the loser is kept (R-2).
    w = ps.write_snapshot(a, s.id, 0, {"v": "other device"})
    assert (w.status, w.revision, w.snapshot) == ("stale", 2, {"v": 2})
    assert ps.get(a, s.id).snapshot == {"v": 2}
    [c] = ps.list_conflicts(a, s.id)
    assert c.snapshot == {"v": "other device"} and c.base_revision == 0
    audit = [e for e in store.list_audit(a) if e.action == "session.snapshot_conflict"]
    assert audit and "other device" not in str(audit[0].detail)  # no participant data


def test_quota_is_idempotent_per_session_and_node(ps, pub, tenants):
    a, _ = tenants
    s = start(ps, a, pub)
    first = ps.claim_quota(a, s.id, "qc1", "women")
    again = ps.claim_quota(a, s.id, "qc1", "women")
    assert (first.status, first.result) == ("ok", "admitted")
    assert (again.status, again.result) == ("replay", "admitted")
    assert ps.quota_usage(a, pub.id)["women"] == (1, 50)


def test_200_parallel_quota_checks_against_limit_50_admit_exactly_50(ps, pub, tenants):
    a, _ = tenants
    sessions = [start(ps, a, pub).id for _ in range(200)]
    barrier = threading.Barrier(20)

    def claim(sid):
        try:
            barrier.wait(timeout=5)
        except threading.BrokenBarrierError:
            pass
        return ps.claim_quota(a, sid, "qc1", "women").result

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = Counter(pool.map(claim, sessions))
    assert results == {"admitted": 50, "full": 150}
    assert ps.quota_usage(a, pub.id)["women"] == (50, 50)
    # Retries after the race return the recorded results, never a new slot.
    with ThreadPoolExecutor(max_workers=20) as pool:
        again = Counter(
            pool.map(lambda sid: ps.claim_quota(a, sid, "qc1", "women").result, sessions)
        )
    assert again == results


def test_parallel_retries_from_one_session_take_one_slot(ps, pub, tenants):
    a, _ = tenants
    sid = start(ps, a, pub).id
    with ThreadPoolExecutor(max_workers=10) as pool:
        out = list(pool.map(lambda _: ps.claim_quota(a, sid, "qc1", "women"), range(30)))
    assert {o.result for o in out} == {"admitted"}
    assert sum(o.status == "ok" for o in out) == 1
    assert ps.quota_usage(a, pub.id)["women"] == (1, 50)


def test_parallel_balanced_assignment_stays_balanced(ps, pub, tenants):
    a, _ = tenants
    with ThreadPoolExecutor(max_workers=15) as pool:
        got = list(
            pool.map(lambda _: start(ps, a, pub, balanced=("arm",)).assigned["arm"], range(90))
        )
    assert Counter(got) == {"a": 30, "b": 30, "c": 30}
    assert ps.assignment_counts(a, pub.id) == {"arm": {"a": 30, "b": 30, "c": 30}}


def test_submit_once_then_snapshots_rejected(ps, pub, tenants, store):
    a, _ = tenants
    s = start(ps, a, pub)
    ps.write_snapshot(a, s.id, 0, {"v": 1})
    kw = dict(
        answers=ANS, record={"r": 1}, realised_orders={"b1": ["q2", "q1"]}, engine_version="0.1"
    )
    first = ps.submit(a, s.id, record_checksum="c" * 64, **kw)
    again = ps.submit(a, s.id, record_checksum="c" * 64, **kw)
    other = ps.submit(a, s.id, record_checksum="d" * 64, **kw)
    assert first.status == "ok" and again.status == "replay" and other.status == "mismatch"
    assert first.response_id == again.response_id
    resp = store.get_response(a, first.response_id)
    assert resp.answers == ANS and resp.session_seed == 12345
    assert resp.assigned_conditions == {"framing": "gain"}
    assert ps.get_record(a, first.response_id) == {"r": 1}
    assert len(store.list_responses(a, resp.version_id)) == 1
    assert ps.write_snapshot(a, s.id, 1, {"v": 2}).status == "submitted"
    assert ps.get(a, s.id).snapshot is None  # server copy cleared after submit


def test_end_only_rejects_snapshots(store, ps, tenants):
    a, _ = tenants
    survey, _ = store.create_survey(a, "S", {})
    v = store.publish_version(a, survey.id, b"", meta={})
    p = ps.create_publication(a, v.id, "eo", {"checksum": "x"}, "x", "end-only", {})
    s = ps.start(a, p.id, 7, {}, "e" * 64)
    assert ps.write_snapshot(a, s.id, 0, {"v": 1}).status == "end-only"
    assert ps.get(a, s.id).snapshot is None and ps.get(a, s.id).url_params is None


def test_cross_tenant_access_fails(ps, pub, tenants):
    a, b = tenants
    s = start(ps, a, pub)
    for call in (
        lambda: ps.get(b, s.id),
        lambda: ps.write_snapshot(b, s.id, 0, {"v": 1}),
        lambda: ps.claim_quota(b, s.id, "qc1", "women"),
        lambda: ps.submit(
            b,
            s.id,
            answers=ANS,
            record={},
            record_checksum="c" * 64,
            realised_orders={},
            engine_version=None,
        ),  # fmt: skip
        lambda: ps.get_publication(b, pub.id),
        lambda: ps.start(b, pub.id, 1, {}, "f" * 64),
    ):
        with pytest.raises(NotFound):
            call()
    assert ps.get(a, s.id).revision == 0
    assert ps.quota_usage(a, pub.id)["women"] == (0, 50)


def test_release_after_inactivity_gives_slots_back(ps, pub, tenants, clock):
    a, _ = tenants
    idle = start(ps, a, pub, balanced=("arm",))
    ps.claim_quota(a, idle.id, "qc1", "women")
    done = start(ps, a, pub, balanced=("arm",))
    ps.claim_quota(a, done.id, "qc1", "women")
    ps.submit(a, done.id, answers=ANS, record={}, record_checksum="c" * 64,
              realised_orders={}, engine_version=None)  # fmt: skip
    clock.advance(hours=23)
    active = start(ps, a, pub)
    assert ps.release_inactive(SYS, clock.now - timedelta(hours=24)).sessions_expired == 0
    clock.advance(hours=1)
    report = ps.release_inactive(SYS, clock.now - timedelta(hours=24))
    assert (report.sessions_expired, report.quota_slots_released) == (1, 1)
    assert report.assignment_slots_released == 1
    assert ps.quota_usage(a, pub.id)["women"] == (1, 50)  # the submitted one stays counted
    assert ps.assignment_counts(a, pub.id)["arm"] == {"a": 0, "b": 1, "c": 0}
    assert ps.write_snapshot(a, idle.id, 0, {"v": 1}).status == "expired"
    assert ps.claim_quota(a, idle.id, "qc2", "women").status == "expired"
    assert ps.get(a, active.id).expired_at is None
    assert ps.release_inactive(SYS, clock.now - timedelta(hours=24)).sessions_expired == 0


def test_withdrawal_removes_runtime_rows(ps, pub, tenants, store, engine):
    a, _ = tenants
    s = start(ps, a, pub)
    ps.write_snapshot(a, s.id, 0, {"v": 1})
    ps.write_snapshot(a, s.id, 0, {"v": "stale"})
    ps.claim_quota(a, s.id, "qc1", "women")
    store.delete_session(a, s.id)
    with engine.connect() as conn:
        for table in (t.participant_sessions, t.quota_claims, t.session_conflicts):
            assert conn.execute(select(table)).first() is None, table.name


def test_key_rotation_covers_runtime_fields(store, ps, pub, tenants, engine, clock):
    from osp_store import Keyring, Store

    a, _ = tenants
    s = start(ps, a, pub, url_params={"p": "1"})
    ps.write_snapshot(a, s.id, 0, {"v": 1})
    ps.write_snapshot(a, s.id, 0, {"v": "loser"})
    r = ps.submit(a, s.id, answers=ANS, record={"r": 1}, record_checksum="c" * 64,
                  realised_orders={}, engine_version=None)  # fmt: skip
    rotated = Store(
        engine, Keyring({"k1": "a" * 43 + "=", "k2": "b" * 43 + "="}, active="k2"), clock=clock
    )
    assert rotated.rotate_keys(SYS) >= 4
    assert set(rotated.count_by_key(SYS)) == {"k2"}
    ps2 = ParticipantStore(rotated)
    assert ps2.get(a, s.id).url_params == {"p": "1"}
    assert ps2.list_conflicts(a, s.id)[0].snapshot == {"v": "loser"}
    assert ps2.get_record(a, r.response_id) == {"r": 1}


def test_tenant_context_is_required(ps, pub):
    from osp_store import AccessDenied

    with pytest.raises(AccessDenied):
        ps.get(SYS, "x")  # type: ignore[arg-type]
    with pytest.raises(AccessDenied):
        ps.find_publication(TenantContext("t", "u"), "x")  # type: ignore[arg-type]
