from __future__ import annotations

import pytest
from osp_app.auth import InMemorySessionRepo, SessionConfig, SessionManager, SessionStage
from osp_app.auth.sessions import hash_token
from osp_app.auth.testing import FakeClock, FakeRandom


@pytest.fixture
def setup():
    repo = InMemorySessionRepo()
    clock = FakeClock()
    return SessionManager(repo, clock, FakeRandom()), repo, clock


def test_token_is_opaque_and_stored_hashed(setup):
    mgr, repo, _ = setup
    token = mgr.create("u1")
    assert len(token) >= 43  # 256 bits base64url
    assert repo.get(token) is None
    stored = repo.get(hash_token(token))
    assert stored is not None and stored.user_id == "u1"
    assert token not in repr(repo.list_for_user("u1"))


def test_tokens_unique(setup):
    mgr, _, _ = setup
    assert len({mgr.create("u1") for _ in range(50)}) == 50


def test_idle_timeout(setup):
    mgr, _, clock = setup
    token = mgr.create("u1")
    clock.advance(minutes=29)
    assert mgr.authenticate(token) is not None  # touches the idle timer
    clock.advance(minutes=29)
    assert mgr.authenticate(token) is not None
    clock.advance(minutes=30)
    assert mgr.authenticate(token) is None
    assert mgr.authenticate(token) is None  # deleted, stays dead


def test_absolute_expiry_despite_activity(setup):
    mgr, _, clock = setup
    token = mgr.create("u1")
    for _ in range(12 * 4 - 1):
        clock.advance(minutes=15)
        assert mgr.authenticate(token) is not None
    clock.advance(minutes=15)
    assert mgr.authenticate(token) is None


def test_rotate_invalidates_old_token_and_keeps_absolute_expiry(setup):
    mgr, repo, clock = setup
    old = mgr.create("u1")
    original = repo.get(hash_token(old))
    clock.advance(minutes=5)
    new = mgr.rotate(old)
    assert new and new != old
    assert mgr.authenticate(old) is None
    rotated = mgr.authenticate(new)
    assert rotated is not None and rotated.expires_at == original.expires_at


def test_rotate_dead_token(setup):
    mgr, _, _ = setup
    assert mgr.rotate("nope") is None


def test_logout_and_revoke_all(setup):
    mgr, _, _ = setup
    a, b, other = mgr.create("u1"), mgr.create("u1"), mgr.create("u2")
    mgr.revoke(a)
    assert mgr.authenticate(a) is None and mgr.authenticate(b) is not None
    mgr.revoke_all("u1")
    assert mgr.authenticate(b) is None
    assert mgr.authenticate(other) is not None


def test_pending_session_not_usable_as_full(setup):
    mgr, _, clock = setup
    pending = mgr.create("u1", SessionStage.MFA_PENDING)
    assert mgr.authenticate(pending) is None
    assert mgr.rotate(pending) is None
    assert mgr.peek_pending(pending) is not None
    clock.advance(minutes=6)
    assert mgr.peek_pending(pending) is None


def test_full_session_not_usable_as_pending(setup):
    mgr, _, _ = setup
    assert mgr.peek_pending(mgr.create("u1")) is None


@pytest.mark.parametrize("bad", [None, "", 42, b"bytes", "x" * 10_000, ["t"]])
def test_hostile_tokens(setup, bad):
    mgr, _, _ = setup
    assert mgr.authenticate(bad) is None
    assert mgr.rotate(bad) is None
    mgr.revoke(bad)


def test_config_injected():
    from datetime import timedelta

    clock = FakeClock()
    mgr = SessionManager(
        InMemorySessionRepo(), clock, FakeRandom(), SessionConfig(idle_timeout=timedelta(minutes=1))
    )
    token = mgr.create("u1")
    clock.advance(seconds=61)
    assert mgr.authenticate(token) is None
