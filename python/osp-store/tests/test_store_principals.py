"""Host-owned identity (plan P, migration 0007): principals, labs by host id, audit names."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from osp_store import AccessDenied, InvalidInput, SystemContext, TenantContext, downgrade, migrate
from osp_store import schema as t
from sqlalchemy import insert, inspect, select


def test_touch_principal_inserts_then_updates(store, sys_ctx, clock):
    first = store.touch_principal(sys_ctx, "host-user-1", "Ada")
    assert (first.id, first.display_name) == ("host-user-1", "Ada")
    clock.advance(minutes=5)
    again = store.touch_principal(sys_ctx, "host-user-1", None)  # no name: keep the old one
    assert again.display_name == "Ada"
    assert again.first_seen_at == first.first_seen_at < again.last_seen_at
    renamed = store.touch_principal(sys_ctx, "host-user-1", "  Ada L.  ")
    assert renamed.display_name == "Ada L."
    assert store.get_principal(sys_ctx, "host-user-1") == renamed
    assert store.get_principal(sys_ctx, "nobody") is None


@pytest.mark.parametrize("bad", ["", "x" * 65, "system:retention", None, 7])
def test_principal_ids_are_checked(store, sys_ctx, bad):
    with pytest.raises(InvalidInput):
        store.touch_principal(sys_ctx, bad)
    assert store.get_principal(sys_ctx, bad) is None


def test_principals_need_a_system_context(store, tenants):
    a, _ = tenants
    with pytest.raises(AccessDenied):
        store.touch_principal(a, "u")
    with pytest.raises(AccessDenied):
        store.get_principal(a, "u")


def test_ensure_tenant_uses_the_host_id_once(store, sys_ctx):
    lab = store.ensure_tenant(sys_ctx, "psych-lab-7")
    assert (lab.id, lab.name) == ("psych-lab-7", "psych-lab-7")
    assert store.ensure_tenant(sys_ctx, "psych-lab-7", "Renamed") == lab  # unchanged
    assert store.find_tenant(sys_ctx, "psych-lab-7") == lab
    assert store.find_tenant(sys_ctx, "other") is None
    store.create_survey(TenantContext("psych-lab-7", "u1"), "S", {})  # usable as a tenant
    with pytest.raises(InvalidInput):
        store.ensure_tenant(sys_ctx, "x" * 37)
    creates = [
        e for e in store.list_audit(TenantContext(lab.id, "u1")) if e.action == "tenant.create"
    ]
    assert len(creates) == 1


def test_audit_rows_snapshot_the_display_name(store, sys_ctx):
    store.ensure_tenant(sys_ctx, "lab")
    store.touch_principal(sys_ctx, "u1", "Grace")
    ctx = TenantContext("lab", "u1")
    s1, _ = store.create_survey(ctx, "One", {})
    store.touch_principal(sys_ctx, "u1", "Grace H.")  # renamed by the host
    store.create_survey(ctx, "Two", {})
    names = [(e.action, e.actor_name) for e in store.list_audit(ctx) if e.actor == "u1"]
    assert names == [("survey.create", "Grace"), ("survey.create", "Grace H.")]
    system = [e for e in store.list_audit(ctx) if e.actor.startswith("system:")]
    assert system and all(e.actor_name is None for e in system)


def test_migration_0007_up_and_down(backend):
    """0006 -> 0007 drops the account tables (with rows in them) and adds principals;
    the downgrade recreates them empty. SQLite always; Postgres with `make test-postgres`."""
    engine = backend.engine
    migrate(engine, "0006_consent")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with engine.begin() as conn:
        conn.execute(insert(t.tenants).values(id="lab", name="Lab", created_at=now))
        conn.exec_driver_sql(
            "INSERT INTO users (id, tenant_id, email, password_hash, role, failed_logins, "
            "created_at) VALUES ('u1', 'lab', 'r@x.example', 'h', 'owner', 0, '2026-01-01')"
        )
        conn.exec_driver_sql("INSERT INTO user_mfa (id, recovery_code_hashes) VALUES ('u1', '[]')")
    migrate(engine)
    names = set(inspect(engine).get_table_names())
    assert {"users", "user_mfa", "auth_sessions"}.isdisjoint(names)
    assert "principals" in names
    assert "actor_name" in {c["name"] for c in inspect(engine).get_columns("audit_log")}

    downgrade(engine, "0006_consent")
    names = set(inspect(engine).get_table_names())
    assert {"users", "user_mfa", "auth_sessions"} <= names and "principals" not in names
    assert "actor_name" not in {c["name"] for c in inspect(engine).get_columns("audit_log")}
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM users").scalar_one() == 0
        assert conn.execute(select(t.tenants.c.id)).scalars().all() == ["lab"]  # kept
    migrate(engine)  # and up again
    assert "principals" in set(inspect(engine).get_table_names())


def test_system_context_is_required_for_ensure_tenant(store, tenants):
    a, _ = tenants
    with pytest.raises(AccessDenied):
        store.ensure_tenant(a, "lab-y")
    with pytest.raises(AccessDenied):
        store.find_tenant(SystemContext("nope"), "lab-y")
