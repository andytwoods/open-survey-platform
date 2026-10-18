"""Question bank store (task QB4, migration 0012): save, versions, metadata edits, host
sharing, soft delete, search and filters, tenant isolation, audit, migration up and down.
SQLite always; Postgres with `make test-postgres`."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from osp_store import (
    AccessDenied,
    BankItemMeta,
    BankQuery,
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


def doc(title: str = "PHQ-2", **extra) -> dict:
    return {
        "bankVersion": "osp-bank-item/0.1",
        "kind": "block",
        "title": title,
        "abbreviation": "PHQ-2",
        "tags": ["depression", "screener"],
        "languages": ["en"],
        "licence": {"class": "public-domain"},
        "fragment": {"block": {"id": "b", "pages": []}},
        **extra,
    }


def meta(title: str = "PHQ-2", **extra) -> BankItemMeta:
    base = {
        "title": title,
        "kind": "block",
        "licence_class": "public-domain",
        "search_text": f"{title.lower()} phq-2 depression screener little interest",
        "abbreviation": "PHQ-2",
        "tags": ["depression", "screener"],
        "languages": ["en"],
    }
    return BankItemMeta(**{**base, **extra})


@pytest.fixture
def item_a(store: Store, tenants):
    a, _ = tenants
    item, _version = store.create_bank_item(a, meta(), doc(), "sha256:" + "0" * 64)
    return item


def test_save_get_versions(store: Store, tenants, clock):
    a, _ = tenants
    item, v1 = store.create_bank_item(a, meta(), doc(), "sha256:" + "0" * 64)
    assert (item.title, item.kind, item.visibility, item.current_version) == (
        "PHQ-2", "block", "lab", 1,
    )  # fmt: skip
    assert item.tags == ["depression", "screener"] and item.languages == ["en"]
    assert item.deleted_at is None and item.created_by == a.actor
    assert v1.body["id"] == item.id and v1.body["version"] == 1  # store-owned keys
    assert v1.body["title"] == "PHQ-2" and v1.checksum == "sha256:" + "0" * 64
    assert store.get_bank_item(a, item.id) == item
    assert store.get_bank_version(a, item.id) == v1
    assert store.get_bank_version(a, item.id, 1) == v1

    clock.advance(minutes=5)
    item2, v2 = store.add_bank_version(
        a, item.id, meta("PHQ-2 (revised)"), doc("PHQ-2 (revised)"), "sha256:" + "1" * 64
    )
    assert (item2.current_version, item2.title) == (2, "PHQ-2 (revised)")
    assert item2.created_at == item.created_at and item2.updated_at > item.updated_at
    assert v2.body["version"] == 2 and v2.body["id"] == item.id
    assert store.get_bank_version(a, item.id).version == 2
    assert store.get_bank_version(a, item.id, 1).body["title"] == "PHQ-2"  # immutable
    assert [v.version for v in store.list_bank_versions(a, item.id)] == [1, 2]
    with pytest.raises(NotFound):
        store.get_bank_version(a, item.id, 3)
    with pytest.raises(NotFound):
        store.get_bank_version(a, item.id, 0)
    actions = [e.action for e in store.list_audit(a)]
    assert actions.count("bank.save") == 2
    details = [e.detail for e in store.list_audit(a) if e.action == "bank.save"]
    assert details == [
        {"version": 1, "kind": "block", "licence_class": "public-domain"},
        {"version": 2, "kind": "block", "licence_class": "public-domain"},
    ]
    assert all("title" not in (e.detail or {}) for e in store.list_audit(a))  # no item text


def test_kind_cannot_change_across_versions(store, tenants, item_a):
    a, _ = tenants
    with pytest.raises(InvalidInput):
        store.add_bank_version(a, item_a.id, meta(kind="page"), doc(), "sha256:" + "2" * 64)
    assert store.get_bank_item(a, item_a.id).current_version == 1


def test_metadata_edit_rewrites_the_current_version_only(store, tenants, item_a, clock):
    a, _ = tenants
    store.add_bank_version(a, item_a.id, meta(), doc(), "sha256:" + "1" * 64)
    clock.advance(minutes=1)
    item, version = store.update_bank_item(
        a,
        item_a.id,
        meta("Depression screener", tags=["mood"]),
        {"title": "Depression screener", "tags": ["mood"], "description": "Two items."},
    )
    assert (item.title, item.tags, item.current_version) == ("Depression screener", ["mood"], 2)
    assert version.version == 2 and version.body["title"] == "Depression screener"
    assert version.body["description"] == "Two items." and version.body["tags"] == ["mood"]
    assert version.body["fragment"] == doc()["fragment"]  # untouched
    assert store.get_bank_version(a, item_a.id, 1).body["title"] == "PHQ-2"
    # A None value removes the key.
    _, v = store.update_bank_item(a, item_a.id, meta("Depression screener"), {"description": None})
    assert "description" not in v.body
    with pytest.raises(InvalidInput):
        store.update_bank_item(a, item_a.id, meta(), {"fragment": {}})
    with pytest.raises(InvalidInput):
        store.update_bank_item(a, item_a.id, meta(kind="page"), {"title": "x"})
    audit = [e for e in store.list_audit(a) if e.action == "bank.update"]
    assert audit[0].detail["fields"] == ["description", "tags", "title"]


def test_share_and_soft_delete(store, tenants, item_a):
    a, b = tenants
    assert store.list_bank_items(b) == []
    with pytest.raises(NotFound):
        store.get_bank_item(b, item_a.id)
    shared = store.set_bank_visibility(a, item_a.id, "host")
    assert shared.visibility == "host"
    assert store.set_bank_visibility(a, item_a.id, "host") == shared  # idempotent, one audit
    assert [e.action for e in store.list_audit(a)].count("bank.share") == 1
    assert [i.id for i in store.list_bank_items(b)] == [item_a.id]
    assert store.get_bank_item(b, item_a.id).visibility == "host"
    assert store.get_bank_version(b, item_a.id).body["title"] == "PHQ-2"
    assert [v.version for v in store.list_bank_versions(b, item_a.id)] == [1]
    # Host sharing switched off on this host: nothing from other labs.
    assert store.list_bank_items(b, include_host=False) == []
    assert store.list_bank_items(b, BankQuery(source="host"), include_host=False) == []
    with pytest.raises(NotFound):
        store.get_bank_item(b, item_a.id, include_host=False)
    with pytest.raises(NotFound):
        store.get_bank_version(b, item_a.id, include_host=False)
    assert store.list_bank_items(a, include_host=False) == [shared]  # own items always
    # Only the owning lab changes it.
    for call in (
        lambda: store.set_bank_visibility(b, item_a.id, "lab"),
        lambda: store.delete_bank_item(b, item_a.id),
        lambda: store.update_bank_item(b, item_a.id, meta(), {"title": "Mine"}),
        lambda: store.add_bank_version(b, item_a.id, meta(), doc(), "sha256:" + "3" * 64),
    ):
        with pytest.raises(NotFound):
            call()
    assert store.get_bank_item(a, item_a.id) == shared
    with pytest.raises(InvalidInput):
        store.set_bank_visibility(a, item_a.id, "public")

    gone = store.delete_bank_item(a, item_a.id)
    assert gone.deleted_at is not None
    assert store.list_bank_items(a) == []  # lists stop showing it
    assert store.get_bank_item(a, item_a.id) == gone  # the owner still reads it
    assert store.get_bank_version(a, item_a.id).version == 1
    with pytest.raises(NotFound):  # other labs don't
        store.get_bank_item(b, item_a.id)
    assert store.list_bank_items(b) == []
    for call in (
        lambda: store.set_bank_visibility(a, item_a.id, "lab"),
        lambda: store.delete_bank_item(a, item_a.id),
        lambda: store.update_bank_item(a, item_a.id, meta(), {"title": "x"}),
        lambda: store.add_bank_version(a, item_a.id, meta(), doc(), "sha256:" + "3" * 64),
    ):
        with pytest.raises(Conflict):
            call()
    assert [e.action for e in store.list_audit(a)].count("bank.delete") == 1


def test_search_and_filters(store, tenants):
    a, b = tenants
    phq = store.create_bank_item(a, meta(), doc(), "sha256:" + "0" * 64)[0]
    gad = store.create_bank_item(
        a,
        meta(
            "GAD-7",
            abbreviation="GAD-7",
            tags=["anxiety", "screener"],
            languages=["en", "es"],
            search_text="gad-7 anxiety screener feeling nervous 100% sure",
        ),
        doc("GAD-7"),
        "sha256:" + "1" * 64,
    )[0]
    age = store.create_bank_item(
        a,
        meta(
            "Age",
            kind="question",
            abbreviation=None,
            tags=[],
            licence_class="cc0",
            search_text="age how old are you",
        ),
        doc("Age", kind="question"),
        "sha256:" + "2" * 64,
    )[0]
    other = store.create_bank_item(b, meta("B's PHQ-2"), doc("B's PHQ-2"), "sha256:" + "4" * 64)[0]
    store.set_bank_visibility(b, other.id, "host")
    hidden = store.create_bank_item(b, meta("B private"), doc(), "sha256:" + "5" * 64)[0]

    ids = lambda items: [i.id for i in items]  # noqa: E731
    assert ids(store.list_bank_items(a)) == [age.id, other.id, gad.id, phq.id]  # by title
    assert ids(store.list_bank_items(a, BankQuery(source="lab"))) == [age.id, gad.id, phq.id]
    assert ids(store.list_bank_items(a, BankQuery(source="host"))) == [other.id]
    assert ids(store.list_bank_items(b, BankQuery(source="lab"))) == [hidden.id, other.id]
    assert ids(store.list_bank_items(a, BankQuery(q="screener"))) == [other.id, gad.id, phq.id]
    assert ids(store.list_bank_items(a, BankQuery(q="SCREENER anxiety"))) == [gad.id]
    assert ids(store.list_bank_items(a, BankQuery(q="phq"))) == [other.id, phq.id]
    assert ids(store.list_bank_items(a, BankQuery(q="100%"))) == [gad.id]  # escaped
    assert ids(store.list_bank_items(a, BankQuery(q="%"))) == [gad.id]  # a literal %
    assert ids(store.list_bank_items(a, BankQuery(q="_"))) == []
    assert ids(store.list_bank_items(a, BankQuery(q="   "))) == [age.id, other.id, gad.id, phq.id]
    assert ids(store.list_bank_items(a, BankQuery(kind="question"))) == [age.id]
    assert ids(store.list_bank_items(a, BankQuery(licence_class="cc0"))) == [age.id]
    assert ids(store.list_bank_items(a, BankQuery(language="es"))) == [gad.id]
    assert ids(store.list_bank_items(a, BankQuery(tags=["screener"]))) == [other.id, gad.id, phq.id]
    assert ids(store.list_bank_items(a, BankQuery(tags=["screener", "anxiety"]))) == [gad.id]
    assert ids(store.list_bank_items(a, BankQuery(q="phq", source="lab", kind="block"))) == [phq.id]
    for bad in (
        BankQuery(source="public"),
        BankQuery(kind="matrix"),
        BankQuery(q="x" * 201),
        BankQuery(tags="screener"),
        BankQuery(licence_class=""),
    ):
        with pytest.raises(InvalidInput):
            store.list_bank_items(a, bad)


@pytest.mark.parametrize(
    ("m", "body", "checksum"),
    [
        (meta(""), doc(), "sha256:" + "0" * 64),
        (meta("x" * 201), doc(), "sha256:" + "0" * 64),
        (meta(kind="matrix"), doc(), "sha256:" + "0" * 64),
        (meta(abbreviation="x" * 41), doc(), "sha256:" + "0" * 64),
        (meta(tags="screener"), doc(), "sha256:" + "0" * 64),
        (meta(tags=[1]), doc(), "sha256:" + "0" * 64),
        (meta(languages=["x" * 41]), doc(), "sha256:" + "0" * 64),
        (meta(licence_class=""), doc(), "sha256:" + "0" * 64),
        (meta(search_text="x" * 70_000), doc(), "sha256:" + "0" * 64),
        (meta(search_text=None), doc(), "sha256:" + "0" * 64),
        (meta(), ["not", "an", "object"], "sha256:" + "0" * 64),
        (meta(), {"x": object()}, "sha256:" + "0" * 64),
        (meta(), {"big": "x" * 300_000}, "sha256:" + "0" * 64),
        (meta(), "{}", "sha256:" + "0" * 64),
        (meta(), doc(), ""),
        (meta(), doc(), None),
        ({"title": "x"}, doc(), "sha256:" + "0" * 64),
    ],
)
def test_bad_input_is_refused(store, tenants, m, body, checksum):
    a, _ = tenants
    with pytest.raises(InvalidInput):
        store.create_bank_item(a, m, body, checksum)
    assert store.list_bank_items(a) == []


def test_imported_items_are_audited_as_imports(store, tenants):
    a, _ = tenants
    item, _ = store.create_bank_item(a, meta(), doc(), "sha256:" + "0" * 64, imported=True)
    entry = next(e for e in store.list_audit(a) if e.target_id == item.id)
    assert entry.action == "bank.import" and entry.detail["version"] == 1


# --- Tenant isolation ---------------------------------------------------------------------

CROSS_TENANT: dict[str, Callable[[Store, TenantContext, str], object]] = {
    "get_bank_item": lambda s, b, i: s.get_bank_item(b, i),
    "get_bank_version": lambda s, b, i: s.get_bank_version(b, i),
    "list_bank_versions": lambda s, b, i: s.list_bank_versions(b, i),
    "add_bank_version": lambda s, b, i: s.add_bank_version(b, i, meta(), doc(), "sha256:" + "1" * 64),  # noqa: E501
    "update_bank_item": lambda s, b, i: s.update_bank_item(b, i, meta(), {"title": "pwned"}),
    "set_bank_visibility": lambda s, b, i: s.set_bank_visibility(b, i, "host"),
    "delete_bank_item": lambda s, b, i: s.delete_bank_item(b, i),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(CROSS_TENANT))
def test_cross_tenant_access_fails_closed_and_changes_nothing(store, tenants, item_a, name):
    a, b = tenants
    before = (store.list_bank_items(a), store.get_bank_version(a, item_a.id))
    with pytest.raises(NotFound):
        CROSS_TENANT[name](store, b, item_a.id)
    assert (store.list_bank_items(a), store.get_bank_version(a, item_a.id)) == before
    assert store.list_bank_items(b) == []
    assert item_a.id not in {e.target_id for e in store.list_audit(b)}


@pytest.mark.parametrize("bad_id", [None, 1, "", "x" * 37, ["id"]])
def test_hostile_ids_are_not_found(store, tenants, bad_id):
    a, _ = tenants
    for call in (
        lambda: store.get_bank_item(a, bad_id),
        lambda: store.get_bank_version(a, bad_id),
        lambda: store.delete_bank_item(a, bad_id),
    ):
        with pytest.raises(NotFound):
            call()


@pytest.mark.parametrize("ctx", [None, "tenant-a", TenantContext("", "u")])
def test_missing_context_is_denied(store, tenants, item_a, ctx):
    for call in (
        lambda: store.list_bank_items(ctx),
        lambda: store.create_bank_item(ctx, meta(), doc(), "sha256:" + "0" * 64),
        lambda: store.get_bank_item(ctx, item_a.id),
        lambda: store.set_bank_visibility(ctx, item_a.id, "host"),
    ):
        with pytest.raises(AccessDenied):
            call()


def test_unknown_tenant_cannot_save(store, tenants):
    ghost = TenantContext("00000000-0000-0000-0000-000000000000", "u")
    with pytest.raises(NotFound):
        store.create_bank_item(ghost, meta(), doc(), "sha256:" + "0" * 64)


def test_db_refuses_a_version_pointing_at_another_tenants_item(engine, tenants, item_a):
    # Defence in depth: the composite (tenant_id, item_id) foreign key.
    _, b = tenants
    with pytest.raises(DBAPIError) as exc, engine.begin() as conn:
        conn.execute(
            insert(t.bank_item_versions).values(
                item_id=item_a.id,
                version=9,
                tenant_id=b.tenant_id,
                body={},
                checksum="x",
                created_by="evil",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    assert is_constraint_violation(exc.value)


def test_migration_0012_up_and_down(backend):
    """0011 -> 0012 adds the two tables (empty); the downgrade drops them and keeps
    everything else. SQLite always; Postgres with `make test-postgres`."""
    engine = backend.engine
    migrate(engine, "0011_response_outcome")
    names = set(inspect(engine).get_table_names())
    assert {"bank_items", "bank_item_versions"}.isdisjoint(names)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with engine.begin() as conn:
        conn.execute(insert(t.tenants).values(id="lab", name="Lab", created_at=now))
    migrate(engine)
    names = set(inspect(engine).get_table_names())
    assert {"bank_items", "bank_item_versions"} <= names
    columns = {c["name"] for c in inspect(engine).get_columns("bank_items")}
    assert {"id", "tenant_id", "visibility", "licence_class", "search_text"} <= columns
    assert "deleted_at" in columns
    assert inspect(engine).get_pk_constraint("bank_item_versions")["constrained_columns"] == [
        "item_id",
        "version",
    ]
    with engine.connect() as conn:
        assert conn.execute(select(t.bank_items.c.id)).all() == []

    downgrade(engine, "0011_response_outcome")
    names = set(inspect(engine).get_table_names())
    assert {"bank_items", "bank_item_versions"}.isdisjoint(names)
    assert "responses" in names
    with engine.connect() as conn:
        assert conn.execute(select(t.tenants.c.id)).scalars().all() == ["lab"]  # kept
    migrate(engine)  # and up again
    assert "bank_items" in set(inspect(engine).get_table_names())
