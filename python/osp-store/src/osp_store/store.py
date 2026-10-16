"""The repository. Every public method takes a context first and fails closed.

- Tenant-scoped methods take a :class:`TenantContext`; every query filters on its
  ``tenant_id``. A row in another tenant is reported as :class:`NotFound`.
- Cross-tenant maintenance takes a :class:`SystemContext` (a different type).
- Survey JSON, op params/inverses and version meta are opaque JSON.
- Participant answers, autosaved instances and TOTP secrets are encrypted with
  the keyring before they reach the database.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, Engine, delete, func, insert, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from . import schema as t
from .context import SystemContext, TenantContext, require_ctx, require_system
from .crypto import Keyring, aad_for, canonical_json
from .errors import (
    Conflict,
    InvalidInput,
    NotFound,
    RevisionConflict,
    StoreError,
)
from .records import (
    ANSWER_STATES,
    AuditEntry,
    Draft,
    OpLogEntry,
    OpRecord,
    Response,
    Session,
    Survey,
    Tenant,
    User,
    Version,
)
from .retention import (
    ParticipantRow,
    RetentionPlan,
    RetentionPolicy,
    SurveyFacts,
    plan_retention,
)

Clock = Callable[[], datetime]
ALLOCATION_MODES = frozenset({"server", "limesurvey-native"})
_MAX_SEED = 2**63 - 1


class _Unset:
    pass


UNSET: Any = _Unset()


def is_constraint_violation(exc: DBAPIError) -> bool:
    """IntegrityError, or SQLSTATE class 23 (pg8000 reports FK violations as
    ProgrammingError with the code in ``orig.args[0]["C"]``)."""
    if isinstance(exc, IntegrityError):
        return True
    arg = exc.orig.args[0] if exc.orig is not None and exc.orig.args else None
    return isinstance(arg, dict) and str(arg.get("C", "")).startswith("23")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


def checksum(body: object) -> str:
    """SHA-256 (hex) of the canonical JSON of ``body``: a published version's checksum."""
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _json(value: object, what: str) -> Any:
    """Prove ``value`` is plain JSON and return a detached copy of it."""
    try:
        return json.loads(canonical_json(value))
    except (TypeError, ValueError, RecursionError) as exc:
        raise InvalidInput(f"{what} is not JSON-serialisable: {exc}") from exc


def _id(value: object) -> str:
    """Ids are strings; anything else can't exist, so fail closed as NotFound."""
    if not isinstance(value, str) or not value or len(value) > 36:
        raise NotFound("no such row")
    return value


def _aware(value: datetime, what: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise InvalidInput(f"{what} must be a timezone-aware datetime")
    return value


def _seed(value: object) -> int:
    if type(value) is not int or not 0 < value <= _MAX_SEED:
        raise InvalidInput("session_seed must be a positive integer (semantics §7)")
    return value


def _answers(value: object) -> dict[str, dict[str, Any]]:
    """Answers map ``var -> {"state", "value"}`` with the four states of semantics §1."""
    if not isinstance(value, Mapping):
        raise InvalidInput("answers must be an object of {var: {state, value}}")
    out = _json(dict(value), "answers")
    for var, ans in out.items():
        if not isinstance(ans, dict) or ans.get("state") not in ANSWER_STATES:
            raise InvalidInput(f"answer {var!r} needs a state in {sorted(ANSWER_STATES)}")
        if ans["state"] != "answered" and ans.get("value") is not None:
            raise InvalidInput(f"answer {var!r} is {ans['state']} so its value must be null")
    return out


class Store:
    def __init__(self, engine: Engine, keyring: Keyring, clock: Clock = _utcnow) -> None:
        self._engine = engine
        self._keys = keyring
        self._clock = clock

    # -- plumbing ------------------------------------------------------------------

    def _now(self) -> datetime:
        return _aware(self._clock(), "clock()")

    @contextmanager
    def _tx(self) -> Iterator[Connection]:
        try:
            with self._engine.begin() as conn:
                yield conn
        except DBAPIError as exc:
            if is_constraint_violation(exc):
                raise Conflict("constraint violated") from exc
            raise

    def _audit(
        self,
        conn: Connection,
        tenant_id: str | None,
        actor: str,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        conn.execute(
            insert(t.audit_log).values(
                tenant_id=tenant_id,
                actor=actor,
                action=action,
                target_type=target_type,
                target_id=target_id,
                detail=_json(dict(detail or {}), "audit detail"),
                at=self._now(),
            )
        )

    def _enc(self, value: object, table: str, column: str, row_id: str) -> tuple[bytes, str]:
        e = self._keys.encrypt_json(value, aad_for(table, column, row_id))
        return e.blob, e.key_id

    def _dec(self, blob: bytes, key_id: str, table: str, column: str, row_id: str) -> Any:
        return self._keys.decrypt_json(key_id, blob, aad_for(table, column, row_id))

    def _one(self, conn: Connection, stmt: Any) -> Any:
        row = conn.execute(stmt).mappings().first()
        if row is None:
            raise NotFound("no such row")
        return row

    # -- tenants (system) ----------------------------------------------------------

    def create_tenant(self, sys: SystemContext, name: str) -> Tenant:
        sys = require_system(sys)
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise InvalidInput("tenant name must be 1-200 characters")
        row = {"id": _new_id(), "name": name.strip(), "created_at": self._now()}
        with self._tx() as conn:
            conn.execute(insert(t.tenants).values(**row))
            self._audit(conn, row["id"], sys.actor, "tenant.create", "tenant", row["id"])
        return Tenant(**row)

    def get_tenant(self, ctx: TenantContext) -> Tenant:
        ctx = require_ctx(ctx)
        with self._engine.connect() as conn:
            r = self._one(conn, select(t.tenants).where(t.tenants.c.id == ctx.tenant_id))
        return Tenant(r["id"], r["name"], r["created_at"])

    # -- users ---------------------------------------------------------------------

    @staticmethod
    def _user(r: Mapping[str, Any]) -> User:
        return User(
            id=r["id"],
            tenant_id=r["tenant_id"],
            email=r["email"],
            role=r["role"],
            password_hash=r["password_hash"],
            has_totp=r["totp_secret_ct"] is not None,
            failed_logins=r["failed_logins"],
            locked_until=r["locked_until"],
            created_at=r["created_at"],
        )

    @staticmethod
    def _email(email: object) -> str:
        if not isinstance(email, str):
            raise InvalidInput("email must be a string")
        e = email.strip().lower()
        if not 3 <= len(e) <= 320 or e.count("@") != 1 or e.startswith("@") or e.endswith("@"):
            raise InvalidInput("not an email address")
        return e

    def create_user(
        self, ctx: TenantContext, email: str, role: str, password_hash: str | None = None
    ) -> User:
        ctx = require_ctx(ctx)
        if not isinstance(role, str) or not 0 < len(role) <= 32:
            raise InvalidInput("role must be 1-32 characters")
        if password_hash is not None and not isinstance(password_hash, str):
            raise InvalidInput("password_hash must be a string")
        uid = _new_id()
        values = {
            "id": uid,
            "tenant_id": ctx.tenant_id,
            "email": self._email(email),
            "role": role,
            "password_hash": password_hash,
            "created_at": self._now(),
        }
        with self._tx() as conn:
            self._one(conn, select(t.tenants.c.id).where(t.tenants.c.id == ctx.tenant_id))
            taken = conn.execute(
                select(t.users.c.id).where(t.users.c.email == values["email"])
            ).first()
            if taken is not None:
                raise Conflict("email already registered")
            conn.execute(insert(t.users).values(**values))
            self._audit(conn, ctx.tenant_id, ctx.actor, "user.create", "user", uid)
            return self._user(self._one(conn, select(t.users).where(t.users.c.id == uid)))

    def _user_where(self, ctx: TenantContext, user_id: object) -> Any:
        return (t.users.c.tenant_id == ctx.tenant_id) & (t.users.c.id == _id(user_id))

    def get_user(self, ctx: TenantContext, user_id: str) -> User:
        ctx = require_ctx(ctx)
        with self._engine.connect() as conn:
            return self._user(
                self._one(conn, select(t.users).where(self._user_where(ctx, user_id)))
            )

    def list_users(self, ctx: TenantContext) -> list[User]:
        ctx = require_ctx(ctx)
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(t.users)
                .where(t.users.c.tenant_id == ctx.tenant_id)
                .order_by(t.users.c.email)
            ).mappings()
            return [self._user(r) for r in rows]

    def find_user_for_login(self, sys: SystemContext, email: str) -> User | None:
        """Login happens before a tenant is known, so this one lookup is cross-tenant."""
        require_system(sys)
        try:
            e = self._email(email)
        except InvalidInput:
            return None
        with self._engine.connect() as conn:
            r = conn.execute(select(t.users).where(t.users.c.email == e)).mappings().first()
        return None if r is None else self._user(r)

    def _update_user(self, ctx: TenantContext, user_id: str, action: str, **values: Any) -> None:
        with self._tx() as conn:
            res = conn.execute(
                update(t.users).where(self._user_where(ctx, user_id)).values(**values)
            )
            if res.rowcount != 1:
                raise NotFound("no such user")
            self._audit(conn, ctx.tenant_id, ctx.actor, action, "user", user_id)

    def set_password_hash(self, ctx: TenantContext, user_id: str, password_hash: str) -> None:
        ctx = require_ctx(ctx)
        if not isinstance(password_hash, str) or not password_hash:
            raise InvalidInput("password_hash must be a non-empty string")
        self._update_user(ctx, user_id, "user.password", password_hash=password_hash)

    def set_role(self, ctx: TenantContext, user_id: str, role: str) -> None:
        ctx = require_ctx(ctx)
        if not isinstance(role, str) or not 0 < len(role) <= 32:
            raise InvalidInput("role must be 1-32 characters")
        self._update_user(ctx, user_id, "user.role", role=role)

    def set_totp_secret(self, ctx: TenantContext, user_id: str, secret: str | None) -> None:
        """Store (encrypted) or clear the user's TOTP secret."""
        ctx = require_ctx(ctx)
        uid = _id(user_id)
        if secret is None:
            self._update_user(
                ctx, uid, "user.totp.clear", totp_secret_ct=None, totp_secret_key_id=None
            )
            return
        if not isinstance(secret, str) or not secret:
            raise InvalidInput("TOTP secret must be a non-empty string")
        blob, kid = self._enc(secret, "users", "totp_secret", uid)
        self._update_user(ctx, uid, "user.totp.set", totp_secret_ct=blob, totp_secret_key_id=kid)

    def get_totp_secret(self, ctx: TenantContext, user_id: str) -> str | None:
        ctx = require_ctx(ctx)
        with self._engine.connect() as conn:
            r = self._one(
                conn,
                select(t.users.c.id, t.users.c.totp_secret_ct, t.users.c.totp_secret_key_id).where(
                    self._user_where(ctx, user_id)
                ),
            )
        if r["totp_secret_ct"] is None:
            return None
        return self._dec(
            r["totp_secret_ct"], r["totp_secret_key_id"], "users", "totp_secret", r["id"]
        )

    def record_login_failure(
        self, ctx: TenantContext, user_id: str, locked_until: datetime | None = None
    ) -> int:
        """Increment the failure counter (and optionally lock). Returns the new count."""
        ctx = require_ctx(ctx)
        if locked_until is not None:
            _aware(locked_until, "locked_until")
        with self._tx() as conn:
            res = conn.execute(
                update(t.users)
                .where(self._user_where(ctx, user_id))
                .values(failed_logins=t.users.c.failed_logins + 1, locked_until=locked_until)
            )
            if res.rowcount != 1:
                raise NotFound("no such user")
            self._audit(conn, ctx.tenant_id, ctx.actor, "user.login_failed", "user", user_id)
            return conn.execute(
                select(t.users.c.failed_logins).where(self._user_where(ctx, user_id))
            ).scalar_one()

    def reset_login_failures(self, ctx: TenantContext, user_id: str) -> None:
        ctx = require_ctx(ctx)
        self._update_user(ctx, user_id, "user.login_ok", failed_logins=0, locked_until=None)

    # -- surveys and drafts --------------------------------------------------------

    @staticmethod
    def _survey(r: Mapping[str, Any]) -> Survey:
        policy = RetentionPolicy(r["retention_kind"], r["retention_days"], r["retention_until"])
        return Survey(
            r["id"],
            r["tenant_id"],
            r["title"],
            r["created_by"],
            r["created_at"],
            r["closed_at"],
            policy,
        )

    def _survey_where(self, ctx: TenantContext, survey_id: object) -> Any:
        return (t.surveys.c.tenant_id == ctx.tenant_id) & (t.surveys.c.id == _id(survey_id))

    def create_survey(self, ctx: TenantContext, title: str, body: object) -> tuple[Survey, Draft]:
        """New survey with its draft at revision 0. ``body`` is opaque survey JSON."""
        ctx = require_ctx(ctx)
        if not isinstance(title, str) or not 0 < len(title) <= 500:
            raise InvalidInput("title must be 1-500 characters")
        body = _json(body, "survey body")
        sid, now = _new_id(), self._now()
        with self._tx() as conn:
            self._one(conn, select(t.tenants.c.id).where(t.tenants.c.id == ctx.tenant_id))
            conn.execute(
                insert(t.surveys).values(
                    id=sid,
                    tenant_id=ctx.tenant_id,
                    title=title,
                    created_by=ctx.actor,
                    created_at=now,
                )
            )
            conn.execute(
                insert(t.drafts).values(
                    survey_id=sid,
                    tenant_id=ctx.tenant_id,
                    revision=0,
                    body=body,
                    updated_by=ctx.actor,
                    updated_at=now,
                )
            )
            self._audit(conn, ctx.tenant_id, ctx.actor, "survey.create", "survey", sid)
            s = self._survey(self._one(conn, select(t.surveys).where(t.surveys.c.id == sid)))
        return s, Draft(sid, 0, body, ctx.actor, now)

    def get_survey(self, ctx: TenantContext, survey_id: str) -> Survey:
        ctx = require_ctx(ctx)
        with self._engine.connect() as conn:
            return self._survey(
                self._one(conn, select(t.surveys).where(self._survey_where(ctx, survey_id)))
            )

    def list_surveys(self, ctx: TenantContext) -> list[Survey]:
        ctx = require_ctx(ctx)
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(t.surveys)
                .where(t.surveys.c.tenant_id == ctx.tenant_id)
                .order_by(t.surveys.c.created_at, t.surveys.c.id)
            ).mappings()
            return [self._survey(r) for r in rows]

    def set_retention(self, ctx: TenantContext, survey_id: str, policy: RetentionPolicy) -> None:
        ctx = require_ctx(ctx)
        if not isinstance(policy, RetentionPolicy):
            raise InvalidInput("policy must be a RetentionPolicy")
        policy.validate()
        with self._tx() as conn:
            res = conn.execute(
                update(t.surveys)
                .where(self._survey_where(ctx, survey_id))
                .values(
                    retention_kind=policy.kind,
                    retention_days=policy.days,
                    retention_until=policy.until,
                )
            )
            if res.rowcount != 1:
                raise NotFound("no such survey")
            detail = {"kind": policy.kind, "days": policy.days}
            if policy.until is not None:
                detail["until"] = policy.until.isoformat()
            self._audit(
                conn, ctx.tenant_id, ctx.actor, "survey.retention", "survey", survey_id, detail
            )

    def close_survey(self, ctx: TenantContext, survey_id: str, at: datetime | None = None) -> None:
        ctx = require_ctx(ctx)
        closed = self._now() if at is None else _aware(at, "at")
        with self._tx() as conn:
            res = conn.execute(
                update(t.surveys).where(self._survey_where(ctx, survey_id)).values(closed_at=closed)
            )
            if res.rowcount != 1:
                raise NotFound("no such survey")
            self._audit(conn, ctx.tenant_id, ctx.actor, "survey.close", "survey", survey_id)

    def get_draft(self, ctx: TenantContext, survey_id: str) -> Draft:
        ctx = require_ctx(ctx)
        with self._engine.connect() as conn:
            r = self._one(
                conn,
                select(t.drafts).where(
                    (t.drafts.c.tenant_id == ctx.tenant_id)
                    & (t.drafts.c.survey_id == _id(survey_id))
                ),
            )
        return Draft(r["survey_id"], r["revision"], r["body"], r["updated_by"], r["updated_at"])

    def save_draft(
        self,
        ctx: TenantContext,
        survey_id: str,
        body: object,
        base_revision: int,
        ops: Sequence[OpRecord] = (),
        txn_id: str | None = None,
    ) -> Draft:
        """Replace the draft iff it is still at ``base_revision``; log ``ops`` as one txn.

        Raises :class:`RevisionConflict` if someone else saved first.
        """
        ctx = require_ctx(ctx)
        sid = _id(survey_id)
        if type(base_revision) is not int or base_revision < 0:
            raise InvalidInput("base_revision must be a non-negative integer")
        body = _json(body, "survey body")
        op_rows = []
        for i, op in enumerate(ops):
            if not isinstance(op, OpRecord) or not isinstance(op.op_id, str) or not op.op_id:
                raise InvalidInput(f"ops[{i}] must be an OpRecord with an op_id")
            op_rows.append(
                (op.op_id, _json(op.params, "op params"), _json(op.inverse, "op inverse"))
            )
        txn = _new_id() if txn_id is None else txn_id
        if not isinstance(txn, str) or not 0 < len(txn) <= 36:
            raise InvalidInput("txn_id must be a string of at most 36 characters")
        now, new_rev = self._now(), base_revision + 1
        where = (t.drafts.c.tenant_id == ctx.tenant_id) & (t.drafts.c.survey_id == sid)
        with self._tx() as conn:
            res = conn.execute(
                update(t.drafts)
                .where(where & (t.drafts.c.revision == base_revision))
                .values(body=body, revision=new_rev, updated_by=ctx.actor, updated_at=now)
            )
            if res.rowcount != 1:
                current = conn.execute(select(t.drafts.c.revision).where(where)).scalar()
                if current is None:
                    raise NotFound("no such survey")
                raise RevisionConflict(base_revision, current)
            for seq, (op_id, params, inverse) in enumerate(op_rows):
                conn.execute(
                    insert(t.op_log).values(
                        tenant_id=ctx.tenant_id,
                        survey_id=sid,
                        revision=new_rev,
                        seq=seq,
                        txn_id=txn,
                        op_id=op_id,
                        params=params,
                        inverse=inverse,
                        actor=ctx.actor,
                        at=now,
                    )
                )
        return Draft(sid, new_rev, body, ctx.actor, now)

    def list_ops(
        self, ctx: TenantContext, survey_id: str, after_revision: int = 0
    ) -> list[OpLogEntry]:
        ctx = require_ctx(ctx)
        if type(after_revision) is not int:
            raise InvalidInput("after_revision must be an integer")
        self.get_survey(ctx, survey_id)  # NotFound across tenants
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(t.op_log)
                .where(
                    (t.op_log.c.tenant_id == ctx.tenant_id)
                    & (t.op_log.c.survey_id == survey_id)
                    & (t.op_log.c.revision > after_revision)
                )
                .order_by(t.op_log.c.revision, t.op_log.c.seq)
            ).mappings()
            return [
                OpLogEntry(
                    r["survey_id"],
                    r["revision"],
                    r["seq"],
                    r["txn_id"],
                    r["op_id"],
                    r["params"],
                    r["inverse"],
                    r["actor"],
                    r["at"],
                )
                for r in rows
            ]

    # -- published versions (immutable: there is no update method) -----------------

    def _version(self, r: Mapping[str, Any]) -> Version:
        body_text = r["body"]
        if hashlib.sha256(body_text.encode("utf-8")).hexdigest() != r["checksum"]:
            raise StoreError(f"version {r['id']} fails its checksum: stored body was altered")
        return Version(
            r["id"],
            r["survey_id"],
            r["number"],
            r["checksum"],
            json.loads(body_text),
            bytes(r["xform"]),
            r["meta"],
            r["published_by"],
            r["published_at"],
        )

    def publish_version(
        self,
        ctx: TenantContext,
        survey_id: str,
        xform: bytes,
        meta: object = None,
        body: object = UNSET,
    ) -> Version:
        """Freeze ``body`` (default: the current draft) as the next immutable version."""
        ctx = require_ctx(ctx)
        sid = _id(survey_id)
        if not isinstance(xform, bytes | bytearray):
            raise InvalidInput("xform must be bytes")
        meta = _json({} if meta is None else meta, "version meta")
        vid, now = _new_id(), self._now()
        with self._tx() as conn:
            self._one(conn, select(t.surveys.c.id).where(self._survey_where(ctx, sid)))
            if body is UNSET:
                body = conn.execute(
                    select(t.drafts.c.body).where(
                        (t.drafts.c.tenant_id == ctx.tenant_id) & (t.drafts.c.survey_id == sid)
                    )
                ).scalar_one()
            text = canonical_json(_json(body, "survey body"))
            number = (
                conn.execute(
                    select(func.max(t.versions.c.number)).where(t.versions.c.survey_id == sid)
                ).scalar()
                or 0
            ) + 1
            conn.execute(
                insert(t.versions).values(
                    id=vid,
                    tenant_id=ctx.tenant_id,
                    survey_id=sid,
                    number=number,
                    checksum=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    body=text,
                    xform=bytes(xform),
                    meta=meta,
                    published_by=ctx.actor,
                    published_at=now,
                )
            )
            self._audit(
                conn,
                ctx.tenant_id,
                ctx.actor,
                "version.publish",
                "version",
                vid,
                {"survey_id": sid, "number": number},
            )
            return self._version(self._one(conn, select(t.versions).where(t.versions.c.id == vid)))

    def _version_where(self, ctx: TenantContext, version_id: object) -> Any:
        return (t.versions.c.tenant_id == ctx.tenant_id) & (t.versions.c.id == _id(version_id))

    def get_version(self, ctx: TenantContext, version_id: str) -> Version:
        ctx = require_ctx(ctx)
        with self._engine.connect() as conn:
            return self._version(
                self._one(conn, select(t.versions).where(self._version_where(ctx, version_id)))
            )

    def list_versions(self, ctx: TenantContext, survey_id: str) -> list[Version]:
        ctx = require_ctx(ctx)
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(t.versions)
                .where(
                    (t.versions.c.tenant_id == ctx.tenant_id)
                    & (t.versions.c.survey_id == _id(survey_id))
                )
                .order_by(t.versions.c.number)
            ).mappings()
            return [self._version(r) for r in rows]

    # -- participant sessions ------------------------------------------------------

    def _session(self, r: Mapping[str, Any]) -> Session:
        instance = None
        if r["instance_ct"] is not None:
            instance = self._dec(
                r["instance_ct"], r["instance_key_id"], "sessions", "instance", r["id"]
            )
        return Session(
            r["id"],
            r["version_id"],
            r["session_seed"],
            r["assigned_conditions"],
            r["realised_orders"],
            r["current_page"],
            instance,
            r["started_at"],
            r["updated_at"],
            r["completed_at"],
        )

    def _session_where(self, ctx: TenantContext, session_id: object) -> Any:
        return (t.sessions.c.tenant_id == ctx.tenant_id) & (t.sessions.c.id == _id(session_id))

    def start_session(
        self,
        ctx: TenantContext,
        version_id: str,
        session_seed: int,
        assigned_conditions: object,
        realised_orders: Mapping[str, Any] | None = None,
    ) -> Session:
        """A participant session bound to one version, with its seed and conditions."""
        ctx = require_ctx(ctx)
        vid = _id(version_id)
        seed = _seed(session_seed)
        conds = _json(assigned_conditions, "assigned_conditions")
        orders = _json(dict(realised_orders or {}), "realised_orders")
        sess_id, now = _new_id(), self._now()
        with self._tx() as conn:
            self._one(conn, select(t.versions.c.id).where(self._version_where(ctx, vid)))
            conn.execute(
                insert(t.sessions).values(
                    id=sess_id,
                    tenant_id=ctx.tenant_id,
                    version_id=vid,
                    session_seed=seed,
                    assigned_conditions=conds,
                    realised_orders=orders,
                    started_at=now,
                    updated_at=now,
                )
            )
        return Session(sess_id, vid, seed, conds, orders, None, None, now, now, None)

    def get_session(self, ctx: TenantContext, session_id: str) -> Session:
        ctx = require_ctx(ctx)
        with self._engine.connect() as conn:
            return self._session(
                self._one(conn, select(t.sessions).where(self._session_where(ctx, session_id)))
            )

    def update_session(
        self,
        ctx: TenantContext,
        session_id: str,
        *,
        current_page: str | None = UNSET,
        instance: object = UNSET,
        add_orders: Mapping[str, Any] | None = None,
        completed: bool = False,
    ) -> Session:
        """Autosave. Realised orders are fixed at first reach (semantics §7): new keys may be
        added, existing ones never change."""
        ctx = require_ctx(ctx)
        sess_id = _id(session_id)
        values: dict[str, Any] = {"updated_at": self._now()}
        if current_page is not UNSET:
            if current_page is not None and (
                not isinstance(current_page, str) or len(current_page) > 200
            ):
                raise InvalidInput("current_page must be a string of at most 200 characters")
            values["current_page"] = current_page
        if instance is not UNSET:
            if instance is None:
                values["instance_ct"] = values["instance_key_id"] = None
            else:
                blob, kid = self._enc(_json(instance, "instance"), "sessions", "instance", sess_id)
                values["instance_ct"], values["instance_key_id"] = blob, kid
        if completed:
            values["completed_at"] = values["updated_at"]
        with self._tx() as conn:
            r = self._one(
                conn,
                select(t.sessions.c.realised_orders).where(self._session_where(ctx, sess_id)),
            )
            if add_orders:
                orders = dict(r["realised_orders"])
                for key, order in _json(dict(add_orders), "realised_orders").items():
                    if key in orders and orders[key] != order:
                        raise InvalidInput(f"order {key!r} is already realised and cannot change")
                    orders[key] = order
                values["realised_orders"] = orders
            conn.execute(
                update(t.sessions).where(self._session_where(ctx, sess_id)).values(**values)
            )
            return self._session(
                self._one(conn, select(t.sessions).where(self._session_where(ctx, sess_id)))
            )

    def delete_session(
        self, ctx: TenantContext, session_id: str, reason: str = "withdrawal"
    ) -> int:
        """Withdrawal before (or after) submission: delete the session and every response
        linked to it. Returns the number of responses deleted."""
        ctx = require_ctx(ctx)
        sess_id = _id(session_id)
        with self._tx() as conn:
            self._one(conn, select(t.sessions.c.id).where(self._session_where(ctx, sess_id)))
            n = conn.execute(
                delete(t.responses).where(
                    (t.responses.c.tenant_id == ctx.tenant_id)
                    & (t.responses.c.session_id == sess_id)
                )
            ).rowcount
            conn.execute(delete(t.sessions).where(self._session_where(ctx, sess_id)))
            self._audit(
                conn,
                ctx.tenant_id,
                ctx.actor,
                "session.delete",
                "session",
                sess_id,
                {"reason": str(reason)[:200], "responses_deleted": n},
            )
        return n

    # -- responses -----------------------------------------------------------------

    def _response(self, r: Mapping[str, Any]) -> Response:
        answers = self._dec(r["answers_ct"], r["answers_key_id"], "responses", "answers", r["id"])
        return Response(
            r["id"],
            r["version_id"],
            r["version_checksum"],
            r["session_id"],
            r["allocation_mode"],
            r["session_seed"],
            r["assigned_conditions"],
            r["realised_orders"],
            r["engine_version"],
            answers,
            r["started_at"],
            r["submitted_at"],
        )

    def _response_where(self, ctx: TenantContext, response_id: object) -> Any:
        return (t.responses.c.tenant_id == ctx.tenant_id) & (t.responses.c.id == _id(response_id))

    def record_response(
        self,
        ctx: TenantContext,
        version_id: str,
        answers: Mapping[str, Mapping[str, Any]],
        allocation_mode: str = "server",
        *,
        session_id: str | None = None,
        session_seed: int | None = None,
        assigned_conditions: object = UNSET,
        realised_orders: object = UNSET,
        engine_version: str | None = None,
        started_at: datetime | None = None,
        submitted_at: datetime | None = None,
    ) -> Response:
        """Store a submitted response bound to one version and that version's checksum.

        With ``session_id``, seed / conditions / orders default to the session's.
        """
        ctx = require_ctx(ctx)
        vid = _id(version_id)
        ans = _answers(answers)
        if allocation_mode not in ALLOCATION_MODES:
            raise InvalidInput(f"allocation_mode must be one of {sorted(ALLOCATION_MODES)}")
        if engine_version is not None and (
            not isinstance(engine_version, str) or len(engine_version) > 64
        ):
            raise InvalidInput("engine_version must be a string of at most 64 characters")
        if started_at is not None:
            _aware(started_at, "started_at")
        submitted = self._now() if submitted_at is None else _aware(submitted_at, "submitted_at")
        rid = _new_id()
        with self._tx() as conn:
            vrow = self._one(
                conn,
                select(t.versions.c.id, t.versions.c.checksum).where(self._version_where(ctx, vid)),
            )
            if session_id is not None:
                srow = self._one(
                    conn, select(t.sessions).where(self._session_where(ctx, session_id))
                )
                if srow["version_id"] != vid:
                    raise InvalidInput("session belongs to a different version")
                session_seed = srow["session_seed"] if session_seed is None else session_seed
                if assigned_conditions is UNSET:
                    assigned_conditions = srow["assigned_conditions"]
                if realised_orders is UNSET:
                    realised_orders = srow["realised_orders"]
                if started_at is None:
                    started_at = srow["started_at"]
            if session_seed is not None:
                _seed(session_seed)
            elif allocation_mode == "server":
                raise InvalidInput("server allocation requires a session_seed")
            blob, kid = self._enc(ans, "responses", "answers", rid)
            conn.execute(
                insert(t.responses).values(
                    id=rid,
                    tenant_id=ctx.tenant_id,
                    version_id=vid,
                    version_checksum=vrow["checksum"],
                    session_id=session_id,
                    allocation_mode=allocation_mode,
                    session_seed=session_seed,
                    assigned_conditions=_json(
                        {} if assigned_conditions is UNSET else assigned_conditions, "conditions"
                    ),
                    realised_orders=_json(
                        {} if realised_orders is UNSET else realised_orders, "realised_orders"
                    ),
                    engine_version=engine_version,
                    answers_ct=blob,
                    answers_key_id=kid,
                    started_at=started_at,
                    submitted_at=submitted,
                )
            )
            return self._response(
                self._one(conn, select(t.responses).where(t.responses.c.id == rid))
            )

    def get_response(self, ctx: TenantContext, response_id: str) -> Response:
        """Decrypts the answers and writes a ``response.read`` audit entry (review §9 Q8)."""
        ctx = require_ctx(ctx)
        with self._tx() as conn:
            r = self._one(conn, select(t.responses).where(self._response_where(ctx, response_id)))
            self._audit(conn, ctx.tenant_id, ctx.actor, "response.read", "response", r["id"])
        return self._response(r)

    def list_responses(self, ctx: TenantContext, version_id: str) -> list[Response]:
        """All responses for one version, decrypted; audited as one ``responses.read``."""
        ctx = require_ctx(ctx)
        vid = _id(version_id)
        with self._tx() as conn:
            self._one(conn, select(t.versions.c.id).where(self._version_where(ctx, vid)))
            rows = list(
                conn.execute(
                    select(t.responses)
                    .where(
                        (t.responses.c.tenant_id == ctx.tenant_id)
                        & (t.responses.c.version_id == vid)
                    )
                    .order_by(t.responses.c.submitted_at, t.responses.c.id)
                ).mappings()
            )
            self._audit(
                conn,
                ctx.tenant_id,
                ctx.actor,
                "responses.read",
                "version",
                vid,
                {"count": len(rows)},
            )
        return [self._response(r) for r in rows]

    def delete_response(
        self, ctx: TenantContext, response_id: str, reason: str = "withdrawal"
    ) -> None:
        """Participant deletion (consent withdrawal, MVP 12b). Also deletes the linked
        session, which holds the autosaved instance."""
        ctx = require_ctx(ctx)
        rid = _id(response_id)
        with self._tx() as conn:
            r = self._one(
                conn, select(t.responses.c.session_id).where(self._response_where(ctx, rid))
            )
            conn.execute(delete(t.responses).where(self._response_where(ctx, rid)))
            if r["session_id"] is not None:
                conn.execute(delete(t.sessions).where(self._session_where(ctx, r["session_id"])))
            self._audit(
                conn,
                ctx.tenant_id,
                ctx.actor,
                "response.delete",
                "response",
                rid,
                {"reason": str(reason)[:200], "session_deleted": r["session_id"] is not None},
            )

    # -- audit ---------------------------------------------------------------------

    def list_audit(self, ctx: TenantContext, limit: int = 1000) -> list[AuditEntry]:
        ctx = require_ctx(ctx)
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(t.audit_log)
                .where(t.audit_log.c.tenant_id == ctx.tenant_id)
                .order_by(t.audit_log.c.id)
                .limit(max(1, min(int(limit), 10_000)))
            ).mappings()
            return [
                AuditEntry(
                    r["id"],
                    r["tenant_id"],
                    r["actor"],
                    r["action"],
                    r["target_type"],
                    r["target_id"],
                    r["detail"],
                    r["at"],
                )
                for r in rows
            ]

    # -- retention (system) --------------------------------------------------------

    def plan_retention(self, sys: SystemContext, now: datetime | None = None) -> RetentionPlan:
        """Dry run: gather facts and return the plan without deleting anything."""
        require_system(sys)
        when = self._now() if now is None else _aware(now, "now")
        with self._engine.connect() as conn:
            return self._plan(conn, when)

    def _plan(self, conn: Connection, now: datetime) -> RetentionPlan:
        facts = [
            SurveyFacts(
                r["tenant_id"],
                r["id"],
                RetentionPolicy(r["retention_kind"], r["retention_days"], r["retention_until"]),
                r["closed_at"],
            )
            for r in conn.execute(
                select(t.surveys).where(t.surveys.c.retention_kind != "none")
            ).mappings()
        ]
        if not facts:
            return RetentionPlan(now=now)
        survey_ids = [f.survey_id for f in facts]
        rows: list[ParticipantRow] = []
        for kind, table in (("response", t.responses), ("session", t.sessions)):
            q = (
                select(table.c.id, table.c.tenant_id, t.versions.c.survey_id)
                .join(
                    t.versions,
                    (t.versions.c.id == table.c.version_id)
                    & (t.versions.c.tenant_id == table.c.tenant_id),
                )
                .where(t.versions.c.survey_id.in_(survey_ids))
            )
            rows += [ParticipantRow(kind, r.id, r.tenant_id, r.survey_id) for r in conn.execute(q)]
        return plan_retention(facts, rows, now)

    def run_retention(self, sys: SystemContext, now: datetime | None = None) -> RetentionPlan:
        """Plan, then delete each survey's rows in its own transaction with an audit entry."""
        sys = require_system(sys)
        when = self._now() if now is None else _aware(now, "now")
        with self._engine.connect() as conn:
            plan = self._plan(conn, when)
        for p in plan.purges:
            with self._tx() as conn:
                n_resp = n_sess = 0
                if p.response_ids:
                    n_resp = conn.execute(
                        delete(t.responses).where(
                            (t.responses.c.tenant_id == p.tenant_id)
                            & t.responses.c.id.in_(p.response_ids)
                        )
                    ).rowcount
                if p.session_ids:
                    n_sess = conn.execute(
                        delete(t.sessions).where(
                            (t.sessions.c.tenant_id == p.tenant_id)
                            & t.sessions.c.id.in_(p.session_ids)
                        )
                    ).rowcount
                self._audit(
                    conn,
                    p.tenant_id,
                    sys.actor,
                    "retention.purge",
                    "survey",
                    p.survey_id,
                    {
                        "due_at": p.due_at.isoformat(),
                        "now": when.isoformat(),
                        "responses_deleted": n_resp,
                        "sessions_deleted": n_sess,
                    },
                )
        return plan

    # -- key rotation (system) -----------------------------------------------------

    def rotate_keys(self, sys: SystemContext) -> int:
        """Re-encrypt every field not under the active key. Returns rows re-encrypted.

        Retire an old key only after this returns 0 for it (``count_by_key``).
        """
        sys = require_system(sys)
        names = {"users": "totp_secret", "sessions": "instance", "responses": "answers"}
        total = 0
        for table, ct_col, kid_col in t.ENCRYPTED_FIELDS:
            ct, kid = table.c[ct_col], table.c[kid_col]
            with self._tx() as conn:
                rows = conn.execute(
                    select(table.c.id, ct, kid).where(ct.is_not(None) & (kid != self._keys.active))
                ).all()
                for row_id, blob, old in rows:
                    aad = aad_for(table.name, names[table.name], row_id)
                    new = self._keys.encrypt(self._keys.decrypt(old, blob, aad), aad)
                    res = conn.execute(
                        update(table)
                        .where((table.c.id == row_id) & (kid == old))
                        .values({ct_col: new.blob, kid_col: new.key_id})
                    )
                    total += res.rowcount
        with self._tx() as conn:
            self._audit(
                conn,
                None,
                sys.actor,
                "keys.rotate",
                detail={"active": self._keys.active, "rows": total},
            )
        return total

    def count_by_key(self, sys: SystemContext) -> dict[str, int]:
        """How many encrypted fields each key id protects (to know when a key can retire)."""
        require_system(sys)
        counts: dict[str, int] = {}
        with self._engine.connect() as conn:
            for table, _ct, kid_col in t.ENCRYPTED_FIELDS:
                kid = table.c[kid_col]
                for key_id, n in conn.execute(
                    select(kid, func.count()).where(kid.is_not(None)).group_by(kid)
                ):
                    counts[key_id] = counts.get(key_id, 0) + n
        return counts
