"""Theme library: CRUD, the lab default, and tenant isolation (runtime-design §6a)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from osp_store import AccessDenied, Conflict, InvalidInput, NotFound, Store, TenantContext
from osp_store import schema as t
from osp_store.store import is_constraint_violation
from sqlalchemy import insert
from sqlalchemy.exc import DBAPIError

BODY = {"colours": {"light": {"accent": "#2456c7"}}, "mode": "auto"}


@pytest.fixture
def theme_a(store: Store, tenants):
    a, _ = tenants
    return store.create_theme(a, "Lab blue", BODY)


def test_create_get_list_update_delete(store, tenants, clock):
    a, _ = tenants
    th = store.create_theme(a, "  Lab blue ", BODY)
    assert th.name == "Lab blue" and th.body == BODY and th.created_by == a.actor
    assert store.get_theme(a, th.id) == th
    store.create_theme(a, "Another", {"mode": "dark"})
    assert [x.name for x in store.list_themes(a)] == ["Another", "Lab blue"]

    clock.advance(minutes=5)
    up = store.update_theme(a, th.id, name="Lab navy", body={"mode": "light"})
    assert (up.name, up.body, up.created_at) == ("Lab navy", {"mode": "light"}, th.created_at)
    assert up.updated_at > th.updated_at
    assert store.update_theme(a, th.id) == up  # nothing to change

    store.delete_theme(a, th.id)
    with pytest.raises(NotFound):
        store.get_theme(a, th.id)
    actions = [e.action for e in store.list_audit(a)]
    assert {"theme.create", "theme.update", "theme.delete"} <= set(actions)


def test_names_are_unique_per_lab_not_globally(store, tenants, theme_a):
    a, b = tenants
    with pytest.raises(Conflict):
        store.create_theme(a, "Lab blue", BODY)
    assert store.create_theme(b, "Lab blue", BODY).tenant_id == b.tenant_id


@pytest.mark.parametrize(
    ("name", "body"),
    [("", BODY), ("x" * 201, BODY), (None, BODY), ("ok", ["not", "an", "object"]),
     ("ok", {"x": object()}), ("ok", {"big": "x" * 70_000}), ("ok", "{}")],
)  # fmt: skip
def test_bad_input_is_refused(store, tenants, name, body):
    a, _ = tenants
    with pytest.raises(InvalidInput):
        store.create_theme(a, name, body)
    assert store.list_themes(a) == []


def test_lab_default(store, tenants, theme_a):
    a, _ = tenants
    assert store.get_lab_default_theme(a) is None
    store.set_lab_default_theme(a, theme_a.id)
    assert store.get_lab_default_theme(a) == theme_a
    other = store.create_theme(a, "Warm", {"mode": "light"})
    store.set_lab_default_theme(a, other.id)  # replaces, one default per lab
    assert store.get_lab_default_theme(a).id == other.id
    store.set_lab_default_theme(a, None)
    assert store.get_lab_default_theme(a) is None
    actions = {e.action for e in store.list_audit(a)}
    assert {"theme.default.set", "theme.default.clear"} <= actions


def test_deleting_the_default_theme_clears_the_default(store, tenants, theme_a):
    a, _ = tenants
    store.set_lab_default_theme(a, theme_a.id)
    store.delete_theme(a, theme_a.id)
    assert store.get_lab_default_theme(a) is None


# --- Tenant isolation ---------------------------------------------------------------------

CROSS_TENANT: dict[str, Callable[[Store, TenantContext, str], object]] = {
    "get_theme": lambda s, b, tid: s.get_theme(b, tid),
    "update_theme_name": lambda s, b, tid: s.update_theme(b, tid, name="pwned"),
    "update_theme_body": lambda s, b, tid: s.update_theme(b, tid, body={"x": 1}),
    "update_theme_noop": lambda s, b, tid: s.update_theme(b, tid),
    "delete_theme": lambda s, b, tid: s.delete_theme(b, tid),
    "set_lab_default_theme": lambda s, b, tid: s.set_lab_default_theme(b, tid),
}


@pytest.mark.parametrize("name", sorted(CROSS_TENANT))
def test_cross_tenant_access_fails_closed_and_changes_nothing(store, tenants, theme_a, name):
    a, b = tenants
    store.set_lab_default_theme(a, theme_a.id)
    before = (store.list_themes(a), store.get_lab_default_theme(a), store.list_themes(b))
    with pytest.raises(NotFound):
        CROSS_TENANT[name](store, b, theme_a.id)
    assert (store.list_themes(a), store.get_lab_default_theme(a), store.list_themes(b)) == before
    assert store.get_lab_default_theme(b) is None


def test_lists_and_defaults_are_tenant_scoped(store, tenants, theme_a):
    a, b = tenants
    store.set_lab_default_theme(a, theme_a.id)
    assert store.list_themes(b) == []
    assert store.get_lab_default_theme(b) is None
    assert theme_a.id not in {e.target_id for e in store.list_audit(b)}


@pytest.mark.parametrize("bad_id", [None, 1, "", "x" * 37, ["id"]])
def test_hostile_theme_ids_are_not_found(store, tenants, bad_id):
    a, _ = tenants
    with pytest.raises(NotFound):
        store.get_theme(a, bad_id)
    if bad_id is not None:  # None means "clear the default"
        with pytest.raises(NotFound):
            store.set_lab_default_theme(a, bad_id)


@pytest.mark.parametrize("ctx", [None, "tenant-a", TenantContext("", "u")])
def test_missing_context_is_denied(store, tenants, theme_a, ctx):
    for call in (
        lambda: store.list_themes(ctx),
        lambda: store.create_theme(ctx, "x", {}),
        lambda: store.get_lab_default_theme(ctx),
        lambda: store.set_lab_default_theme(ctx, theme_a.id),
    ):
        with pytest.raises(AccessDenied):
            call()


def test_unknown_tenant_cannot_create_themes(store, tenants):
    ghost = TenantContext("00000000-0000-0000-0000-000000000000", "u")
    with pytest.raises(NotFound):
        store.create_theme(ghost, "x", {})


def test_db_refuses_a_default_pointing_at_another_tenants_theme(engine, tenants, theme_a):
    # Defence in depth: the composite (tenant_id, theme_id) foreign key.
    _, b = tenants
    with pytest.raises(DBAPIError) as exc, engine.begin() as conn:
        conn.execute(
            insert(t.lab_theme_defaults).values(
                tenant_id=b.tenant_id,
                theme_id=theme_a.id,
                set_by="evil",
                set_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    assert is_constraint_violation(exc.value)
