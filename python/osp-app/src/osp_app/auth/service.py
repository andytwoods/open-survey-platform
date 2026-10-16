"""Login flow and account security operations.

    login(email, password)
        -> LoginOk(token)          no TOTP enrolled
        -> MfaRequired(challenge)  TOTP enrolled; finish with login_totp / login_recovery
        -> LoginFailed             anything else, always the same message

Failures never say whether the email exists, the password was wrong, the code
was wrong or the account is locked. Unknown emails still pay for one argon2
verify, so timing doesn't tell either. Repeated failures lock the account for
an exponentially growing period (backoff, not a permanent lock, so an attacker
can't lock a victim out for long). All time and randomness are injected.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

from . import totp
from .model import SessionStage, User, normalise_email
from .passwords import PasswordHasher, PasswordPolicy
from .permissions import Actor
from .ports import Clock, RandomSource
from .repos import MembershipRepo, SessionRepo, UserRepo
from .sessions import SessionConfig, SessionManager

GENERIC_FAILURE = "Sign-in failed. Check your details and try again."
ISSUER = "Open Survey Platform"


@dataclass(frozen=True)
class LoginOk:
    token: str
    user_id: str


@dataclass(frozen=True)
class MfaRequired:
    challenge: str  # short-lived MFA-pending session token


@dataclass(frozen=True)
class LoginFailed:
    message: str = GENERIC_FAILURE


type LoginResult = LoginOk | MfaRequired | LoginFailed


@dataclass(frozen=True)
class LockoutPolicy:
    free_attempts: int = 5  # failures before the first lock
    base_delay: timedelta = timedelta(seconds=30)
    max_delay: timedelta = timedelta(minutes=15)

    def delay_after(self, failures: int) -> timedelta | None:
        if failures < self.free_attempts:
            return None
        exponent = min(failures - self.free_attempts, 30)
        return min(self.base_delay * (2**exponent), self.max_delay)


@dataclass(frozen=True)
class TotpEnrolment:
    secret: str
    provisioning_uri: str


class AuthError(Exception):
    pass


class PasswordRejected(AuthError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class EmailTaken(AuthError):
    pass


class AuthService:
    def __init__(
        self,
        *,
        users: UserRepo,
        memberships: MembershipRepo,
        sessions: SessionRepo,
        clock: Clock,
        rng: RandomSource,
        hasher: PasswordHasher | None = None,
        policy: PasswordPolicy | None = None,
        lockout: LockoutPolicy | None = None,
        session_config: SessionConfig | None = None,
    ) -> None:
        self.users = users
        self.memberships = memberships
        self.clock = clock
        self.rng = rng
        self.hasher = hasher or PasswordHasher()
        self.policy = policy or PasswordPolicy()
        self.lockout = lockout or LockoutPolicy()
        self.sessions = SessionManager(sessions, clock, rng, session_config)
        self._dummy_hash: str | None = None

    # --- accounts -----------------------------------------------------------

    def create_user(self, email: str, password: str) -> User:
        email = normalise_email(email) if isinstance(email, str) else ""
        if "@" not in email:
            raise AuthError("A valid email address is required.")
        problems = self.policy.problems(password, email=email)
        if problems:
            raise PasswordRejected(problems)
        if self.users.get_by_email(email) is not None:
            raise EmailTaken("email already registered")
        user = User(
            id=self.rng.token_bytes(16).hex(),
            email=email,
            password_hash=self.hasher.hash(password),
            created_at=self.clock.now(),
        )
        self.users.add(user)
        return user

    def change_password(self, token: str, old_password: str, new_password: str) -> str:
        """Re-checks the old password, revokes every session of the user (all
        devices), and returns a new session token for this one."""
        user = self._user_for(token)
        if user is None or not self._password_ok(user, old_password):
            raise AuthError(GENERIC_FAILURE)
        problems = self.policy.problems(new_password, email=user.email)
        if problems:
            raise PasswordRejected(problems)
        self.users.update(replace(user, password_hash=self.hasher.hash(new_password)))
        self.sessions.revoke_all(user.id)
        return self.sessions.create(user.id)

    def actor(self, token: object) -> Actor | None:
        """Authenticate a request and build its Actor from live memberships."""
        session = self.sessions.authenticate(token)
        if session is None:
            return None
        return Actor.from_memberships(
            session.user_id, self.memberships.memberships_for_user(session.user_id)
        )

    def logout(self, token: object) -> None:
        self.sessions.revoke(token)

    # --- login ----------------------------------------------------------------

    def login(self, email: object, password: object) -> LoginResult:
        if not isinstance(email, str) or not isinstance(password, str):
            return LoginFailed()
        if len(password) > self.policy.max_length * 4:  # DoS guard before hashing
            return LoginFailed()
        user = self.users.get_by_email(email)
        if user is None:
            self._burn_hash(password)
            return LoginFailed()
        if self._locked(user):
            self._burn_hash(password)
            return LoginFailed()
        if not self._password_ok(user, password):
            self._record_failure(user)
            return LoginFailed()
        user = self._maybe_rehash(user, password)
        if user.totp_enrolled:
            # Password is right but the account isn't unlocked yet: the failure
            # counter is reset only once the second factor succeeds.
            return MfaRequired(self.sessions.create(user.id, SessionStage.MFA_PENDING))
        return self._succeed(user)

    def login_totp(self, challenge: object, code: object) -> LoginResult:
        return self._second_factor(challenge, code, recovery=False)

    def login_recovery(self, challenge: object, code: object) -> LoginResult:
        return self._second_factor(challenge, code, recovery=True)

    def _second_factor(self, challenge: object, code: object, *, recovery: bool) -> LoginResult:
        pending = self.sessions.peek_pending(challenge)
        if pending is None:
            return LoginFailed()
        user = self.users.get(pending.user_id)
        if user is None or not user.totp_enrolled or self._locked(user):
            return LoginFailed()
        if recovery:
            matched = totp.match_recovery_code(code, user.recovery_code_hashes)
            if matched is None:
                self._record_failure(user)
                return LoginFailed()
            user = replace(
                user,
                recovery_code_hashes=tuple(h for h in user.recovery_code_hashes if h != matched),
            )
        else:
            secret = user.totp_secret or ""
            step = totp.verify(secret, code, self.clock.now(), last_step=user.totp_last_step)
            if step is None:
                self._record_failure(user)
                return LoginFailed()
            user = replace(user, totp_last_step=step)
        self.users.update(user)
        self.sessions.revoke(challenge)  # one challenge, one login
        return self._succeed(user)

    # --- TOTP enrolment ---------------------------------------------------------

    def start_totp_enrolment(self, token: object) -> TotpEnrolment:
        user = self._user_for(token)
        if user is None:
            raise AuthError(GENERIC_FAILURE)
        if user.totp_enrolled:
            raise AuthError("TOTP is already enabled.")
        secret = totp.generate_secret(self.rng)
        self.users.update(replace(user, totp_pending_secret=secret))
        return TotpEnrolment(secret, totp.provisioning_uri(secret, user.email, ISSUER))

    def confirm_totp_enrolment(self, token: str, code: object) -> tuple[str, list[str]]:
        """Activate TOTP once the user proves their app works. Returns the
        rotated session token and the recovery codes (shown once, stored hashed)."""
        user = self._user_for(token)
        if user is None or user.totp_pending_secret is None:
            raise AuthError(GENERIC_FAILURE)
        step = totp.verify(user.totp_pending_secret, code, self.clock.now(), last_step=None)
        if step is None:
            raise AuthError("That code didn't match. Check your authenticator app's clock.")
        codes = totp.generate_recovery_codes(self.rng)
        self.users.update(
            replace(
                user,
                totp_secret=user.totp_pending_secret,
                totp_pending_secret=None,
                totp_last_step=step,
                recovery_code_hashes=tuple(totp.hash_recovery_code(c) for c in codes),
            )
        )
        # Privilege change: drop other sessions, rotate this one.
        self.sessions.revoke_all_except(user.id, token)
        new_token = self.sessions.rotate(token)
        assert new_token is not None
        return new_token, codes

    def regenerate_recovery_codes(self, token: str, password: str) -> list[str]:
        user = self._user_for(token)
        if user is None or not user.totp_enrolled or not self._password_ok(user, password):
            raise AuthError(GENERIC_FAILURE)
        codes = totp.generate_recovery_codes(self.rng)
        self.users.update(
            replace(user, recovery_code_hashes=tuple(totp.hash_recovery_code(c) for c in codes))
        )
        return codes

    # --- internals ----------------------------------------------------------------

    def _user_for(self, token: object) -> User | None:
        session = self.sessions.authenticate(token)
        return None if session is None else self.users.get(session.user_id)

    def _password_ok(self, user: User, password: object) -> bool:
        return isinstance(password, str) and self.hasher.verify(user.password_hash, password)

    def _burn_hash(self, password: str) -> None:
        if self._dummy_hash is None:
            self._dummy_hash = self.hasher.hash(self.rng.token_bytes(16).hex())
        self.hasher.verify(self._dummy_hash, password)

    def _maybe_rehash(self, user: User, password: str) -> User:
        if not self.hasher.needs_rehash(user.password_hash):
            return user
        user = replace(user, password_hash=self.hasher.hash(password))
        self.users.update(user)
        return user

    def _locked(self, user: User) -> bool:
        return user.locked_until is not None and self.clock.now() < user.locked_until

    def _record_failure(self, user: User) -> None:
        user = self.users.get(user.id) or user
        failures = user.failed_logins + 1
        delay = self.lockout.delay_after(failures)
        locked_until = None if delay is None else self.clock.now() + delay
        self.users.update(replace(user, failed_logins=failures, locked_until=locked_until))

    def _succeed(self, user: User) -> LoginOk:
        if user.failed_logins or user.locked_until:
            user = replace(user, failed_logins=0, locked_until=None)
            self.users.update(user)
        return LoginOk(self.sessions.create(user.id), user.id)
