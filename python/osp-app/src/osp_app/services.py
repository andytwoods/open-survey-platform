"""Wiring: one object holding the auth service and the builder, backed by osp-store."""

from __future__ import annotations

from dataclasses import dataclass

from osp_store import AccountStore, Conflict, Store, SystemContext

from .auth import AuthService, PasswordHasher, Role
from .auth.model import normalise_email
from .auth.passwords import PasswordPolicy
from .auth.ports import Clock, RandomSource, SystemClock, SystemRandom
from .auth.service import EmailTaken, PasswordRejected
from .auth.sessions import SessionConfig
from .builder import Builder
from .store_repos import StoreMembershipRepo, StoreSessionRepo, StoreUserRepo


@dataclass
class AppServices:
    store: Store
    auth: AuthService
    builder: Builder

    def create_account(
        self, tenant_id: str, email: str, password: str, role: Role | str = Role.VIEWER
    ) -> str:
        """Provision a researcher (system/bootstrap use: CLI, tests). Returns the user id.

        Same password policy as everywhere else; the default role is the least one.
        """
        email = normalise_email(email) if isinstance(email, str) else ""
        problems = self.auth.policy.problems(password, email=email)
        if problems:
            raise PasswordRejected(problems)
        uid = self.auth.rng.token_bytes(16).hex()
        try:
            AccountStore(self.store).add_user(
                SystemContext("system:provision"),
                user_id=uid,
                tenant_id=tenant_id,
                email=email,
                role=str(role),
                password_hash=self.auth.hasher.hash(password),
                created_at=self.auth.clock.now(),
            )
        except Conflict as exc:
            raise EmailTaken("email already registered") from exc
        return uid


def build_services(
    store: Store,
    *,
    clock: Clock | None = None,
    rng: RandomSource | None = None,
    hasher: PasswordHasher | None = None,
    session_config: SessionConfig | None = None,
    password_policy: PasswordPolicy | None = None,
) -> AppServices:
    auth = AuthService(
        users=StoreUserRepo(store),
        memberships=StoreMembershipRepo(store),
        sessions=StoreSessionRepo(store),
        clock=clock or SystemClock(),
        rng=rng or SystemRandom(),
        hasher=hasher,
        session_config=session_config,
        policy=password_policy or PasswordPolicy.from_env(),
    )
    return AppServices(store=store, auth=auth, builder=Builder(store))
