"""Host identities admitted by the app, and the builder app commands (no HTTP)."""

from __future__ import annotations

import pytest
from osp_app import (
    COMMANDS,
    Forbidden,
    InvalidIdentity,
    NotFoundError,
    Unauthenticated,
    build_services,
    make_identity,
)
from osp_app.auth import Actor, Role
from osp_app.auth.testing import FakeClock
from osp_app.identity import dev_identity, format_roles, parse_roles
from osp_store import Keyring, Store, SystemContext, TenantContext, create_engine, migrate

KEY = "a" * 43 + "="
SYS = SystemContext("system:test")


def _store(tmp_path) -> Store:
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    migrate(engine)
    return Store(engine, Keyring({"k1": KEY}, active="k1"))


@pytest.fixture
def env(tmp_path):
    svc = build_services(_store(tmp_path), clock=FakeClock())
    actors = {
        "owner_a": svc.admit(make_identity("owner-a", {"lab-a": "owner"}, "Owner A")),
        "viewer_a": svc.admit(make_identity("viewer-a", {"lab-a": "viewer"})),
        "owner_b": svc.admit(make_identity("owner-b", {"lab-b": "owner"})),
    }
    return svc, actors


# -- identity checks -----------------------------------------------------------------


def test_make_identity_builds_a_checked_actor():
    ident = make_identity("u-1@host", {"lab-1": "editor", "lab-2": "viewer"}, "  Ada  ")
    assert ident.actor == Actor("u-1@host", {"lab-1": Role.EDITOR, "lab-2": Role.VIEWER})
    assert ident.display_name == "Ada"
    assert make_identity("u", {}, "   ").display_name is None


@pytest.mark.parametrize(
    ("user", "roles", "name"),
    [
        ("", {}, None),
        ("x" * 65, {}, None),
        ("system:retention", {}, None),  # ':' would forge an actor tag
        ("a b", {}, None),
        ("u", {"lab": "superuser"}, None),  # strict role enum
        ("u", {"lab": "Owner"}, None),
        ("u", {"x" * 37: "owner"}, None),
        ("u", {"a,b": "owner"}, None),
        ("u", {"": "owner"}, None),
        ("u", {f"l{i}": "viewer" for i in range(65)}, None),
        ("u", {}, "x" * 201),
        ("u", {}, "bell\x07"),
        (7, {}, None),
    ],
)
def test_bad_identities_are_refused_whole(user, roles, name):
    with pytest.raises(InvalidIdentity):
        make_identity(user, roles, name)


def test_roles_header_round_trip():
    roles = {"lab-b": Role.VIEWER, "lab-a": Role.OWNER}
    text = format_roles(roles)
    assert text == "lab-a:owner,lab-b:viewer"
    assert make_identity("u", parse_roles(text)).actor.roles == roles
    assert parse_roles("") == []
    with pytest.raises(InvalidIdentity):
        parse_roles("lab-a")
    with pytest.raises(InvalidIdentity):
        make_identity("u", parse_roles("lab-a:owner,lab-a:viewer"))  # listed twice


def test_dev_identity_owns_the_dev_lab():
    ident = dev_identity()
    assert ident.actor.roles == {"dev-lab": Role.OWNER}


# -- admit: principals and labs (D5, D6) -----------------------------------------------


def test_admit_records_the_principal_and_creates_labs(env):
    svc, actors = env
    assert actors["owner_a"].roles == {"lab-a": Role.OWNER}
    assert svc.store.find_tenant(SYS, "lab-a") is not None
    assert svc.display_name("owner-a") == "Owner A"
    assert svc.display_name("viewer-a") is None
    svc.admit(make_identity("owner-a", {"lab-a": "owner"}, "Owner A (renamed)"))
    assert svc.display_name("owner-a") == "Owner A (renamed)"  # a new name is written at once


def test_audit_rows_carry_the_display_name(env):
    svc, actors = env
    sid = svc.builder.run("survey.create", actors["owner_a"], title="S").survey.id
    entry = next(
        e
        for e in svc.store.list_audit(TenantContext("lab-a", "owner-a"))
        if e.target_id == sid and e.action == "survey.create"
    )
    assert (entry.actor, entry.actor_name) == ("owner-a", "Owner A")


def test_auto_create_off_drops_unknown_labs(tmp_path):
    svc = build_services(_store(tmp_path), auto_create_labs=False)
    actor = svc.admit(make_identity("u", {"made": "owner", "unknown": "owner"}))
    assert actor.roles == {}
    assert svc.store.find_tenant(SYS, "unknown") is None
    svc.create_lab("made", "Made by the CLI")
    actor = svc.admit(make_identity("u", {"made": "owner", "unknown": "owner"}))
    assert actor.roles == {"made": Role.OWNER}
    with pytest.raises(NotFoundError):
        # A role for a lab that doesn't exist opens nothing either.
        svc.builder.run("survey.get", Actor("u", {"unknown": "owner"}), survey_id="0" * 36)


# -- builder commands --------------------------------------------------------------------


@pytest.mark.parametrize("command_id", sorted(COMMANDS))
@pytest.mark.parametrize("who", [None, "not an actor", Actor("ghost", {})])
def test_every_command_fails_closed_for_non_members(env, command_id, who):
    svc, actors = env
    owner = actors["owner_a"]
    sid = svc.builder.run("survey.create", owner, title="S").survey.id
    params = {
        "survey.create": {"title": "x"},
        "survey.list": {},
        "survey.import_preview": {"filename": "x.json", "content": "{}"},
        "survey.import": {"filename": "x.json", "content": "{}"},
        "survey.apply_ops": {"survey_id": sid, "ops": [], "base_revision": 0},
        "survey.undo": {"survey_id": sid, "transaction_id": "t", "base_revision": 0},
        "survey.redo": {"survey_id": sid, "transaction_id": "u:t", "base_revision": 0},
        "theme.list": {},
        "theme.get": {"theme_id": "t"},
        "theme.create": {"name": "x", "theme": {}},
        "theme.update": {"theme_id": "t", "name": "x"},
        "theme.delete": {"theme_id": "t"},
        "theme.set_default": {"theme_id": None},
        "survey.delete_response": {"survey_id": sid, "response_id": "r1"},
        "survey.repro_package": {"survey_id": sid, "version": 1, "data": True},
        "survey.prereg_bundle": {"survey_id": sid, "version": 1},
        "survey.prereg_osf_upload": {
            "survey_id": sid,
            "version": 1,
            "token": "not-a-real-token-0123",
            "node": "ab3de",
        },
        "survey.results_layout_get": {"survey_id": sid, "layout_id": "l"},
        "survey.results_layout_create": {"survey_id": sid, "name": "x", "settings": {}},
        "survey.results_layout_update": {"survey_id": sid, "layout_id": "l", "name": "x"},
        "survey.results_layout_delete": {"survey_id": sid, "layout_id": "l"},
        "survey.results_layout_set_default": {"survey_id": sid, "layout_id": None},
        "profile.get": {"tenant_id": "lab-a"},
        "profile.set": {"profile": {}, "tenant_id": "lab-a"},
        "profile.clear": {"tenant_id": "lab-a"},
        "profile.schemas": {"tenant_id": "lab-a"},
        "bank.list": {"tenant_id": "lab-a"},
        "bank.library": {},
        "bank.get": {"item_id": "i", "tenant_id": "lab-a"},
        "bank.versions": {"item_id": "i", "tenant_id": "lab-a"},
        "bank.save": {"survey_id": sid, "target_id": "b1", "title": "x"},
        "bank.new_version": {"item_id": "i", "survey_id": sid, "target_id": "b1"},
        "bank.update": {"item_id": "i", "fields": {}, "tenant_id": "lab-a"},
        "bank.share": {"item_id": "i", "visibility": "host", "tenant_id": "lab-a"},
        "bank.delete": {"item_id": "i", "tenant_id": "lab-a"},
        "bank.export": {"item_id": "i", "tenant_id": "lab-a"},
        "bank.import": {"file": {}, "tenant_id": "lab-a"},
        "bank.copy": {"item_id": "i", "tenant_id": "lab-a"},
    }.get(command_id, {"survey_id": sid})
    if who is None or isinstance(who, str):
        with pytest.raises(Unauthenticated):
            svc.builder.run(command_id, who, **params)
        return
    if command_id == "survey.list":
        assert svc.builder.run(command_id, who) == []
        return
    with pytest.raises((Forbidden, NotFoundError)):
        svc.builder.run(command_id, who, **params)


def test_other_tenant_owner_sees_not_found(env):
    svc, actors = env
    owner_a, owner_b = actors["owner_a"], actors["owner_b"]
    sid = svc.builder.run("survey.create", owner_a, title="S").survey.id
    with pytest.raises(NotFoundError):
        svc.builder.run("survey.get", owner_b, survey_id=sid)
    with pytest.raises(NotFoundError):
        svc.builder.run("survey.delete", owner_b, survey_id=sid)
