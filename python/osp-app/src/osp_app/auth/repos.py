"""Repository Protocols and in-memory implementations.

`osp-store` (L4, task C9) will provide database-backed implementations of the
same Protocols; until then the in-memory ones back tests and local use.
"""

from __future__ import annotations

from typing import Protocol

from .model import Membership, Session, Tenant, User, normalise_email


class DuplicateError(Exception):
    pass


class UserRepo(Protocol):
    def get(self, user_id: str) -> User | None: ...
    def get_by_email(self, email: str) -> User | None: ...
    def add(self, user: User) -> None:
        """Raises DuplicateError if the id or (normalised) email exists."""
        ...

    def update(self, user: User) -> None: ...


class MembershipRepo(Protocol):
    def add_tenant(self, tenant: Tenant) -> None: ...
    def get_tenant(self, tenant_id: str) -> Tenant | None: ...
    def set_membership(self, membership: Membership) -> None:
        """Insert or replace the (user_id, tenant_id) membership."""
        ...

    def remove_membership(self, user_id: str, tenant_id: str) -> None: ...
    def memberships_for_user(self, user_id: str) -> list[Membership]: ...
    def members_of(self, tenant_id: str) -> list[Membership]: ...


class SessionRepo(Protocol):
    def add(self, session: Session) -> None: ...
    def get(self, session_id: str) -> Session | None: ...
    def update(self, session: Session) -> None: ...
    def delete(self, session_id: str) -> None: ...
    def delete_for_user(self, user_id: str) -> None: ...
    def list_for_user(self, user_id: str) -> list[Session]: ...


class InMemoryUserRepo:
    def __init__(self) -> None:
        self._by_id: dict[str, User] = {}

    def get(self, user_id: str) -> User | None:
        return self._by_id.get(user_id)

    def get_by_email(self, email: str) -> User | None:
        key = normalise_email(email)
        return next((u for u in self._by_id.values() if u.email == key), None)

    def add(self, user: User) -> None:
        if user.id in self._by_id or self.get_by_email(user.email) is not None:
            raise DuplicateError("user exists")
        self._by_id[user.id] = user

    def update(self, user: User) -> None:
        if user.id not in self._by_id:
            raise KeyError(user.id)
        self._by_id[user.id] = user


class InMemoryMembershipRepo:
    def __init__(self) -> None:
        self._tenants: dict[str, Tenant] = {}
        self._members: dict[tuple[str, str], Membership] = {}

    def add_tenant(self, tenant: Tenant) -> None:
        if tenant.id in self._tenants:
            raise DuplicateError("tenant exists")
        self._tenants[tenant.id] = tenant

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        return self._tenants.get(tenant_id)

    def set_membership(self, membership: Membership) -> None:
        self._members[(membership.user_id, membership.tenant_id)] = membership

    def remove_membership(self, user_id: str, tenant_id: str) -> None:
        self._members.pop((user_id, tenant_id), None)

    def memberships_for_user(self, user_id: str) -> list[Membership]:
        return [m for (uid, _), m in self._members.items() if uid == user_id]

    def members_of(self, tenant_id: str) -> list[Membership]:
        return [m for (_, tid), m in self._members.items() if tid == tenant_id]


class InMemorySessionRepo:
    def __init__(self) -> None:
        self._by_id: dict[str, Session] = {}

    def add(self, session: Session) -> None:
        if session.id in self._by_id:
            raise DuplicateError("session exists")
        self._by_id[session.id] = session

    def get(self, session_id: str) -> Session | None:
        return self._by_id.get(session_id)

    def update(self, session: Session) -> None:
        if session.id in self._by_id:
            self._by_id[session.id] = session

    def delete(self, session_id: str) -> None:
        self._by_id.pop(session_id, None)

    def delete_for_user(self, user_id: str) -> None:
        for sid in [s.id for s in self._by_id.values() if s.user_id == user_id]:
            del self._by_id[sid]

    def list_for_user(self, user_id: str) -> list[Session]:
        return [s for s in self._by_id.values() if s.user_id == user_id]
