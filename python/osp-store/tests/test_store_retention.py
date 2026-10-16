"""Retention: pure planner (no clock) + executor (injected clock)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from osp_store import InvalidInput, NotFound, RetentionPolicy, plan_retention
from osp_store.retention import ParticipantRow, SurveyFacts, deletion_due_at

T0 = datetime(2026, 3, 1, tzinfo=UTC)
ANS = {"q1": {"state": "answered", "value": 1}}

# -- pure planner ----------------------------------------------------------------


def test_due_dates():
    assert deletion_due_at(RetentionPolicy.none(), T0) is None
    assert deletion_due_at(RetentionPolicy.days_after_close(30), None) is None  # still open
    assert deletion_due_at(RetentionPolicy.days_after_close(30), T0) == T0 + timedelta(days=30)
    assert deletion_due_at(RetentionPolicy.after_date(T0), None) == T0


def _facts(sid, policy, closed=None, tenant="t1"):
    return SurveyFacts(tenant, sid, policy, closed)


def test_planner_picks_only_due_rows():
    surveys = [
        _facts("due", RetentionPolicy.days_after_close(10), closed=T0),
        _facts("not-yet", RetentionPolicy.days_after_close(10), closed=T0 + timedelta(days=5)),
        _facts("open", RetentionPolicy.days_after_close(0)),
        _facts("dated", RetentionPolicy.after_date(T0 + timedelta(days=10))),
        _facts("forever", RetentionPolicy.none(), closed=T0),
    ]
    rows = [ParticipantRow("response", f"r-{s.survey_id}", "t1", s.survey_id) for s in surveys] + [
        ParticipantRow("session", "s-due", "t1", "due")
    ]
    now = T0 + timedelta(days=10)  # boundary: exactly due counts as due
    plan = plan_retention(surveys, rows, now)
    assert [p.survey_id for p in plan.purges] == ["dated", "due"]
    assert set(plan.response_ids) == {"r-due", "r-dated"}
    assert plan.session_ids == ("s-due",)
    assert plan_retention(surveys, rows, now - timedelta(seconds=1)).purges == ()


def test_planner_matches_on_tenant_and_survey():
    surveys = [_facts("s1", RetentionPolicy.after_date(T0), tenant="t1")]
    rows = [ParticipantRow("response", "other-tenant", "t2", "s1")]
    assert plan_retention(surveys, rows, T0).purges == ()


def test_planner_needs_aware_now():
    with pytest.raises(InvalidInput):
        plan_retention([], [], datetime(2026, 1, 1))


@pytest.mark.parametrize(
    "policy",
    [
        RetentionPolicy("days_after_close", days=-1),
        RetentionPolicy("days_after_close"),
        RetentionPolicy("days_after_close", days=True),
        RetentionPolicy("after_date"),
        RetentionPolicy("after_date", until=datetime(2026, 1, 1)),
        RetentionPolicy("none", days=3),
        RetentionPolicy("sometimes"),  # type: ignore[arg-type]
    ],
)
def test_bad_policies_are_rejected(store, tenants, policy):
    a, _ = tenants
    survey, _ = store.create_survey(a, "S", {})
    with pytest.raises(InvalidInput):
        store.set_retention(a, survey.id, policy)


# -- executor --------------------------------------------------------------------


def _survey_with_data(store, ctx, n=2):
    survey, _ = store.create_survey(ctx, "S", {})
    v = store.publish_version(ctx, survey.id, b"<x/>")
    rids = []
    for i in range(n):
        s = store.start_session(ctx, v.id, i + 1, {})
        rids.append(store.record_response(ctx, v.id, ANS, session_id=s.id).id)
    abandoned = store.start_session(ctx, v.id, 99, {})
    return survey, v, rids, abandoned.id


def test_retention_deletes_after_n_days_and_audits(store, tenants, clock, sys_ctx):
    a, b = tenants
    clock.now = T0
    survey, v, rids, abandoned = _survey_with_data(store, a)
    other, ov, other_rids, _ = _survey_with_data(store, b)  # tenant B, no policy
    store.set_retention(a, survey.id, RetentionPolicy.days_after_close(30))

    assert store.run_retention(sys_ctx).purges == ()  # open survey: nothing
    store.close_survey(a, survey.id)
    clock.advance(days=29)
    assert store.plan_retention(sys_ctx).purges == ()
    assert len(store.list_responses(a, v.id)) == 2

    clock.advance(days=1)
    dry = store.plan_retention(sys_ctx)
    assert set(dry.response_ids) == set(rids) and len(dry.session_ids) == 3
    assert len(store.list_responses(a, v.id)) == 2  # dry run deleted nothing

    plan = store.run_retention(sys_ctx)
    assert set(plan.response_ids) == set(rids)
    assert store.list_responses(a, v.id) == []
    with pytest.raises(NotFound):
        store.get_session(a, abandoned)
    assert {r.id for r in store.list_responses(b, ov.id)} == set(other_rids)  # untouched

    entry = [e for e in store.list_audit(a) if e.action == "retention.purge"][-1]
    assert entry.actor == "system:test" and entry.target_id == survey.id
    assert entry.detail["responses_deleted"] == 2 and entry.detail["sessions_deleted"] == 3
    # Versions (the survey definition) are kept; only participant data goes.
    assert store.get_version(a, v.id).id == v.id

    assert store.run_retention(sys_ctx).purges == ()  # idempotent


def test_retention_after_fixed_date(store, tenants, clock, sys_ctx):
    a, _ = tenants
    clock.now = T0
    survey, v, _, _ = _survey_with_data(store, a, n=1)
    store.set_retention(a, survey.id, RetentionPolicy.after_date(T0 + timedelta(days=7)))
    clock.advance(days=6, hours=23)
    assert store.run_retention(sys_ctx).purges == ()
    clock.advance(hours=1)
    assert len(store.run_retention(sys_ctx).response_ids) == 1
    assert store.list_responses(a, v.id) == []


def test_policy_roundtrips(store, tenants):
    a, _ = tenants
    survey, _ = store.create_survey(a, "S", {})
    assert store.get_survey(a, survey.id).retention == RetentionPolicy.none()
    p = RetentionPolicy.after_date(T0)
    store.set_retention(a, survey.id, p)
    assert store.get_survey(a, survey.id).retention == p
