"""Tenant isolation: every repository method fails closed across tenants.

A row in another tenant is indistinguishable from a missing row (NotFound), and
writes aimed at it change nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from osp_store import (
    AccessDenied,
    NotFound,
    OpRecord,
    RetentionPolicy,
    Store,
    SystemContext,
    TenantContext,
)
from osp_store import schema as t
from osp_store.store import is_constraint_violation
from sqlalchemy import insert
from sqlalchemy.exc import DBAPIError

ANS = {"q1": {"state": "answered", "value": 3}}


@dataclass
class World:
    a: TenantContext
    b: TenantContext
    user_a: str
    survey_a: str
    version_a: str
    session_a: str
    response_a: str


@pytest.fixture
def world(store: Store, tenants) -> World:
    a, b = tenants
    survey, _ = store.create_survey(a, "A's survey", {"secret": "a"})
    store.save_draft(a, survey.id, {"secret": "a2"}, 0, ops=[OpRecord("x", {}, {})])
    store.set_totp_secret(a, a.actor, "JBSWY3DPEHPK3PXP")
    v = store.publish_version(a, survey.id, b"<xform/>")
    s = store.start_session(a, v.id, 7, {"arm": "A"})
    r = store.record_response(a, v.id, ANS, session_id=s.id)
    return World(a, b, a.actor, survey.id, v.id, s.id, r.id)


READS: dict[str, Callable[[Store, World], object]] = {
    "get_user": lambda s, w: s.get_user(w.b, w.user_a),
    "get_totp_secret": lambda s, w: s.get_totp_secret(w.b, w.user_a),
    "get_survey": lambda s, w: s.get_survey(w.b, w.survey_a),
    "get_draft": lambda s, w: s.get_draft(w.b, w.survey_a),
    "list_ops": lambda s, w: s.list_ops(w.b, w.survey_a),
    "get_version": lambda s, w: s.get_version(w.b, w.version_a),
    "get_session": lambda s, w: s.get_session(w.b, w.session_a),
    "get_response": lambda s, w: s.get_response(w.b, w.response_a),
    "list_responses": lambda s, w: s.list_responses(w.b, w.version_a),
}

WRITES: dict[str, Callable[[Store, World], object]] = {
    "set_password_hash": lambda s, w: s.set_password_hash(w.b, w.user_a, "pwned"),
    "set_role": lambda s, w: s.set_role(w.b, w.user_a, "admin"),
    "set_totp_secret": lambda s, w: s.set_totp_secret(w.b, w.user_a, "AAAA"),
    "clear_totp_secret": lambda s, w: s.set_totp_secret(w.b, w.user_a, None),
    "record_login_failure": lambda s, w: s.record_login_failure(w.b, w.user_a),
    "reset_login_failures": lambda s, w: s.reset_login_failures(w.b, w.user_a),
    "save_draft": lambda s, w: s.save_draft(w.b, w.survey_a, {"x": 1}, 1),
    "set_retention": lambda s, w: s.set_retention(
        w.b, w.survey_a, RetentionPolicy.days_after_close(0)
    ),
    "close_survey": lambda s, w: s.close_survey(w.b, w.survey_a),
    "publish_version": lambda s, w: s.publish_version(w.b, w.survey_a, b"x"),
    "start_session": lambda s, w: s.start_session(w.b, w.version_a, 1, {}),
    "update_session": lambda s, w: s.update_session(w.b, w.session_a, instance={"x": 1}),
    "delete_session": lambda s, w: s.delete_session(w.b, w.session_a),
    "record_response": lambda s, w: s.record_response(w.b, w.version_a, ANS, session_seed=1),
    "record_response_via_session": lambda s, w: s.record_response(
        w.b, w.version_a, ANS, session_id=w.session_a
    ),
    "delete_response": lambda s, w: s.delete_response(w.b, w.response_a),
}


def _snapshot(store: Store, w: World) -> tuple:
    a = w.a
    return (
        store.get_user(a, w.user_a),
        store.get_totp_secret(a, w.user_a),
        store.get_survey(a, w.survey_a),
        store.get_draft(a, w.survey_a),
        store.list_ops(a, w.survey_a),
        store.list_versions(a, w.survey_a),
        store.get_session(a, w.session_a),
        [r.id for r in store.list_responses(a, w.version_a)],
    )


@pytest.mark.parametrize("name", sorted(READS))
def test_cross_tenant_read_fails_closed(store, world, name):
    with pytest.raises(NotFound):
        READS[name](store, world)


@pytest.mark.parametrize("name", sorted(WRITES))
def test_cross_tenant_write_fails_closed_and_changes_nothing(store, world, name):
    before = _snapshot(store, world)
    with pytest.raises(NotFound):
        WRITES[name](store, world)
    assert _snapshot(store, world) == before


def test_owner_can_do_everything_the_attacker_cannot(store, world):
    # Sanity: the same calls succeed in the owning tenant, so the tests above
    # fail because of the tenant, not because the calls are broken.
    owner = World(world.b, world.a, *list(vars(world).values())[2:])
    for fn in READS.values():
        fn(store, owner)
    assert store.get_totp_secret(world.a, world.user_a) == "JBSWY3DPEHPK3PXP"


def test_lists_only_show_own_tenant(store, world, sys_ctx):
    assert store.list_surveys(world.b) == []
    assert [u.id for u in store.list_users(world.b)] != [world.user_a]
    assert world.user_a not in {u.id for u in store.list_users(world.b)}
    assert all(e.tenant_id == world.b.tenant_id for e in store.list_audit(world.b))
    assert store.list_versions(world.b, world.survey_a) == []
    assert store.get_tenant(world.b).id == world.b.tenant_id


def test_audit_is_tenant_scoped(store, world):
    a_actions = {e.action for e in store.list_audit(world.a)}
    assert {"survey.create", "version.publish", "user.totp.set"} <= a_actions
    b_targets = {e.target_id for e in store.list_audit(world.b)}
    assert world.survey_a not in b_targets


@pytest.mark.parametrize(
    "ctx",
    [
        None,
        "tenant-a",
        {"tenant_id": "x", "actor": "y"},
        TenantContext("", "u"),
        TenantContext("t", ""),
        TenantContext("t", "x" * 81),
        SystemContext("system:test"),
    ],
)
def test_missing_or_malformed_context_is_denied(store, world, ctx):
    with pytest.raises(AccessDenied):
        store.get_survey(ctx, world.survey_a)
    with pytest.raises(AccessDenied):
        store.save_draft(ctx, world.survey_a, {}, 1)


def test_tenant_context_cannot_run_system_jobs(store, world):
    for call in (
        lambda: store.run_retention(world.a),
        lambda: store.rotate_keys(world.a),
        lambda: store.create_tenant(world.a, "x"),
        lambda: store.find_user_for_login(world.a, "r@a.example"),
        lambda: store.run_retention(SystemContext("not-system")),
    ):
        with pytest.raises(AccessDenied):
            call()


def test_unknown_tenant_cannot_create_rows(store, world):
    ghost = TenantContext("00000000-0000-0000-0000-000000000000", "u")
    with pytest.raises(NotFound):
        store.create_survey(ghost, "x", {})
    with pytest.raises(NotFound):
        store.create_user(ghost, "g@example.org", "researcher")


@pytest.mark.parametrize("bad_id", [None, 1, "", "x" * 37, ["id"]])
def test_hostile_ids_are_not_found(store, world, bad_id):
    with pytest.raises(NotFound):
        store.get_survey(world.a, bad_id)


def test_db_refuses_child_row_pointing_at_other_tenant(engine, world):
    # Defence in depth: composite (tenant_id, id) foreign keys reject a row in
    # tenant B that references tenant A's version, even if app code had a bug.
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(DBAPIError) as exc, engine.begin() as conn:
        conn.execute(
            insert(t.sessions).values(
                id="evil-session",
                tenant_id=world.b.tenant_id,
                version_id=world.version_a,
                session_seed=1,
                assigned_conditions={},
                realised_orders={},
                started_at=now,
                updated_at=now,
            )
        )
    assert is_constraint_violation(exc.value)
