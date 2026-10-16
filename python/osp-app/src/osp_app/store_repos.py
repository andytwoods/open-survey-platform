"""Store-backed implementations of the auth repository Protocols (C10a's ``repos.py``).

Researchers belong to exactly one tenant in the MVP store (``users.tenant_id`` +
``users.role``), so a membership is derived from the user row. Sign-in runs before a
tenant is known, so the account methods use a ``SystemContext``.
"""

from __future__ import annotations

from dataclasses import replace

from osp_store import (
    AccountStore,
    AccountUser,
    AuthSessionRow,
    Conflict,
    NotFound,
    Store,
    SystemContext,
    TenantContext,
)

from .auth.model import Membership, Session, SessionStage, Tenant, User
from .auth.repos import DuplicateError

SYSTEM = SystemContext("system:auth")


def _to_user(a: AccountUser) -> User:
    return User(
        id=a.id,
        email=a.email,
        password_hash=a.password_hash or "",  # no hash: verification always fails
        created_at=a.created_at,
        totp_secret=a.totp_secret,
        totp_pending_secret=a.totp_pending_secret,
        totp_last_step=a.totp_last_step,
        recovery_code_hashes=a.recovery_code_hashes,
        failed_logins=a.failed_logins,
        locked_until=a.locked_until,
    )


class StoreUserRepo:
    """``UserRepo`` over osp-store. New users go into ``tenant_id`` with ``role``
    (both fixed at construction); the safest default role is ``viewer``."""

    def __init__(self, store: Store, *, tenant_id: str | None = None, role: str = "viewer") -> None:
        self._accounts = AccountStore(store)
        self._tenant_id = tenant_id
        self._role = role

    def get(self, user_id: str) -> User | None:
        a = self._accounts.get_user(SYSTEM, user_id)
        return None if a is None else _to_user(a)

    def get_by_email(self, email: str) -> User | None:
        a = self._accounts.get_user_by_email(SYSTEM, email)
        return None if a is None else _to_user(a)

    def add(self, user: User) -> None:
        if self._tenant_id is None:
            raise DuplicateError("this repo has no tenant for new users")
        try:
            self._accounts.add_user(
                SYSTEM,
                user_id=user.id,
                tenant_id=self._tenant_id,
                email=user.email,
                role=self._role,
                password_hash=user.password_hash,
                created_at=user.created_at,
            )
        except Conflict as exc:
            raise DuplicateError("user exists") from exc

    def update(self, user: User) -> None:
        current = self._accounts.get_user(SYSTEM, user.id)
        if current is None:
            raise KeyError(user.id)
        self._accounts.save_user(
            SYSTEM,
            replace(
                current,
                password_hash=user.password_hash,
                totp_secret=user.totp_secret,
                totp_pending_secret=user.totp_pending_secret,
                totp_last_step=user.totp_last_step,
                recovery_code_hashes=tuple(user.recovery_code_hashes),
                failed_logins=user.failed_logins,
                locked_until=user.locked_until,
            ),
        )


class StoreSessionRepo:
    """``SessionRepo`` over osp-store's ``auth_sessions`` table."""

    def __init__(self, store: Store) -> None:
        self._accounts = AccountStore(store)

    @staticmethod
    def _row(s: Session) -> AuthSessionRow:
        return AuthSessionRow(
            s.id, s.user_id, str(s.stage), s.created_at, s.last_seen_at, s.expires_at
        )

    @staticmethod
    def _session(r: AuthSessionRow) -> Session | None:
        try:
            stage = SessionStage(r.stage)
        except ValueError:
            return None  # unknown stage: fail closed
        return Session(r.id, r.user_id, stage, r.created_at, r.last_seen_at, r.expires_at)

    def add(self, session: Session) -> None:
        try:
            self._accounts.add_session(SYSTEM, self._row(session))
        except Conflict as exc:
            raise DuplicateError("session exists") from exc

    def get(self, session_id: str) -> Session | None:
        r = self._accounts.get_session(SYSTEM, session_id)
        return None if r is None else self._session(r)

    def update(self, session: Session) -> None:
        self._accounts.update_session(SYSTEM, self._row(session))

    def delete(self, session_id: str) -> None:
        self._accounts.delete_session(SYSTEM, session_id)

    def delete_for_user(self, user_id: str) -> None:
        self._accounts.delete_sessions_for_user(SYSTEM, user_id)

    def list_for_user(self, user_id: str) -> list[Session]:
        out = []
        for r in self._accounts.list_sessions_for_user(SYSTEM, user_id):
            s = self._session(r)
            if s is not None:
                out.append(s)
        return out


class StoreMembershipRepo:
    """``MembershipRepo`` derived from ``users.tenant_id`` + ``users.role``.

    One tenant per user (MVP store): moving a user to another tenant is refused.
    Tenants are created by a system job (``Store.create_tenant``), not here.
    """

    def __init__(self, store: Store) -> None:
        self._store = store
        self._accounts = AccountStore(store)

    def add_tenant(self, tenant: Tenant) -> None:
        raise DuplicateError("create tenants with Store.create_tenant")

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        try:
            t = self._store.get_tenant(TenantContext(tenant_id, SYSTEM.actor))
        except Exception:
            return None
        return Tenant(t.id, t.name)

    def set_membership(self, membership: Membership) -> None:
        a = self._accounts.get_user(SYSTEM, membership.user_id)
        if a is None or a.tenant_id != membership.tenant_id:
            raise KeyError("users belong to exactly one tenant")
        self._store.set_role(TenantContext(a.tenant_id, SYSTEM.actor), a.id, str(membership.role))

    def remove_membership(self, user_id: str, tenant_id: str) -> None:
        # No row to delete: an unknown role fails closed in `can`, so revoke by role.
        a = self._accounts.get_user(SYSTEM, user_id)
        if a is not None and a.tenant_id == tenant_id:
            self._store.set_role(TenantContext(tenant_id, SYSTEM.actor), user_id, "none")
            self._accounts.delete_sessions_for_user(SYSTEM, user_id)

    def memberships_for_user(self, user_id: str) -> list[Membership]:
        a = self._accounts.get_user(SYSTEM, user_id)
        return [] if a is None else [Membership(a.id, a.tenant_id, a.role)]

    def members_of(self, tenant_id: str) -> list[Membership]:
        try:
            users = self._store.list_users(TenantContext(tenant_id, SYSTEM.actor))
        except NotFound:
            return []
        return [Membership(u.id, u.tenant_id, u.role) for u in users]
