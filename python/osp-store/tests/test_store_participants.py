"""Sessions, responses (semantics §1, §7, §9), participant deletion and audit."""

from __future__ import annotations

import pytest
from osp_store import InvalidInput, NotFound

ANS = {
    "q1": {"state": "answered", "value": 3},
    "q2": {"state": "unanswered", "value": None},
    "q3": {"state": "irrelevant", "value": None},
    "q4": {"state": "not-reached"},
}


@pytest.fixture
def version(store, tenants):
    a, _ = tenants
    survey, _ = store.create_survey(a, "S", {"blocks": []})
    return store.publish_version(a, survey.id, b"<x/>", meta={"pyxform": "4.0"})


def test_session_lifecycle(store, tenants, version, clock):
    a, _ = tenants
    s = store.start_session(a, version.id, 123456789, {"arm": "B"}, {"block1": ["q2", "q1"]})
    clock.advance(seconds=30)
    s2 = store.update_session(
        a, s.id, current_page="p2", instance={"q1": 3}, add_orders={"block2": ["q4", "q3"]}
    )
    assert s2.current_page == "p2"
    assert s2.instance == {"q1": 3}
    assert s2.realised_orders == {"block1": ["q2", "q1"], "block2": ["q4", "q3"]}
    assert s2.updated_at > s2.started_at
    assert store.update_session(a, s.id, completed=True).completed_at == clock.now


def test_realised_orders_are_fixed_at_first_reach(store, tenants, version):
    a, _ = tenants
    s = store.start_session(a, version.id, 5, {}, {"block1": ["a", "b"]})
    store.update_session(a, s.id, add_orders={"block1": ["a", "b"]})  # same: fine
    with pytest.raises(InvalidInput, match="cannot change"):
        store.update_session(a, s.id, add_orders={"block1": ["b", "a"]})
    assert store.get_session(a, s.id).realised_orders == {"block1": ["a", "b"]}


@pytest.mark.parametrize("seed", [0, -1, 1.5, "7", True, None, 2**63])
def test_session_seed_must_be_positive_integer(store, tenants, version, seed):
    a, _ = tenants
    with pytest.raises(InvalidInput):
        store.start_session(a, version.id, seed, {})


def test_response_records_everything_semantics_requires(store, tenants, version, clock):
    a, _ = tenants
    s = store.start_session(a, version.id, 99, {"arm": "A"}, {"b1": ["q2", "q1"]})
    clock.advance(minutes=5)
    r = store.record_response(a, version.id, ANS, session_id=s.id, engine_version="0.1")
    assert r.version_id == version.id
    assert r.version_checksum == version.checksum  # §9
    assert r.allocation_mode == "server"  # §7
    assert r.session_seed == 99
    assert r.assigned_conditions == {"arm": "A"}
    assert r.realised_orders == {"b1": ["q2", "q1"]}
    assert r.answers == ANS  # §1 states preserved
    assert r.started_at == s.started_at and r.submitted_at == clock.now
    assert [x.id for x in store.list_responses(a, version.id)] == [r.id]


def test_limesurvey_native_response_needs_no_seed(store, tenants, version):
    a, _ = tenants
    r = store.record_response(
        a, version.id, ANS, "limesurvey-native", assigned_conditions={"arm": "A"}
    )
    assert r.session_seed is None and r.allocation_mode == "limesurvey-native"


@pytest.mark.parametrize(
    "answers",
    [
        [],
        {"q": 3},
        {"q": {"value": 3}},
        {"q": {"state": "skipped"}},
        {"q": {"state": "irrelevant", "value": 3}},
        {"q": {"state": "answered", "value": {1, 2}}},
    ],
)
def test_bad_answers_are_rejected(store, tenants, version, answers):
    a, _ = tenants
    with pytest.raises(InvalidInput):
        store.record_response(a, version.id, answers, session_seed=1)


def test_bad_allocation_is_rejected(store, tenants, version):
    a, _ = tenants
    with pytest.raises(InvalidInput):
        store.record_response(a, version.id, ANS, "random")
    with pytest.raises(InvalidInput, match="session_seed"):
        store.record_response(a, version.id, ANS, "server")


def test_session_from_other_version_is_rejected(store, tenants, version):
    a, _ = tenants
    other = store.publish_version(a, version.survey_id, b"<y/>")
    s = store.start_session(a, other.id, 1, {})
    with pytest.raises(InvalidInput):
        store.record_response(a, version.id, ANS, session_id=s.id)


def test_reading_responses_is_audited(store, tenants, version):
    a, _ = tenants
    r = store.record_response(a, version.id, ANS, session_seed=1)
    store.get_response(a, r.id)
    store.list_responses(a, version.id)
    entries = [(e.action, e.target_id, e.actor) for e in store.list_audit(a)]
    assert ("response.read", r.id, a.actor) in entries
    assert ("responses.read", version.id, a.actor) in entries


def test_participant_deletion_by_response_id(store, tenants, version):
    a, _ = tenants
    s = store.start_session(a, version.id, 3, {})
    store.update_session(a, s.id, instance={"q1": "draft"})
    r = store.record_response(a, version.id, ANS, session_id=s.id)
    keep = store.record_response(a, version.id, ANS, session_seed=4)

    store.delete_response(a, r.id, reason="consent withdrawn")

    with pytest.raises(NotFound):
        store.get_response(a, r.id)
    with pytest.raises(NotFound):
        store.get_session(a, s.id)  # the autosaved instance goes too
    assert [x.id for x in store.list_responses(a, version.id)] == [keep.id]
    entry = [e for e in store.list_audit(a) if e.action == "response.delete"][-1]
    assert entry.target_id == r.id
    assert entry.detail == {"reason": "consent withdrawn", "session_deleted": True}
    with pytest.raises(NotFound):
        store.delete_response(a, r.id)  # idempotent callers see NotFound, nothing else


def test_withdrawal_before_submission_deletes_session(store, tenants, version):
    a, _ = tenants
    s = store.start_session(a, version.id, 3, {})
    assert store.delete_session(a, s.id) == 0
    with pytest.raises(NotFound):
        store.get_session(a, s.id)


def test_audit_never_contains_answers(store, tenants, version):
    a, _ = tenants
    r = store.record_response(
        a, version.id, {"q1": {"state": "answered", "value": "SECRET-ANSWER"}}, session_seed=1
    )
    store.get_response(a, r.id)
    store.delete_response(a, r.id)
    assert "SECRET-ANSWER" not in repr(store.list_audit(a))
