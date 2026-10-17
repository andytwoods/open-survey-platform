"""Store-backed auth repos and the builder app commands (no HTTP)."""

from __future__ import annotations

import pytest
from osp_app import COMMANDS, Forbidden, NotFoundError, Unauthenticated, build_services
from osp_app.auth import Actor, LoginOk, MfaRequired, Role, totp
from osp_app.auth.testing import FakeClock, FakeRandom, cheap_hasher
from osp_store import Keyring, Store, SystemContext, create_engine, migrate

PASSWORD = "correct horse battery staple 42"
KEY = "a" * 43 + "="


@pytest.fixture
def env(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    migrate(engine)
    store = Store(engine, Keyring({"k1": KEY}, active="k1"))
    clock = FakeClock()
    svc = build_services(store, clock=clock, rng=FakeRandom("app"), hasher=cheap_hasher())
    sys = SystemContext("system:test")
    a = store.create_tenant(sys, "Lab A").id
    b = store.create_tenant(sys, "Lab B").id
    ids = {
        "owner_a": svc.create_account(a, "owner@a.example", PASSWORD, Role.OWNER),
        "viewer_a": svc.create_account(a, "viewer@a.example", PASSWORD),  # default: viewer
        "owner_b": svc.create_account(b, "owner@b.example", PASSWORD, Role.OWNER),
    }
    return svc, clock, ids


def _actor(svc, email):
    res = svc.auth.login(email, PASSWORD)
    assert isinstance(res, LoginOk)
    return svc.auth.actor(res.token), res.token


def test_store_backed_login_lockout_and_totp(env):
    svc, clock, ids = env
    for _ in range(5):
        assert not isinstance(svc.auth.login("owner@a.example", "nope nope nope nope"), LoginOk)
    assert not isinstance(svc.auth.login("owner@a.example", PASSWORD), LoginOk)  # locked
    clock.advance(minutes=1)
    actor, token = _actor(svc, "owner@a.example")
    assert actor.user_id == ids["owner_a"]

    enrol = svc.auth.start_totp_enrolment(token)
    new_token, codes = svc.auth.confirm_totp_enrolment(token, totp.totp(enrol.secret, clock.now()))
    assert len(codes) == 10 and svc.auth.actor(token) is None and svc.auth.actor(new_token)
    stored = svc.auth.users.get(ids["owner_a"])
    assert stored.totp_secret == enrol.secret and stored.totp_pending_secret is None

    res = svc.auth.login("owner@a.example", PASSWORD)
    assert isinstance(res, MfaRequired)
    clock.advance(seconds=30)
    assert isinstance(
        svc.auth.login_totp(res.challenge, totp.totp(enrol.secret, clock.now())), LoginOk
    )


def test_store_backed_sessions_expire_and_revoke(env):
    svc, clock, _ = env
    _, token = _actor(svc, "owner@a.example")
    clock.advance(minutes=31)  # idle timeout
    assert svc.auth.actor(token) is None
    _, token = _actor(svc, "owner@a.example")
    svc.auth.logout(token)
    assert svc.auth.actor(token) is None


def test_memberships_come_from_the_user_row(env):
    svc, _, ids = env
    actor, _ = _actor(svc, "viewer@a.example")
    assert list(actor.roles.values()) == ["viewer"]
    assert svc.auth.memberships.memberships_for_user("missing") == []


@pytest.mark.parametrize("command_id", sorted(COMMANDS))
@pytest.mark.parametrize("who", [None, "not an actor", Actor("ghost", {})])
def test_every_command_fails_closed_for_non_members(env, command_id, who):
    svc, _, _ = env
    owner, _ = _actor(svc, "owner@a.example")
    sid = svc.builder.run("survey.create", owner, title="S").survey.id
    params = {
        "survey.create": {"title": "x"},
        "survey.list": {},
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
    svc, _, _ = env
    owner_a, _ = _actor(svc, "owner@a.example")
    owner_b, _ = _actor(svc, "owner@b.example")
    sid = svc.builder.run("survey.create", owner_a, title="S").survey.id
    with pytest.raises(NotFoundError):
        svc.builder.run("survey.get", owner_b, survey_id=sid)
    with pytest.raises(NotFoundError):
        svc.builder.run("survey.delete", owner_b, survey_id=sid)
