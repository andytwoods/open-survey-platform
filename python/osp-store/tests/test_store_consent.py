"""Consent before collection, declines and withdrawal (M5, semantics.md §11)."""

from __future__ import annotations

import uuid

import pytest
from osp_store import NotFound, ParticipantStore
from osp_store import schema as t
from sqlalchemy import func, select

ANS = {"q1": {"state": "answered", "value": 3}}


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
        {"checksum": "abc"},
        "abc",
        "every-page",
        {"surveyVersion": "1"},
        quotas={"women": 5},
        balanced={"arm": ["a", "b"]},
    )


def least(_variable, counts):
    low = min(n for _, n in counts)
    return next(lv for lv, n in counts if n == low)


def start(ps, ctx, pub):
    return ps.start(ctx, pub.id, 7, {}, uuid.uuid4().hex * 2, balanced=("arm",), choose=least)


def count(engine, table) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def test_consent_is_recorded_once_with_server_time(ps, pub, tenants, clock):
    a, _ = tenants
    s = start(ps, a, pub)
    assert ps.get(a, s.id).consented_at is None
    r = ps.record_consent(a, s.id, "sha256:v1")
    assert (r.status, r.version, r.consented_at) == ("ok", "sha256:v1", clock.now)
    clock.advance(seconds=5)
    again = ps.record_consent(a, s.id, "sha256:v1")
    assert (again.status, again.consented_at) == ("replay", r.consented_at)
    assert ps.record_consent(a, s.id, "sha256:v2").status == "mismatch"
    got = ps.get(a, s.id)
    assert (got.consent_version, got.consented_at) == ("sha256:v1", r.consented_at)


def test_decline_deletes_the_session_and_keeps_only_a_count(ps, pub, tenants, store, engine):
    a, _ = tenants
    s = start(ps, a, pub)
    audit_before = count(engine, t.audit_log)
    assert ps.assignment_counts(a, pub.id)["arm"] == {"a": 1, "b": 0}
    assert ps.decline(a, s.id, count=True) is True
    with pytest.raises(NotFound):
        ps.get(a, s.id)
    assert count(engine, t.sessions) == 0
    assert count(engine, t.participant_sessions) == 0
    assert ps.assignment_counts(a, pub.id)["arm"] == {"a": 0, "b": 0}  # place given back
    assert ps.decline_count(a, pub.id) == 1
    assert count(engine, t.audit_log) == audit_before  # nothing about the participant


def test_decline_without_counting_leaves_no_trace(ps, pub, tenants):
    a, _ = tenants
    s = start(ps, a, pub)
    assert ps.decline(a, s.id) is True
    assert ps.decline_count(a, pub.id) == 0


def test_decline_after_agreeing_changes_nothing(ps, pub, tenants):
    a, _ = tenants
    s = start(ps, a, pub)
    ps.record_consent(a, s.id, "sha256:v1")
    assert ps.decline(a, s.id, count=True) is False
    assert ps.get(a, s.id).consented_at is not None
    assert ps.decline_count(a, pub.id) == 0


def test_decline_is_tenant_scoped(ps, pub, tenants):
    a, b = tenants
    s = start(ps, a, pub)
    with pytest.raises(NotFound):
        ps.decline(b, s.id)


def test_withdraw_after_submit_deletes_response_and_session(ps, pub, tenants, store, engine):
    a, _ = tenants
    s = start(ps, a, pub)
    ps.record_consent(a, s.id, "sha256:v1")
    r = ps.submit(
        a,
        s.id,
        answers=ANS,
        record={"answers": ANS},
        record_checksum="c" * 64,
        realised_orders={},
        engine_version="1",
    )
    assert ps.withdraw(a, s.id, "participant withdrawal") == 1
    with pytest.raises(NotFound):
        store.get_response(a, r.response_id)
    assert count(engine, t.response_records) == 0
    assert count(engine, t.participant_sessions) == 0
    entry = next(e for e in store.list_audit(a) if e.action == "session.delete")
    assert entry.target_id == s.id
    assert entry.detail == {"reason": "participant withdrawal", "responses_deleted": 1}
    assert "3" not in str(entry.detail)  # no answer data in the audit log


def test_withdraw_before_submit_gives_back_held_places(ps, pub, tenants):
    a, _ = tenants
    s = start(ps, a, pub)
    ps.record_consent(a, s.id, "sha256:v1")
    assert ps.claim_quota(a, s.id, "qc1", "women").result == "admitted"
    assert ps.quota_usage(a, pub.id)["women"] == (1, 5)
    assert ps.withdraw(a, s.id, "participant withdrawal") == 0
    assert ps.quota_usage(a, pub.id)["women"] == (0, 5)
    assert ps.assignment_counts(a, pub.id)["arm"] == {"a": 0, "b": 0}
