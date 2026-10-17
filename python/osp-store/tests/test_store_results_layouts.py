"""Saved results layouts (plan V, V-D9, migration 0009): CRUD, the survey default,
tenant and survey isolation. SQLite always; Postgres with `make test-postgres`."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from osp_store import (
    AccessDenied,
    Conflict,
    InvalidInput,
    NotFound,
    Store,
    TenantContext,
    downgrade,
    migrate,
)
from osp_store import schema as t
from osp_store.store import is_constraint_violation
from sqlalchemy import insert, inspect, select
from sqlalchemy.exc import DBAPIError

SETTINGS = {
    "schemaVersion": "osp-results-layout/0.1",
    "query": {"denominator": "answered", "split": {"condition": "arm"}},
    "cards": [{"question": "q1", "chart": "donut"}, {"question": "q2", "hidden": True}],
}


@pytest.fixture
def surveys(store: Store, tenants):
    """Lab A: two surveys; lab B: one. Returns (survey_a1, survey_a2, survey_b)."""
    a, b = tenants
    a1, _ = store.create_survey(a, "A one", {})
    a2, _ = store.create_survey(a, "A two", {})
    b1, _ = store.create_survey(b, "B one", {})
    return a1.id, a2.id, b1.id


@pytest.fixture
def layout(store: Store, tenants, surveys):
    a, _ = tenants
    return store.create_results_layout(a, surveys[0], "Team view", SETTINGS)


def test_create_get_list_update_delete(store, tenants, surveys, clock):
    a, _ = tenants
    sid = surveys[0]
    lay = store.create_results_layout(a, sid, "  Team view ", SETTINGS)
    assert (lay.name, lay.settings, lay.survey_id) == ("Team view", SETTINGS, sid)
    assert lay.created_by == a.actor and lay.is_default is False
    assert store.get_results_layout(a, sid, lay.id) == lay
    store.create_results_layout(a, sid, "Another", {"cards": []})
    assert [x.name for x in store.list_results_layouts(a, sid)] == ["Another", "Team view"]
    assert store.list_results_layouts(a, surveys[1]) == []  # per survey

    clock.advance(minutes=5)
    up = store.update_results_layout(a, sid, lay.id, name="Lab view", settings={"cards": []})
    assert (up.name, up.settings, up.created_at) == ("Lab view", {"cards": []}, lay.created_at)
    assert up.updated_at > lay.updated_at
    assert store.update_results_layout(a, sid, lay.id) == up  # nothing to change

    store.delete_results_layout(a, sid, lay.id)
    with pytest.raises(NotFound):
        store.get_results_layout(a, sid, lay.id)
    actions = [e.action for e in store.list_audit(a)]
    assert {"results.layout.create", "results.layout.update", "results.layout.delete"} <= set(
        actions
    )
    detail = next(e.detail for e in store.list_audit(a) if e.action == "results.layout.update")
    assert detail == {"surveyId": sid, "fields": ["name", "settings"]}
    assert all("settings" not in (e.detail or {}) for e in store.list_audit(a))  # no bodies


def test_names_are_unique_per_survey_not_per_lab(store, tenants, surveys, layout):
    a, b = tenants
    with pytest.raises(Conflict):
        store.create_results_layout(a, surveys[0], "Team view", SETTINGS)
    with pytest.raises(Conflict):
        other = store.create_results_layout(a, surveys[0], "Other", SETTINGS)
        store.update_results_layout(a, surveys[0], other.id, name="Team view")
    in_a2 = store.create_results_layout(a, surveys[1], "Team view", SETTINGS)
    in_b = store.create_results_layout(b, surveys[2], "Team view", SETTINGS)
    assert (in_a2.survey_id, in_b.tenant_id) == (surveys[1], b.tenant_id)


@pytest.mark.parametrize(
    ("name", "settings"),
    [("", SETTINGS), ("x" * 201, SETTINGS), (None, SETTINGS), ("ok", ["not", "an", "object"]),
     ("ok", {"x": object()}), ("ok", {"big": "x" * 70_000}), ("ok", "{}"), ("ok", None)],
)  # fmt: skip
def test_bad_input_is_refused(store, tenants, surveys, name, settings):
    a, _ = tenants
    with pytest.raises(InvalidInput):
        store.create_results_layout(a, surveys[0], name, settings)
    assert store.list_results_layouts(a, surveys[0]) == []


def test_default_flag_is_bool(store, tenants, surveys):
    a, _ = tenants
    with pytest.raises(InvalidInput):
        store.create_results_layout(a, surveys[0], "x", SETTINGS, default="yes")  # type: ignore[arg-type]


def test_survey_default(store, tenants, surveys, layout):
    a, _ = tenants
    sid = surveys[0]
    assert store.get_default_results_layout_id(a, sid) is None
    store.set_default_results_layout(a, sid, layout.id)
    assert store.get_default_results_layout_id(a, sid) == layout.id
    assert store.get_results_layout(a, sid, layout.id).is_default is True
    assert [x.is_default for x in store.list_results_layouts(a, sid)] == [True]

    other = store.create_results_layout(a, sid, "Other", SETTINGS, default=True)  # replaces
    assert other.is_default is True
    assert store.get_default_results_layout_id(a, sid) == other.id
    assert store.get_results_layout(a, sid, layout.id).is_default is False
    assert store.get_default_results_layout_id(a, surveys[1]) is None  # per survey

    store.set_default_results_layout(a, sid, None)
    assert store.get_default_results_layout_id(a, sid) is None
    actions = {e.action for e in store.list_audit(a)}
    assert {"results.layout.default.set", "results.layout.default.clear"} <= actions


def test_deleting_the_default_layout_clears_the_default(store, tenants, surveys, layout):
    a, _ = tenants
    store.set_default_results_layout(a, surveys[0], layout.id)
    store.delete_results_layout(a, surveys[0], layout.id)
    assert store.get_default_results_layout_id(a, surveys[0]) is None


def test_deleting_the_survey_deletes_its_layouts(store, engine, tenants, surveys, layout):
    a, _ = tenants
    store.set_default_results_layout(a, surveys[0], layout.id)
    store.delete_unpublished_survey(a, surveys[0])
    with engine.connect() as conn:
        assert conn.execute(select(t.results_layouts.c.id)).all() == []
        assert conn.execute(select(t.results_layout_defaults.c.layout_id)).all() == []
    with pytest.raises(NotFound):
        store.list_results_layouts(a, surveys[0])


# --- Tenant and survey isolation ----------------------------------------------------------

CROSS: dict[str, Callable[[Store, TenantContext, str, str], object]] = {
    "get": lambda s, c, sid, lid: s.get_results_layout(c, sid, lid),
    "list": lambda s, c, sid, lid: s.list_results_layouts(c, sid),
    "default_id": lambda s, c, sid, lid: s.get_default_results_layout_id(c, sid),
    "create": lambda s, c, sid, lid: s.create_results_layout(c, sid, "pwned", {}),
    "update_name": lambda s, c, sid, lid: s.update_results_layout(c, sid, lid, name="pwned"),
    "update_settings": lambda s, c, sid, lid: s.update_results_layout(c, sid, lid, settings={}),
    "update_noop": lambda s, c, sid, lid: s.update_results_layout(c, sid, lid),
    "delete": lambda s, c, sid, lid: s.delete_results_layout(c, sid, lid),
    "set_default": lambda s, c, sid, lid: s.set_default_results_layout(c, sid, lid),
    "clear_default": lambda s, c, sid, lid: s.set_default_results_layout(c, sid, None),
}


def _snapshot(store, a, b, surveys):
    return (
        store.list_results_layouts(a, surveys[0]),
        store.get_default_results_layout_id(a, surveys[0]),
        store.list_results_layouts(a, surveys[1]),
        store.list_results_layouts(b, surveys[2]),
    )


@pytest.mark.parametrize("name", sorted(CROSS))
def test_other_tenant_fails_closed_and_changes_nothing(store, tenants, surveys, layout, name):
    a, b = tenants
    store.set_default_results_layout(a, surveys[0], layout.id)
    before = _snapshot(store, a, b, surveys)
    with pytest.raises(NotFound):
        CROSS[name](store, b, surveys[0], layout.id)
    assert _snapshot(store, a, b, surveys) == before
    assert layout.id not in {e.target_id for e in store.list_audit(b)}


PER_LAYOUT = [
    n for n in sorted(CROSS) if n not in ("list", "default_id", "create", "clear_default")
]


@pytest.mark.parametrize("name", PER_LAYOUT)
def test_a_layout_is_not_reachable_through_another_survey(store, tenants, surveys, layout, name):
    """Same lab, wrong survey in the path: NotFound, nothing changes."""
    a, b = tenants
    store.set_default_results_layout(a, surveys[0], layout.id)
    before = _snapshot(store, a, b, surveys)
    with pytest.raises(NotFound):
        CROSS[name](store, a, surveys[1], layout.id)
    assert _snapshot(store, a, b, surveys) == before


@pytest.mark.parametrize("bad_id", [None, 1, "", "x" * 37, ["id"]])
def test_hostile_ids_are_not_found(store, tenants, surveys, bad_id):
    a, _ = tenants
    with pytest.raises(NotFound):
        store.get_results_layout(a, surveys[0], bad_id)
    with pytest.raises(NotFound):
        store.get_results_layout(a, bad_id, "x")
    with pytest.raises(NotFound):
        store.list_results_layouts(a, bad_id)
    with pytest.raises(NotFound):
        store.create_results_layout(a, bad_id, "x", {})
    if bad_id is not None:  # None means "clear the default"
        with pytest.raises(NotFound):
            store.set_default_results_layout(a, surveys[0], bad_id)


@pytest.mark.parametrize("ctx", [None, "tenant-a", TenantContext("", "u")])
def test_missing_context_is_denied(store, tenants, surveys, layout, ctx):
    for call in (
        lambda: store.list_results_layouts(ctx, surveys[0]),
        lambda: store.create_results_layout(ctx, surveys[0], "x", {}),
        lambda: store.get_results_layout(ctx, surveys[0], layout.id),
        lambda: store.update_results_layout(ctx, surveys[0], layout.id, name="x"),
        lambda: store.delete_results_layout(ctx, surveys[0], layout.id),
        lambda: store.get_default_results_layout_id(ctx, surveys[0]),
        lambda: store.set_default_results_layout(ctx, surveys[0], layout.id),
    ):
        with pytest.raises(AccessDenied):
            call()


def test_db_refuses_a_default_pointing_at_another_surveys_layout(engine, tenants, surveys, layout):
    # Defence in depth: the composite (survey_id, layout_id) foreign key.
    a, _ = tenants
    with pytest.raises(DBAPIError) as exc, engine.begin() as conn:
        conn.execute(
            insert(t.results_layout_defaults).values(
                survey_id=surveys[1],
                tenant_id=a.tenant_id,
                layout_id=layout.id,
                set_by="evil",
                set_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    assert is_constraint_violation(exc.value)


def test_db_refuses_a_layout_under_another_tenants_survey(engine, tenants, surveys):
    # Defence in depth: the composite (tenant_id, survey_id) foreign key.
    _, b = tenants
    with pytest.raises(DBAPIError) as exc, engine.begin() as conn:
        conn.execute(
            insert(t.results_layouts).values(
                id="l" * 36,
                tenant_id=b.tenant_id,
                survey_id=surveys[0],
                name="x",
                settings={},
                created_by="evil",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                updated_by="evil",
                updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    assert is_constraint_violation(exc.value)


def test_migration_0009_up_and_down(backend):
    """0008 -> 0009 adds the two tables (empty); the downgrade drops them and keeps
    everything else. SQLite always; Postgres with `make test-postgres`."""
    engine = backend.engine
    migrate(engine, "0008_identity_nonces")
    names = set(inspect(engine).get_table_names())
    assert {"results_layouts", "results_layout_defaults"}.isdisjoint(names)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with engine.begin() as conn:
        conn.execute(insert(t.tenants).values(id="lab", name="Lab", created_at=now))
    migrate(engine)
    names = set(inspect(engine).get_table_names())
    assert {"results_layouts", "results_layout_defaults"} <= names
    columns = {c["name"] for c in inspect(engine).get_columns("results_layouts")}
    assert {"id", "tenant_id", "survey_id", "name", "settings", "updated_at"} <= columns
    with engine.connect() as conn:
        assert conn.execute(select(t.results_layouts.c.id)).all() == []

    downgrade(engine, "0008_identity_nonces")
    names = set(inspect(engine).get_table_names())
    assert {"results_layouts", "results_layout_defaults"}.isdisjoint(names)
    assert "identity_nonces" in names
    with engine.connect() as conn:
        assert conn.execute(select(t.tenants.c.id)).scalars().all() == ["lab"]  # kept
    migrate(engine)  # and up again
    assert "results_layouts" in set(inspect(engine).get_table_names())
