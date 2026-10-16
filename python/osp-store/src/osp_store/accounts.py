"""Researcher sign-in state (task C10, migration ``0004_accounts``).

Backs the store-backed ``UserRepo`` / ``SessionRepo`` in ``osp_app``. Sign-in happens
before a tenant is known (a session token or an email is all there is), so every
method takes a :class:`SystemContext`, like ``Store.find_user_for_login``.

- The confirmed TOTP secret stays in ``users.totp_secret_ct``; the pending one is in
  ``user_mfa.totp_pending_ct``; both are encrypted with the store keyring.
- Sessions are stored by ``SHA-256(token)`` (the caller hashes); the token is never seen.
- Also here: deleting a survey that was never published (builder "delete draft").
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, insert, select, update

from . import schema as t
from .context import SystemContext, TenantContext, require_ctx, require_system
from .errors import Conflict, InvalidInput, NotFound

if TYPE_CHECKING:
    from .store import Store

SESSION_STAGES = frozenset({"full", "mfa_pending"})


@dataclass(frozen=True, slots=True)
class AccountUser:
    """Everything the auth core needs about one researcher (secrets decrypted)."""

    id: str
    tenant_id: str
    email: str
    role: str
    password_hash: str | None
    created_at: datetime
    totp_secret: str | None
    totp_pending_secret: str | None
    totp_last_step: int | None
    recovery_code_hashes: tuple[str, ...]
    failed_logins: int
    locked_until: datetime | None


@dataclass(frozen=True, slots=True)
class AuthSessionRow:
    id: str  # SHA-256 hex of the token
    user_id: str
    stage: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime


def _uid(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 36:
        raise NotFound("no such user")
    return value


def _sid(value: object) -> str | None:
    if not isinstance(value, str) or not 0 < len(value) <= 64:
        return None
    return value


class AccountStore:
    """Sign-in tables, sharing the engine, keyring and clock of a ``Store``."""

    def __init__(self, store: Store) -> None:
        self._s = store

    # -- users -----------------------------------------------------------------------

    def _account(self, conn: Any, r: Mapping[str, Any]) -> AccountUser:
        s = self._s
        mfa = conn.execute(select(t.user_mfa).where(t.user_mfa.c.id == r["id"])).mappings().first()
        secret = None
        if r["totp_secret_ct"] is not None:
            secret = s._dec(
                r["totp_secret_ct"], r["totp_secret_key_id"], "users", "totp_secret", r["id"]
            )
        pending = None
        if mfa is not None and mfa["totp_pending_ct"] is not None:
            pending = s._dec(
                mfa["totp_pending_ct"],
                mfa["totp_pending_key_id"],
                "user_mfa",
                "totp_pending",
                r["id"],
            )
        return AccountUser(
            id=r["id"],
            tenant_id=r["tenant_id"],
            email=r["email"],
            role=r["role"],
            password_hash=r["password_hash"],
            created_at=r["created_at"],
            totp_secret=secret,
            totp_pending_secret=pending,
            totp_last_step=None if mfa is None else mfa["totp_last_step"],
            recovery_code_hashes=tuple(mfa["recovery_code_hashes"]) if mfa is not None else (),
            failed_logins=r["failed_logins"],
            locked_until=r["locked_until"],
        )

    def get_user(self, sys: SystemContext, user_id: str) -> AccountUser | None:
        require_system(sys)
        try:
            uid = _uid(user_id)
        except NotFound:
            return None
        with self._s._engine.connect() as conn:
            r = conn.execute(select(t.users).where(t.users.c.id == uid)).mappings().first()
            return None if r is None else self._account(conn, r)

    def get_user_by_email(self, sys: SystemContext, email: str) -> AccountUser | None:
        require_system(sys)
        found = self._s.find_user_for_login(sys, email)
        return None if found is None else self.get_user(sys, found.id)

    def add_user(
        self,
        sys: SystemContext,
        *,
        user_id: str,
        tenant_id: str,
        email: str,
        role: str,
        password_hash: str,
        created_at: datetime,
    ) -> None:
        """Create a researcher with a caller-chosen id (the auth core picks ids)."""
        sys = require_system(sys)
        uid = _uid(user_id)
        if not isinstance(role, str) or not 0 < len(role) <= 32:
            raise InvalidInput("role must be 1-32 characters")
        e = self._s._email(email)
        with self._s._tx() as conn:
            self._s._one(conn, select(t.tenants.c.id).where(t.tenants.c.id == tenant_id))
            if conn.execute(select(t.users.c.id).where(t.users.c.email == e)).first():
                raise Conflict("email already registered")
            conn.execute(
                insert(t.users).values(
                    id=uid,
                    tenant_id=tenant_id,
                    email=e,
                    role=role,
                    password_hash=password_hash,
                    created_at=created_at,
                )
            )
            self._s._audit(conn, tenant_id, sys.actor, "user.create", "user", uid)

    def save_user(self, sys: SystemContext, user: AccountUser) -> None:
        """Write the mutable sign-in fields of ``user`` (by id). Audits which changed."""
        sys = require_system(sys)
        uid = _uid(user.id)
        s = self._s
        before = self.get_user(sys, uid)
        if before is None:
            raise NotFound("no such user")
        values: dict[str, Any] = {
            "password_hash": user.password_hash,
            "failed_logins": int(user.failed_logins),
            "locked_until": user.locked_until,
        }
        if user.totp_secret is None:
            values |= {"totp_secret_ct": None, "totp_secret_key_id": None}
        else:
            blob, kid = s._enc(user.totp_secret, "users", "totp_secret", uid)
            values |= {"totp_secret_ct": blob, "totp_secret_key_id": kid}
        mfa: dict[str, Any] = {
            "totp_last_step": user.totp_last_step,
            "recovery_code_hashes": [str(h) for h in user.recovery_code_hashes],
            "totp_pending_ct": None,
            "totp_pending_key_id": None,
        }
        if user.totp_pending_secret is not None:
            blob, kid = s._enc(user.totp_pending_secret, "user_mfa", "totp_pending", uid)
            mfa |= {"totp_pending_ct": blob, "totp_pending_key_id": kid}
        changed = sorted(
            f
            for f in (
                "password_hash",
                "totp_secret",
                "totp_pending_secret",
                "recovery_code_hashes",
                "failed_logins",
                "locked_until",
            )
            if getattr(before, f) != getattr(user, f)
        )
        with s._tx() as conn:
            conn.execute(update(t.users).where(t.users.c.id == uid).values(**values))
            exists = conn.execute(select(t.user_mfa.c.id).where(t.user_mfa.c.id == uid)).first()
            if exists:
                conn.execute(update(t.user_mfa).where(t.user_mfa.c.id == uid).values(**mfa))
            else:
                conn.execute(insert(t.user_mfa).values(id=uid, **mfa))
            if changed:  # field names only, never values
                s._audit(
                    conn, before.tenant_id, sys.actor, "user.auth", "user", uid, {"fields": changed}
                )

    # -- sign-in sessions --------------------------------------------------------------

    @staticmethod
    def _session(r: Mapping[str, Any]) -> AuthSessionRow:
        return AuthSessionRow(
            r["id"], r["user_id"], r["stage"], r["created_at"], r["last_seen_at"], r["expires_at"]
        )

    def add_session(self, sys: SystemContext, row: AuthSessionRow) -> None:
        require_system(sys)
        sid = _sid(row.id)
        if sid is None or row.stage not in SESSION_STAGES:
            raise InvalidInput("bad session row")
        with self._s._tx() as conn:
            if conn.execute(
                select(t.auth_sessions.c.id).where(t.auth_sessions.c.id == sid)
            ).first():
                raise Conflict("session exists")
            conn.execute(
                insert(t.auth_sessions).values(
                    id=sid,
                    user_id=_uid(row.user_id),
                    stage=row.stage,
                    created_at=row.created_at,
                    last_seen_at=row.last_seen_at,
                    expires_at=row.expires_at,
                )
            )

    def get_session(self, sys: SystemContext, session_id: str) -> AuthSessionRow | None:
        require_system(sys)
        sid = _sid(session_id)
        if sid is None:
            return None
        with self._s._engine.connect() as conn:
            r = (
                conn.execute(select(t.auth_sessions).where(t.auth_sessions.c.id == sid))
                .mappings()
                .first()
            )
        return None if r is None else self._session(r)

    def update_session(self, sys: SystemContext, row: AuthSessionRow) -> None:
        require_system(sys)
        sid = _sid(row.id)
        if sid is None or row.stage not in SESSION_STAGES:
            return
        with self._s._tx() as conn:
            conn.execute(
                update(t.auth_sessions)
                .where(t.auth_sessions.c.id == sid)
                .values(stage=row.stage, last_seen_at=row.last_seen_at, expires_at=row.expires_at)
            )

    def delete_session(self, sys: SystemContext, session_id: str) -> None:
        require_system(sys)
        sid = _sid(session_id)
        if sid is None:
            return
        with self._s._tx() as conn:
            conn.execute(delete(t.auth_sessions).where(t.auth_sessions.c.id == sid))

    def delete_sessions_for_user(self, sys: SystemContext, user_id: str) -> None:
        require_system(sys)
        with self._s._tx() as conn:
            conn.execute(delete(t.auth_sessions).where(t.auth_sessions.c.user_id == user_id))

    def list_sessions_for_user(self, sys: SystemContext, user_id: str) -> list[AuthSessionRow]:
        require_system(sys)
        with self._s._engine.connect() as conn:
            rows = conn.execute(
                select(t.auth_sessions)
                .where(t.auth_sessions.c.user_id == user_id)
                .order_by(t.auth_sessions.c.created_at, t.auth_sessions.c.id)
            ).mappings()
            return [self._session(r) for r in rows]

    # -- surveys ---------------------------------------------------------------------

    def set_survey_title(self, ctx: TenantContext, survey_id: str, title: str) -> None:
        """Keep the listing title in step with the draft's title."""
        ctx = require_ctx(ctx)
        if not isinstance(title, str) or not 0 < len(title) <= 500:
            raise InvalidInput("title must be 1-500 characters")
        with self._s._tx() as conn:
            res = conn.execute(
                update(t.surveys).where(self._s._survey_where(ctx, survey_id)).values(title=title)
            )
            if res.rowcount != 1:
                raise NotFound("no such survey")

    def delete_unpublished_survey(self, ctx: TenantContext, survey_id: str) -> None:
        """Delete a survey with its draft and op log. A survey with a published version
        is refused (:class:`Conflict`): versions and responses are research records."""
        ctx = require_ctx(ctx)
        with self._s._tx() as conn:
            self._s._one(conn, select(t.surveys.c.id).where(self._s._survey_where(ctx, survey_id)))
            published = conn.execute(
                select(func.count())
                .select_from(t.versions)
                .where(
                    (t.versions.c.tenant_id == ctx.tenant_id)
                    & (t.versions.c.survey_id == survey_id)
                )
            ).scalar_one()
            if published:
                raise Conflict("survey has published versions")
            where_child = (t.op_log.c.tenant_id == ctx.tenant_id) & (
                t.op_log.c.survey_id == survey_id
            )
            conn.execute(delete(t.op_log).where(where_child))
            conn.execute(
                delete(t.drafts).where(
                    (t.drafts.c.tenant_id == ctx.tenant_id) & (t.drafts.c.survey_id == survey_id)
                )
            )
            conn.execute(delete(t.surveys).where(self._s._survey_where(ctx, survey_id)))
            self._s._audit(conn, ctx.tenant_id, ctx.actor, "survey.delete", "survey", survey_id)
