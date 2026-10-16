from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from osp_app.auth import (
    GENERIC_FAILURE,
    AuthError,
    AuthService,
    EmailTaken,
    InMemoryMembershipRepo,
    InMemorySessionRepo,
    InMemoryUserRepo,
    LoginFailed,
    LoginOk,
    Membership,
    MfaRequired,
    PasswordHasher,
    PasswordRejected,
    Role,
    Tenant,
)
from osp_app.auth import totp as totp_mod
from osp_app.auth.testing import FakeClock

EMAIL = "ada@example.org"
PW = "plum tractor violet ninety"


def make_user(auth: AuthService):
    return auth.create_user(EMAIL, PW)


def login_ok(auth: AuthService) -> str:
    result = auth.login(EMAIL, PW)
    assert isinstance(result, LoginOk)
    return result.token


def enrol_totp(auth: AuthService, clock: FakeClock) -> tuple[str, str, list[str]]:
    token = login_ok(auth)
    enrolment = auth.start_totp_enrolment(token)
    token, codes = auth.confirm_totp_enrolment(token, totp_mod.totp(enrolment.secret, clock.now()))
    return token, enrolment.secret, codes


# --- accounts ---------------------------------------------------------------


def test_create_user_hashes_and_normalises_email(auth):
    user = auth.create_user("  Ada@Example.ORG ", PW)
    assert user.email == EMAIL
    assert user.password_hash.startswith("$argon2id$") and PW not in user.password_hash


def test_create_user_rejects_weak_password(auth):
    with pytest.raises(PasswordRejected) as exc:
        auth.create_user(EMAIL, "password")
    assert exc.value.problems


def test_create_user_duplicate_email(auth):
    make_user(auth)
    with pytest.raises(EmailTaken):
        auth.create_user(EMAIL.upper(), "another long passphrase here")


@pytest.mark.parametrize("bad", ["", "no-at-sign", None, 5])
def test_create_user_bad_email(auth, bad):
    with pytest.raises(AuthError):
        auth.create_user(bad, PW)


# --- password login -----------------------------------------------------------


def test_login_success_without_totp(auth):
    user = make_user(auth)
    token = login_ok(auth)
    actor = auth.actor(token)
    assert actor is not None and actor.user_id == user.id


def test_login_email_case_insensitive(auth):
    make_user(auth)
    assert isinstance(auth.login("ADA@example.org", PW), LoginOk)


def test_uniform_failures_no_enumeration(auth, clock):
    make_user(auth)
    wrong_password = auth.login(EMAIL, PW + "x")
    unknown_email = auth.login("nobody@example.org", PW)
    hostile = auth.login(None, None)  # type: ignore[arg-type]
    for _ in range(10):
        auth.login(EMAIL, "bad guess")
    locked_correct = auth.login(EMAIL, PW)  # locked: correct password still fails
    results = {wrong_password, unknown_email, hostile, locked_correct}
    assert results == {LoginFailed(GENERIC_FAILURE)}


def test_unknown_email_still_runs_a_hash(auth, monkeypatch):
    calls = []
    original = PasswordHasher.verify

    def spy(self, h, p):
        calls.append(h)
        return original(self, h, p)

    monkeypatch.setattr(PasswordHasher, "verify", spy)
    auth.login("nobody@example.org", PW)
    assert len(calls) == 1


def test_rehash_on_login_when_params_change(clock, rng):
    users = InMemoryUserRepo()
    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    common = dict(
        users=users,
        memberships=InMemoryMembershipRepo(),
        sessions=InMemorySessionRepo(),
        clock=clock,
        rng=rng,
    )
    user = AuthService(hasher=weak, **common).create_user(EMAIL, PW)
    stronger = PasswordHasher(time_cost=2, memory_cost=16, parallelism=1)
    svc = AuthService(hasher=stronger, **common)
    assert isinstance(svc.login(EMAIL, PW), LoginOk)
    new_hash = users.get(user.id).password_hash
    assert new_hash != user.password_hash and "t=2" in new_hash
    assert not stronger.needs_rehash(new_hash)
    assert isinstance(svc.login(EMAIL, PW), LoginOk)


# --- lockout and backoff --------------------------------------------------------


def test_lockout_after_five_failures_then_backoff(auth, clock):
    make_user(auth)
    for _ in range(4):
        assert isinstance(auth.login(EMAIL, "wrong guess"), LoginFailed)
    assert isinstance(auth.login(EMAIL, PW), LoginOk)  # 4 failures: not locked, resets
    for _ in range(5):
        auth.login(EMAIL, "wrong guess")
    assert isinstance(auth.login(EMAIL, PW), LoginFailed)  # locked 30 s
    clock.advance(seconds=29)
    assert isinstance(auth.login(EMAIL, PW), LoginFailed)
    clock.advance(seconds=2)
    auth.login(EMAIL, "wrong guess")  # 6th failure -> 60 s
    clock.advance(seconds=59)
    assert isinstance(auth.login(EMAIL, PW), LoginFailed)
    clock.advance(seconds=2)
    assert isinstance(auth.login(EMAIL, PW), LoginOk)
    user = auth.users.get_by_email(EMAIL)
    assert user.failed_logins == 0 and user.locked_until is None


def test_attempts_while_locked_do_not_extend_lock(auth, clock):
    make_user(auth)
    for _ in range(5):
        auth.login(EMAIL, "wrong guess")
    for _ in range(50):
        auth.login(EMAIL, "wrong guess")
    clock.advance(seconds=31)
    assert isinstance(auth.login(EMAIL, PW), LoginOk)


def test_backoff_is_capped(auth):
    assert auth.lockout.delay_after(4) is None
    assert auth.lockout.delay_after(5) == timedelta(seconds=30)
    assert auth.lockout.delay_after(6) == timedelta(seconds=60)
    assert auth.lockout.delay_after(1000) == timedelta(minutes=15)


# --- TOTP login -------------------------------------------------------------------


def test_totp_enrolment_requires_confirmation(auth, clock):
    make_user(auth)
    token = login_ok(auth)
    enrolment = auth.start_totp_enrolment(token)
    assert enrolment.provisioning_uri.startswith("otpauth://totp/")
    assert enrolment.secret in enrolment.provisioning_uri
    # not confirmed yet: login still single-factor
    assert isinstance(auth.login(EMAIL, PW), LoginOk)
    with pytest.raises(AuthError):
        auth.confirm_totp_enrolment(token, "000000")
    assert not auth.users.get_by_email(EMAIL).totp_enrolled


def test_totp_enrolment_rotates_session_and_drops_others(auth, clock):
    make_user(auth)
    other_device = login_ok(auth)
    old = login_ok(auth)
    enrolment = auth.start_totp_enrolment(old)
    new, codes = auth.confirm_totp_enrolment(old, totp_mod.totp(enrolment.secret, clock.now()))
    assert auth.actor(old) is None
    assert auth.actor(other_device) is None
    assert auth.actor(new) is not None
    assert len(codes) == 10
    stored = auth.users.get_by_email(EMAIL).recovery_code_hashes
    assert all(c not in stored for c in codes)


def test_login_with_totp(auth, clock):
    make_user(auth)
    _, secret, _ = enrol_totp(auth, clock)
    clock.advance(seconds=30)
    first = auth.login(EMAIL, PW)
    assert isinstance(first, MfaRequired)
    assert auth.actor(first.challenge) is None  # challenge is not a session
    result = auth.login_totp(first.challenge, totp_mod.totp(secret, clock.now()))
    assert isinstance(result, LoginOk)
    assert auth.actor(result.token) is not None
    # challenge is single-use
    assert isinstance(auth.login_totp(first.challenge, "123456"), LoginFailed)


def test_totp_code_replay_rejected(auth, clock):
    make_user(auth)
    _, secret, _ = enrol_totp(auth, clock)
    clock.advance(seconds=30)
    code = totp_mod.totp(secret, clock.now())
    assert isinstance(auth.login_totp(auth.login(EMAIL, PW).challenge, code), LoginOk)
    again = auth.login(EMAIL, PW)
    assert auth.login_totp(again.challenge, code) == LoginFailed(GENERIC_FAILURE)


def test_totp_code_from_enrolment_cannot_be_reused(auth, clock):
    make_user(auth)
    token = login_ok(auth)
    enrolment = auth.start_totp_enrolment(token)
    code = totp_mod.totp(enrolment.secret, clock.now())
    auth.confirm_totp_enrolment(token, code)
    assert isinstance(auth.login_totp(auth.login(EMAIL, PW).challenge, code), LoginFailed)


def test_wrong_totp_counts_towards_lockout(auth, clock):
    make_user(auth)
    _, secret, _ = enrol_totp(auth, clock)
    challenge = auth.login(EMAIL, PW).challenge
    for _ in range(5):
        assert isinstance(auth.login_totp(challenge, "000000"), LoginFailed)
    clock.advance(seconds=10)
    assert isinstance(auth.login_totp(challenge, totp_mod.totp(secret, clock.now())), LoginFailed)
    clock.advance(seconds=30)  # lock over
    challenge = auth.login(EMAIL, PW).challenge
    assert isinstance(auth.login_totp(challenge, totp_mod.totp(secret, clock.now())), LoginOk)


def test_mfa_challenge_expires(auth, clock):
    make_user(auth)
    _, secret, _ = enrol_totp(auth, clock)
    challenge = auth.login(EMAIL, PW).challenge
    clock.advance(minutes=6)
    assert isinstance(auth.login_totp(challenge, totp_mod.totp(secret, clock.now())), LoginFailed)


def test_recovery_code_single_use(auth, clock):
    make_user(auth)
    _, _, codes = enrol_totp(auth, clock)
    ok = auth.login_recovery(auth.login(EMAIL, PW).challenge, codes[0])
    assert isinstance(ok, LoginOk)
    again = auth.login_recovery(auth.login(EMAIL, PW).challenge, codes[0])
    assert again == LoginFailed(GENERIC_FAILURE)
    assert len(auth.users.get_by_email(EMAIL).recovery_code_hashes) == 9
    assert isinstance(auth.login_recovery(auth.login(EMAIL, PW).challenge, codes[1]), LoginOk)


def test_regenerate_recovery_codes(auth, clock):
    make_user(auth)
    token, _, old_codes = enrol_totp(auth, clock)
    new_codes = auth.regenerate_recovery_codes(token, PW)
    assert set(new_codes).isdisjoint(old_codes)
    challenge = auth.login(EMAIL, PW).challenge
    assert isinstance(auth.login_recovery(challenge, old_codes[0]), LoginFailed)
    assert isinstance(auth.login_recovery(challenge, new_codes[0]), LoginOk)
    with pytest.raises(AuthError):
        auth.regenerate_recovery_codes(token, "wrong password entirely")


@pytest.mark.parametrize("bad", [None, "", 123456, "x" * 5000, "AAAA-AAAA-AAAA-AAAA"])
def test_hostile_second_factor_inputs(auth, clock, bad):
    make_user(auth)
    enrol_totp(auth, clock)
    challenge = auth.login(EMAIL, PW).challenge
    assert isinstance(auth.login_totp(challenge, bad), LoginFailed)
    assert isinstance(auth.login_recovery(challenge, bad), LoginFailed)
    assert isinstance(auth.login_totp(bad, "123456"), LoginFailed)


# --- password change, logout, live roles ------------------------------------------


def test_change_password_revokes_all_sessions(auth):
    make_user(auth)
    a, b = login_ok(auth), login_ok(auth)
    new_pw = "another long passphrase here"
    fresh = auth.change_password(a, PW, new_pw)
    assert auth.actor(a) is None and auth.actor(b) is None
    assert auth.actor(fresh) is not None
    assert isinstance(auth.login(EMAIL, PW), LoginFailed)
    assert isinstance(auth.login(EMAIL, new_pw), LoginOk)


def test_change_password_needs_old_password(auth):
    make_user(auth)
    token = login_ok(auth)
    with pytest.raises(AuthError):
        auth.change_password(token, "not my password", "another long passphrase here")
    with pytest.raises(PasswordRejected):
        auth.change_password(token, PW, "short")


def test_logout(auth):
    make_user(auth)
    token = login_ok(auth)
    auth.logout(token)
    assert auth.actor(token) is None


def test_actor_reflects_live_role_changes(auth):
    user = make_user(auth)
    auth.memberships.add_tenant(Tenant("t1", "Lab"))
    auth.memberships.set_membership(Membership(user.id, "t1", Role.VIEWER))
    token = login_ok(auth)
    assert auth.actor(token).roles == {"t1": Role.VIEWER}
    auth.memberships.set_membership(Membership(user.id, "t1", Role.OWNER))
    assert auth.actor(token).roles == {"t1": Role.OWNER}
    auth.memberships.remove_membership(user.id, "t1")
    assert auth.actor(token).roles == {}


def test_login_survives_corrupt_stored_hash(auth):
    user = make_user(auth)
    auth.users.update(replace(user, password_hash="corrupt"))
    assert isinstance(auth.login(EMAIL, PW), LoginFailed)
