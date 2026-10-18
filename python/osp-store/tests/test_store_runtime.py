"""Participant runtime tables (task R2): conditional snapshots, atomic + idempotent quotas,
balanced assignment, submit-once, inactivity release, tenancy. SQLite and Postgres."""

from __future__ import annotations

import threading
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from osp_store import (
    AccessDenied,
    Conflict,
    NotFound,
    ParticipantStore,
    SystemContext,
    TenantContext,
)
from osp_store import schema as t
from sqlalchemy import select, update

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


def test_stale_write_judged_inside_the_transaction(ps, pub, tenants):
    """R9-1: the caller's judge settles a stale write against the copy held right then."""
    a, _ = tenants
    s = start(ps, a, pub)
    ps.write_snapshot(a, s.id, 0, {"v": 1})
    seen = []

    def judge(verdict):
        def j(server, revision):
            seen.append((server, revision))
            return verdict

        return j

    ff = ps.write_snapshot(a, s.id, 5, {"v": 2}, judge("fast-forward"))  # base ahead
    assert (ff.status, ff.revision) == ("ok", 2) and seen == [({"v": 1}, 1)]
    assert ps.get(a, s.id).snapshot == {"v": 2}
    old = ps.write_snapshot(a, s.id, 0, {"v": 1}, judge("superseded"))
    assert (old.status, old.revision) == ("superseded", 2)
    no = ps.write_snapshot(a, s.id, 0, {"v": "other"}, judge(None))
    assert no.status == "stale" and len(ps.list_conflicts(a, s.id)) == 1
    assert ps.get(a, s.id).snapshot == {"v": 2}
    # A current base never asks the judge.
    seen.clear()
    assert ps.write_snapshot(a, s.id, 2, {"v": 3}, judge(None)).status == "ok" and not seen


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
    assert ps.get(a, active.id).expired_at is None
    assert ps.release_inactive(SYS, clock.now - timedelta(hours=24)).sessions_expired == 0
    # Releasing holds does not close the session (decision S-1): writes still work, and
    # the first one takes the released places back.
    assert ps.get(a, idle.id).expired_at is not None
    assert ps.write_snapshot(a, idle.id, 0, {"v": 1}).status == "ok"
    assert ps.get(a, idle.id).expired_at is None
    assert ps.quota_usage(a, pub.id)["women"] == (2, 50)
    assert ps.assignment_counts(a, pub.id)["arm"] == {"a": 1, "b": 1, "c": 0}


def _small_pub(store, ps, ctx, cap):
    survey, _ = store.create_survey(ctx, "S", {"blocks": []})
    version = store.publish_version(ctx, survey.id, b"", meta={})
    return ps.create_publication(
        ctx,
        version.id,
        "slug-" + uuid.uuid4().hex[:8],
        {"checksum": "abc"},
        "abc",
        "every-page",
        {"surveyVersion": "1"},
        quotas={"women": cap},
        balanced={"arm": ["a", "b"]},
    )


def _submit(ps, ctx, sid, checksum="c", record=None, **kw):
    record = {"r": 1, "server": {"late": False}} if record is None else record
    return ps.submit(ctx, sid, answers=ANS, record=record,
                     record_checksum=checksum * 64, realised_orders={},
                     engine_version=None, **kw)  # fmt: skip


def test_resume_retakes_released_holds(store, ps, tenants, clock):
    a, _ = tenants
    p = _small_pub(store, ps, a, cap=1)
    s = start(ps, a, p, balanced=("arm",))
    assert ps.claim_quota(a, s.id, "qc1", "women").result == "admitted"
    clock.advance(hours=25)
    assert ps.release_inactive(SYS, clock.now - timedelta(hours=24)).quota_slots_released == 1
    assert ps.quota_usage(a, p.id)["women"] == (0, 1)
    assert ps.touch(a, s.id) is True
    got = ps.get(a, s.id)
    assert got.expired_at is None
    assert ps.quota_usage(a, p.id)["women"] == (1, 1)
    assert ps.assignment_counts(a, p.id)["arm"] == {"a": 1, "b": 0}
    assert ps.touch(a, s.id) is True  # idempotent: nothing taken twice
    assert ps.quota_usage(a, p.id)["women"] == (1, 1)
    assert ps.claim_quota(a, s.id, "qc1", "women").status == "replay"
    r = _submit(ps, a, s.id)
    assert (r.status, r.late) == ("ok", False)
    assert ps.quota_usage(a, p.id)["women"] == (1, 1)  # used up on completion


def test_place_taken_meanwhile_leaves_holds_released_and_submit_is_late(store, ps, tenants, clock):
    a, _ = tenants
    p = _small_pub(store, ps, a, cap=1)
    s = start(ps, a, p, balanced=("arm",))
    ps.claim_quota(a, s.id, "qc1", "women")
    clock.advance(hours=25)
    ps.release_inactive(SYS, clock.now - timedelta(hours=24))
    other = start(ps, a, p)
    assert ps.claim_quota(a, other.id, "qc1", "women").result == "admitted"
    # Resuming finds the quota full: nothing is taken, the participant carries on.
    assert ps.touch(a, s.id) is True
    assert ps.get(a, s.id).expired_at is not None
    assert ps.quota_usage(a, p.id)["women"] == (1, 1)
    assert ps.assignment_counts(a, p.id)["arm"] == {"a": 0, "b": 0}
    assert ps.write_snapshot(a, s.id, 0, {"v": 1}).status == "ok"
    # A new check while holds are released answers, but holds no place.
    assert ps.claim_quota(a, s.id, "qc2", "women").result == "full"
    r = _submit(ps, a, s.id)
    assert (r.status, r.late) == ("ok", True)
    assert ps.quota_usage(a, p.id)["women"] == (1, 1)  # not counted
    assert ps.get_record(a, r.response_id)["server"]["late"] is True
    # Identical retry: the original success, still late; different data: mismatch.
    again = _submit(ps, a, s.id)
    assert (again.status, again.response_id, again.submitted_at, again.late) == (
        "replay", r.response_id, r.submitted_at, True
    )  # fmt: skip
    assert _submit(ps, a, s.id, checksum="d").status == "mismatch"


def test_late_flag_from_caller_releases_remaining_holds(store, ps, tenants):
    a, _ = tenants
    p = _small_pub(store, ps, a, cap=5)
    s = start(ps, a, p, balanced=("arm",))
    ps.claim_quota(a, s.id, "qc1", "women")
    r = _submit(ps, a, s.id, late=True)
    assert (r.status, r.late) == ("ok", True)
    assert ps.quota_usage(a, p.id)["women"] == (0, 5)  # a late submit is not counted
    assert ps.assignment_counts(a, p.id)["arm"] == {"a": 0, "b": 0}
    assert ps.get_record(a, r.response_id) == {"r": 1, "server": {"late": True}}


def _ended(outcome):
    return {"record": {"end": outcome, "answers": ANS}, "server": {"late": False}}


def test_non_complete_outcome_releases_the_quota_place_and_is_a_column(store, ps, tenants):
    """Lead decision 5 (end-of-survey plan §4.5): quota places count completes only."""
    a, _ = tenants
    p = _small_pub(store, ps, a, cap=1)
    s = start(ps, a, p, balanced=("arm",))
    assert ps.claim_quota(a, s.id, "qc1", "women").result == "admitted"
    assert ps.quota_usage(a, p.id)["women"] == (1, 1)
    r = _submit(ps, a, s.id, record=_ended("screened_out"))
    assert (r.status, r.late) == ("ok", False)
    assert ps.quota_usage(a, p.id)["women"] == (0, 1)  # the place is free again
    assert ps.assignment_counts(a, p.id)["arm"] == {"a": 1, "b": 0}  # counted at start
    assert store.get_response(a, r.response_id).outcome == "screened_out"
    [e] = [e for e in store.list_audit(a) if e.action == "response.submit"]
    assert e.detail["outcome"] == "screened_out" and e.detail["quota_released"] == 1
    # Another participant can take the place; a repeated submit releases nothing twice.
    other = start(ps, a, p)
    assert ps.claim_quota(a, other.id, "qc1", "women").result == "admitted"
    assert _submit(ps, a, s.id, record=_ended("screened_out")).status == "replay"
    assert ps.quota_usage(a, p.id)["women"] == (1, 1)
    # The submitted session stays submitted: no snapshot can take the place back.
    assert ps.write_snapshot(a, s.id, 1, {"v": 2}).status == "submitted"
    assert ps.quota_usage(a, p.id)["women"] == (1, 1)


def test_complete_outcome_keeps_the_place_even_after_withdrawal(store, ps, tenants):
    """Semantics §6 and C-1: a completed response's place stays used."""
    a, _ = tenants
    p = _small_pub(store, ps, a, cap=1)
    s = start(ps, a, p)
    ps.claim_quota(a, s.id, "qc1", "women")
    r = _submit(ps, a, s.id, record=_ended("complete"))
    assert store.get_response(a, r.response_id).outcome == "complete"
    assert ps.quota_usage(a, p.id)["women"] == (1, 1)
    assert ps.withdraw(a, s.id, "changed my mind") == 1
    assert ps.quota_usage(a, p.id)["women"] == (1, 1)  # C-1: the place stays used


def test_outcome_column_is_null_without_a_usable_end(store, ps, tenants):
    a, _ = tenants
    p = _small_pub(store, ps, a, cap=1)
    for checksum, record in (
        ("c", {"r": 1, "server": {"late": False}}),  # no record.end at all
        ("d", {"record": {"end": 5}, "server": {}}),  # not a string
        ("e", {"record": {"end": "x" * 81}, "server": {}}),  # too long
    ):
        s = start(ps, a, p)
        ps.claim_quota(a, s.id, "qc1", "women")
        r = _submit(ps, a, s.id, checksum=checksum, record=record)
        assert store.get_response(a, r.response_id).outcome is None
        # Nothing to go on: the place is treated as used (as before migration 0011)...
        assert ps.quota_usage(a, p.id)["women"] == (1, 1)
        with store.engine.begin() as conn:  # ...so make room for the next case
            conn.execute(update(t.quota_counters).values(used=0))


def test_outcome_counts_and_complete_only_stream_use_the_column(store, ps, tenants):
    a, _ = tenants
    p = _small_pub(store, ps, a, cap=5)
    for checksum, outcome in (("c", "complete"), ("d", "complete"), ("e", "screened_out")):
        s = start(ps, a, p)
        _submit(ps, a, s.id, checksum=checksum, record=_ended(outcome))
    legacy = start(ps, a, p)
    _submit(ps, a, legacy.id, checksum="f", record={"r": 1, "server": {}})
    assert ps.outcome_counts(a, p.version_id) == {"complete": 2, "screened_out": 1, None: 1}
    every = Counter(r.outcome for r, _rec in ps.stream_responses(a, p.version_id))
    assert every == {"complete": 2, "screened_out": 1, None: 1}
    complete = ps.stream_responses(a, p.version_id, complete_only=True)
    assert Counter(r.outcome for r, _rec in complete) == {"complete": 2, None: 1}  # NULL kept
    assert len(store.list_audit(a)) >= 2


def test_backfill_outcomes_reads_the_record_once_and_is_idempotent(store, ps, tenants, sys_ctx):
    a, _ = tenants
    p = _small_pub(store, ps, a, cap=5)
    ids = {}
    for checksum, record in (
        ("c", _ended("quota_full")),
        ("d", _ended("complete")),
        ("e", {"record": {"noEnd": True}, "server": {}}),
    ):
        s = start(ps, a, p)
        ids[checksum] = _submit(ps, a, s.id, checksum=checksum, record=record).response_id
    no_record = store.record_response(a, p.version_id, ANS, session_seed=3)  # a row only
    with store.engine.begin() as conn:  # as rows stored before migration 0011 look
        conn.execute(update(t.responses).values(outcome=None))
    assert ps.outcome_counts(a, p.version_id) == {None: 4}
    report = ps.backfill_outcomes(sys_ctx, batch=2)
    assert (report.scanned, report.updated) == (3, 2)
    assert store.get_response(a, ids["c"]).outcome == "quota_full"
    assert store.get_response(a, ids["d"]).outcome == "complete"
    assert store.get_response(a, ids["e"]).outcome is None
    assert store.get_response(a, no_record.id).outcome is None
    again = ps.backfill_outcomes(sys_ctx)
    assert (again.scanned, again.updated) == (1, 0)  # only the record without an end
    al = t.audit_log.c
    with store.engine.connect() as conn:
        rows = conn.execute(
            select(al.tenant_id, al.detail)
            .where(al.action == "responses.backfill_outcome")
            .order_by(al.id)
        ).all()
    assert [tuple(r) for r in rows] == [
        (None, {"scanned": 3, "updated": 2}),
        (None, {"scanned": 1, "updated": 0}),
    ]
    with pytest.raises(AccessDenied):
        ps.backfill_outcomes(a)  # a tenant context is not a system context


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


# -- public slugs and republish (R2b, migration 0005) ---------------------------------


def _publish(store, ps, ctx, survey, slug, checksum):
    version = store.publish_version(ctx, survey.id, b"", meta={})
    return ps.create_publication(
        ctx, version.id, slug, {"checksum": checksum}, checksum, "every-page", {}
    )


def test_surveys_get_a_unique_public_slug(store, tenants):
    a, b = tenants
    slugs = {store.create_survey(ctx, "S", {})[0].public_slug for ctx in (a, b, a, b)}
    assert len(slugs) == 4 and all(len(s) == 10 and s.isalnum() for s in slugs)
    survey, _ = store.create_survey(a, "S", {})
    assert store.ensure_public_slug(a, survey.id) == survey.public_slug
    with store._tx() as conn:  # a pre-0005 row: no slug yet
        conn.execute(update(t.surveys).where(t.surveys.c.id == survey.id).values(public_slug=None))
    slug = store.ensure_public_slug(a, survey.id)
    assert slug and slug != survey.public_slug
    assert store.get_survey(a, survey.id).public_slug == slug
    with pytest.raises(NotFound):
        store.ensure_public_slug(b, survey.id)  # another tenant's survey


def test_republish_under_one_slug_newest_version_wins(store, ps, tenants):
    a, _ = tenants
    survey, _ = store.create_survey(a, "S", {})
    p1 = _publish(store, ps, a, survey, survey.public_slug, "c1")
    p2 = _publish(store, ps, a, survey, survey.public_slug, "c2")
    assert ps.find_publication(SYS, survey.public_slug).id == p2.id
    assert ps.find_publication(SYS, survey.public_slug, "c1").id == p1.id
    assert ps.find_publication(SYS, survey.public_slug, "c3") is None
    other, _ = store.create_survey(a, "T", {})
    with pytest.raises(Conflict):  # a slug belongs to one survey
        _publish(store, ps, a, other, survey.public_slug, "c4")


def test_publish_version_body_callable_gets_the_number(store, tenants):
    a, _ = tenants
    survey, _ = store.create_survey(a, "S", {})
    seen = []

    def body(n):
        seen.append(n)
        return {"version": n}

    v1 = store.publish_version(a, survey.id, b"", body=body)
    v2 = store.publish_version(a, survey.id, b"", body=body)
    assert seen == [1, 2] and (v1.body, v2.body) == ({"version": 1}, {"version": 2})
