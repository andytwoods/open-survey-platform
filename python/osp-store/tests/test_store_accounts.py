"""AccountStore (C10, migration 0004_accounts): sign-in state, auth sessions, draft delete."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from osp_store import (
    AccessDenied,
    AccountStore,
    AuthSessionRow,
    Conflict,
    NotFound,
    SystemContext,
    TenantContext,
)
from osp_store import schema as t
from sqlalchemy import select


@pytest.fixture
def acc(store) -> AccountStore:
    return AccountStore(store)


def _add(acc, sys_ctx, tenant_id, clock, uid="u1", email="r@x.example"):
    acc.add_user(
        sys_ctx,
        user_id=uid,
        tenant_id=tenant_id,
        email=email,
        role="editor",
        password_hash="h",
        created_at=clock(),
    )


def test_user_round_trip_encrypts_secrets(acc, store, sys_ctx, tenants, clock, engine):
    a, _ = tenants
    _add(acc, sys_ctx, a.tenant_id, clock)
    u = acc.get_user(sys_ctx, "u1")
    assert u.email == "r@x.example" and u.recovery_code_hashes == () and u.totp_secret is None
    acc.save_user(
        sys_ctx,
        replace(
            u,
            totp_secret="CONFIRMEDSECRET",
            totp_pending_secret="PENDINGSECRET",
            totp_last_step=7,
            recovery_code_hashes=("h1", "h2"),
            failed_logins=3,
            locked_until=clock() + timedelta(minutes=1),
        ),
    )
    got = acc.get_user_by_email(sys_ctx, "R@X.example")
    assert (got.totp_secret, got.totp_pending_secret, got.totp_last_step) == (
        "CONFIRMEDSECRET",
        "PENDINGSECRET",
        7,
    )
    assert got.recovery_code_hashes == ("h1", "h2") and got.failed_logins == 3
    with engine.connect() as conn:
        blob = conn.execute(select(t.user_mfa.c.totp_pending_ct)).scalar_one()
    assert b"PENDINGSECRET" not in bytes(blob)
    assert any(e.action == "user.auth" for e in store.list_audit(a))
    with pytest.raises(Conflict):
        _add(acc, sys_ctx, a.tenant_id, clock, uid="u2")  # same email


def test_tenant_context_is_refused(acc, tenants):
    a, _ = tenants
    with pytest.raises(AccessDenied):
        acc.get_user(a, "u1")
    assert acc.get_user(SystemContext("system:x"), "") is None


def test_auth_sessions(acc, sys_ctx, tenants, clock):
    a, _ = tenants
    _add(acc, sys_ctx, a.tenant_id, clock)
    now = clock()
    row = AuthSessionRow("f" * 64, "u1", "full", now, now, now + timedelta(hours=1))
    acc.add_session(sys_ctx, row)
    with pytest.raises(Conflict):
        acc.add_session(sys_ctx, row)
    later = replace(row, last_seen_at=now + timedelta(minutes=5))
    acc.update_session(sys_ctx, later)
    assert acc.get_session(sys_ctx, row.id) == later
    assert acc.list_sessions_for_user(sys_ctx, "u1") == [later]
    acc.delete_sessions_for_user(sys_ctx, "u1")
    assert acc.get_session(sys_ctx, row.id) is None
    assert acc.get_session(sys_ctx, "x" * 65) is None


def test_delete_unpublished_survey_only(acc, store, tenants):
    a, b = tenants
    s1, _ = store.create_survey(a, "One", {"v": 1})
    s2, _ = store.create_survey(a, "Two", {"v": 2})
    store.save_draft(a, s1.id, {"v": 3}, 0)
    with pytest.raises(NotFound):
        acc.delete_unpublished_survey(b, s1.id)  # other tenant
    acc.delete_unpublished_survey(a, s1.id)
    with pytest.raises(NotFound):
        store.get_survey(a, s1.id)
    store.publish_version(a, s2.id, b"")
    with pytest.raises(Conflict):
        acc.delete_unpublished_survey(a, s2.id)
    acc.set_survey_title(a, s2.id, "Renamed")
    assert store.get_survey(a, s2.id).title == "Renamed"
    with pytest.raises(NotFound):
        acc.set_survey_title(TenantContext(b.tenant_id, b.actor), s2.id, "x")
