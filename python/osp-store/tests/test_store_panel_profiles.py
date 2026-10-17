"""Property panel profiles (task B21, migration 0010): one per lab, set/get/clear,
tenant isolation, size cap, audit. SQLite always; Postgres with `make test-postgres`."""

from __future__ import annotations

import pytest
from osp_store import AccessDenied, InvalidInput, NotFound, Store, TenantContext
from osp_store import schema as t
from sqlalchemy import inspect, select

BODY = {"hidden": ["*.help"], "custom": [{"key": "construct", "kind": "text", "label": "C"}]}


def test_set_get_replace_clear(store: Store, tenants, clock):
    a, b = tenants
    assert store.get_panel_profile(a) is None
    saved = store.set_panel_profile(a, BODY)
    assert (saved.tenant_id, saved.body, saved.updated_by) == (a.tenant_id, BODY, a.actor)
    assert store.get_panel_profile(a) == saved
    assert store.get_panel_profile(b) is None  # per lab

    clock.advance(minutes=5)
    again = store.set_panel_profile(a, {"hidden": []})
    assert again.body == {"hidden": []} and again.updated_at > saved.updated_at
    assert store.get_panel_profile(a) == again
    with store.engine.connect() as conn:
        rows = conn.execute(select(t.panel_profiles)).all()
    assert len(rows) == 1  # replaced, not duplicated

    assert store.clear_panel_profile(a) is True
    assert store.get_panel_profile(a) is None
    assert store.clear_panel_profile(a) is False
    actions = [e.action for e in store.list_audit(a)]
    assert actions.count("profile.set") == 2 and actions.count("profile.clear") == 1
    assert all("body" not in (e.detail or {}) for e in store.list_audit(a))


@pytest.mark.parametrize(
    "body",
    [["not", "an", "object"], {"x": object()}, {"big": "x" * 70_000}, "{}", None, 1],
)
def test_bad_body_is_refused(store, tenants, body):
    a, _ = tenants
    with pytest.raises(InvalidInput):
        store.set_panel_profile(a, body)
    assert store.get_panel_profile(a) is None


def test_unknown_tenant_and_bad_context(store, tenants, sys_ctx):
    with pytest.raises(NotFound):
        store.set_panel_profile(TenantContext("no-such-lab", "u"), BODY)
    with pytest.raises(AccessDenied):
        store.get_panel_profile(sys_ctx)  # type: ignore[arg-type]
    with pytest.raises(AccessDenied):
        store.set_panel_profile(None, BODY)  # type: ignore[arg-type]


def test_table_shape(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("panel_profiles")}
    assert cols == {"tenant_id", "body", "updated_by", "updated_at"}
    assert inspect(engine).get_pk_constraint("panel_profiles")["constrained_columns"] == [
        "tenant_id"
    ]
