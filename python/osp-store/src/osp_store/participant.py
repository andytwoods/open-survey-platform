"""Participant runtime persistence (task R2, ``planning/runtime-design.md`` §5).

The atomic primitives behind the session API in ``osp-runtime``: publications,
runtime sessions with a revision counter, conditional snapshot writes, quota and
balanced-assignment counters, submit-once, and the inactivity release job.

Expected outcomes (a stale write, a repeated submit, a full quota) come back as
``status`` values, not exceptions, so ``osp-runtime`` (same layer, cannot import
this package) can act on them. Misuse (bad context, a row in another tenant, bad
input) raises the usual store errors.

Atomicity
- Quotas: ``UPDATE quota_counters SET used = used + 1 WHERE used < cap`` is atomic on
  SQLite and Postgres; the participant row is written first in the same transaction,
  so calls for one session are serialised and a repeat returns the recorded claim.
- Balanced assignment: the counter rows of a variable are locked with a no-op UPDATE
  before they are read, so concurrent starts see each other's increments.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Connection, insert, select, update

from . import schema as t
from .context import SystemContext, TenantContext, require_ctx, require_system
from .crypto import canonical_json
from .errors import Conflict, InvalidInput, NotFound
from .store import Store, _answers, _id, _json, _seed

SaveMode = Literal["every-page", "end-only"]
SAVE_MODES = frozenset({"every-page", "end-only"})

#: ``choose(variable, [(level, count), ...]) -> level`` for balanced assignment.
Chooser = Callable[[str, list[tuple[Any, int]]], Any]


@dataclass(frozen=True, slots=True)
class Publication:
    id: str
    tenant_id: str
    version_id: str
    slug: str
    plan: Any
    plan_checksum: str
    save_mode: SaveMode
    config: Any
    created_at: datetime
    closed_at: datetime | None


@dataclass(frozen=True, slots=True)
class SessionCredential:
    """What the API needs to authenticate a participant call (no participant data)."""

    session_id: str
    tenant_id: str
    token_hash: str
    last_active_at: datetime
    submitted_at: datetime | None
    expired_at: datetime | None


@dataclass(frozen=True, slots=True)
class ParticipantSession:
    id: str
    tenant_id: str
    publication_id: str
    version_id: str
    session_seed: int
    assigned: Any
    save_mode: SaveMode
    revision: int
    snapshot: Any  # decrypted latest acknowledged snapshot, or None
    url_params: Any  # decrypted, or None (always None in end-only mode)
    started_at: datetime
    last_active_at: datetime
    submitted_at: datetime | None
    expired_at: datetime | None
    response_id: str | None


@dataclass(frozen=True, slots=True)
class SnapshotWrite:
    status: Literal["ok", "replay", "stale", "submitted", "expired", "end-only"]
    revision: int
    snapshot: Any = None  # the server copy, for "stale"
    conflict_id: str | None = None


@dataclass(frozen=True, slots=True)
class QuotaClaim:
    status: Literal["ok", "replay", "submitted", "expired"]
    node_id: str
    quota_id: str
    result: Literal["admitted", "full"] | None


@dataclass(frozen=True, slots=True)
class SubmitResult:
    status: Literal["ok", "replay", "mismatch", "expired"]
    response_id: str | None
    submitted_at: datetime | None


@dataclass(frozen=True, slots=True)
class ReleaseReport:
    sessions_expired: int
    quota_slots_released: int
    assignment_slots_released: int


@dataclass(frozen=True, slots=True)
class SnapshotConflict:
    id: str
    base_revision: int
    server_revision: int
    snapshot: Any
    at: datetime


def _key(level: object) -> str:
    key = canonical_json(_json(level, "level"))
    if len(key) > 200:
        raise InvalidInput("level is too long (canonical JSON over 200 characters)")
    return key


def _name(value: object, what: str, limit: int = 200) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise InvalidInput(f"{what} must be a string of 1-{limit} characters")
    return value


class ParticipantStore:
    """Participant-runtime tables, sharing the engine, keyring and clock of a ``Store``."""

    def __init__(self, store: Store) -> None:
        self._s = store

    # -- publications ----------------------------------------------------------------

    def _publication(self, r: Mapping[str, Any]) -> Publication:
        return Publication(
            r["id"],
            r["tenant_id"],
            r["version_id"],
            r["slug"],
            json.loads(r["plan"]),
            r["plan_checksum"],
            r["save_mode"],
            r["config"],
            r["created_at"],
            r["closed_at"],
        )

    def create_publication(
        self,
        ctx: TenantContext,
        version_id: str,
        slug: str,
        plan: object,
        plan_checksum: str,
        save_mode: str,
        config: object,
        *,
        quotas: Mapping[str, int] | None = None,
        balanced: Mapping[str, Sequence[object]] | None = None,
    ) -> Publication:
        """Publish a version under ``slug`` with its runtime plan (opaque JSON).

        ``quotas`` maps quota id -> limit; ``balanced`` maps variable -> levels. Their
        counters start at zero. ``config`` is opaque here (osp-runtime reads it).
        """
        ctx = require_ctx(ctx)
        vid = _id(version_id)
        slug = _name(slug, "slug", 80)
        checksum = _name(plan_checksum, "plan_checksum", 128)
        if save_mode not in SAVE_MODES:
            raise InvalidInput(f"save_mode must be one of {sorted(SAVE_MODES)}")
        plan_text = canonical_json(_json(plan, "plan"))
        config = _json(config, "config")
        pid, now = str(uuid.uuid4()), self._s._now()
        with self._s._tx() as conn:
            survey_id = self._s._one(
                conn, select(t.versions.c.survey_id).where(self._s._version_where(ctx, vid))
            )["survey_id"]
            # A slug belongs to one survey: a republish reuses it, another survey can't.
            owners = conn.execute(
                select(t.versions.c.survey_id)
                .join(t.publications, t.publications.c.version_id == t.versions.c.id)
                .where(t.publications.c.slug == slug)
            ).scalars()
            if any(owner != survey_id for owner in owners):
                raise Conflict("that slug is in use by another survey")
            conn.execute(
                insert(t.publications).values(
                    id=pid,
                    tenant_id=ctx.tenant_id,
                    version_id=vid,
                    slug=slug,
                    plan=plan_text,
                    plan_checksum=checksum,
                    save_mode=save_mode,
                    config=config,
                    published_by=ctx.actor,
                    created_at=now,
                )
            )
            for quota_id, cap in (quotas or {}).items():
                if type(cap) is not int or cap < 0:
                    raise InvalidInput(f"quota {quota_id!r} limit must be a non-negative integer")
                conn.execute(
                    insert(t.quota_counters).values(
                        publication_id=pid,
                        quota_id=_name(quota_id, "quota id"),
                        tenant_id=ctx.tenant_id,
                        cap=cap,
                        used=0,
                    )
                )
            for variable, levels in (balanced or {}).items():
                keys = {_key(level) for level in levels}
                if not keys:
                    raise InvalidInput(f"balanced variable {variable!r} needs levels")
                for key in sorted(keys):
                    conn.execute(
                        insert(t.assignment_counters).values(
                            publication_id=pid,
                            variable=_name(variable, "variable"),
                            level=key,
                            tenant_id=ctx.tenant_id,
                            count=0,
                        )
                    )
            self._s._audit(
                conn,
                ctx.tenant_id,
                ctx.actor,
                "publication.create",
                "publication",
                pid,
                {"version_id": vid, "slug": slug, "save_mode": save_mode},
            )
            return self._publication(
                self._s._one(conn, select(t.publications).where(t.publications.c.id == pid))
            )

    def find_publication(
        self, sys: SystemContext, slug: str, plan_checksum: str | None = None
    ) -> Publication | None:
        """Resolve a public slug (cross-tenant: the slug is what a participant has).

        Without ``plan_checksum``: the publication of the newest version under ``slug``
        (the one new sessions start on). With it: the publication under ``slug`` with
        that plan, so a session started on an older version can still fetch its plan.
        """
        require_system(sys)
        if not isinstance(slug, str) or not slug or len(slug) > 80:
            return None
        q = (
            select(t.publications)
            .join(t.versions, t.versions.c.id == t.publications.c.version_id)
            .where(t.publications.c.slug == slug)
            .order_by(t.versions.c.number.desc(), t.publications.c.created_at.desc())
        )
        if plan_checksum is not None:
            if not isinstance(plan_checksum, str) or len(plan_checksum) > 128:
                return None
            q = q.where(t.publications.c.plan_checksum == plan_checksum)
        with self._s._engine.connect() as conn:
            row = conn.execute(q).mappings().first()
            return None if row is None else self._publication(row)

    def get_publication(self, ctx: TenantContext, publication_id: str) -> Publication:
        ctx = require_ctx(ctx)
        where = (t.publications.c.tenant_id == ctx.tenant_id) & (
            t.publications.c.id == _id(publication_id)
        )
        with self._s._engine.connect() as conn:
            return self._publication(self._s._one(conn, select(t.publications).where(where)))

    def close_publication(self, ctx: TenantContext, publication_id: str) -> None:
        ctx = require_ctx(ctx)
        where = (t.publications.c.tenant_id == ctx.tenant_id) & (
            t.publications.c.id == _id(publication_id)
        )
        with self._s._tx() as conn:
            self._s._one(conn, select(t.publications.c.id).where(where))
            conn.execute(update(t.publications).where(where).values(closed_at=self._s._now()))
            self._s._audit(
                conn, ctx.tenant_id, ctx.actor, "publication.close", "publication", publication_id
            )

    # -- sessions --------------------------------------------------------------------

    def _ps_where(self, ctx: TenantContext, session_id: object) -> Any:
        return (t.participant_sessions.c.tenant_id == ctx.tenant_id) & (
            t.participant_sessions.c.id == _id(session_id)
        )

    def start(
        self,
        ctx: TenantContext,
        publication_id: str,
        session_seed: int,
        assigned: Mapping[str, Any],
        token_hash: str,
        *,
        url_params: object = None,
        balanced: Sequence[str] = (),
        choose: Chooser | None = None,
    ) -> ParticipantSession:
        """Create a session with its seed and assignment, atomically.

        ``assigned`` holds the already-decided (simple random) conditions. Each variable
        in ``balanced`` is decided here under a counter lock by ``choose`` and counted.
        ``url_params`` (None: not stored) is encrypted.
        """
        ctx = require_ctx(ctx)
        pid = _id(publication_id)
        seed = _seed(session_seed)
        conds = dict(_json(dict(assigned), "assigned"))
        token_hash = _name(token_hash, "token_hash", 64)
        if balanced and choose is None:
            raise InvalidInput("balanced assignment needs a chooser")
        sid, now = str(uuid.uuid4()), self._s._now()
        with self._s._tx() as conn:
            pub = self._s._one(
                conn,
                select(t.publications).where(
                    (t.publications.c.tenant_id == ctx.tenant_id) & (t.publications.c.id == pid)
                ),
            )
            counted: dict[str, str] = {}
            c = t.assignment_counters.c
            for variable in balanced:
                mine = (c.publication_id == pid) & (c.variable == variable)
                conn.execute(update(t.assignment_counters).where(mine).values(count=c.count))
                rows = conn.execute(select(c.level, c.count).where(mine).order_by(c.level)).all()
                if not rows:
                    raise InvalidInput(f"no balanced counters for variable {variable!r}")
                level = choose(variable, [(json.loads(lv), n) for lv, n in rows])  # type: ignore[misc]
                key = _key(level)
                if key not in {lv for lv, _ in rows}:
                    raise InvalidInput(f"chooser returned an unknown level for {variable!r}")
                conn.execute(
                    update(t.assignment_counters)
                    .where(mine & (c.level == key))
                    .values(count=c.count + 1)
                )
                conds[variable] = json.loads(key)
                counted[variable] = key
            conn.execute(
                insert(t.sessions).values(
                    id=sid,
                    tenant_id=ctx.tenant_id,
                    version_id=pub["version_id"],
                    session_seed=seed,
                    assigned_conditions=conds,
                    realised_orders={},
                    started_at=now,
                    updated_at=now,
                )
            )
            params_ct = params_kid = None
            if url_params is not None:
                params_ct, params_kid = self._s._enc(
                    _json(url_params, "url_params"), "participant_sessions", "url_params", sid
                )
            conn.execute(
                insert(t.participant_sessions).values(
                    id=sid,
                    tenant_id=ctx.tenant_id,
                    publication_id=pid,
                    token_hash=token_hash,
                    revision=0,
                    save_mode=pub["save_mode"],
                    balanced=counted,
                    url_params_ct=params_ct,
                    url_params_key_id=params_kid,
                    last_active_at=now,
                )
            )
            return self._get(conn, ctx, sid)

    def _get(self, conn: Connection, ctx: TenantContext, session_id: str) -> ParticipantSession:
        ps, s = t.participant_sessions, t.sessions
        r = self._s._one(
            conn,
            select(ps, s.c.version_id, s.c.session_seed, s.c.assigned_conditions)
            .add_columns(s.c.instance_ct, s.c.instance_key_id, s.c.started_at)
            .join(s, (s.c.id == ps.c.id) & (s.c.tenant_id == ps.c.tenant_id))
            .where(self._ps_where(ctx, session_id)),
        )
        snapshot = url_params = None
        if r["instance_ct"] is not None:
            snapshot = self._s._dec(
                r["instance_ct"], r["instance_key_id"], "sessions", "instance", r["id"]
            )
        if r["url_params_ct"] is not None:
            url_params = self._s._dec(
                r["url_params_ct"],
                r["url_params_key_id"],
                "participant_sessions",
                "url_params",
                r["id"],
            )
        return ParticipantSession(
            r["id"],
            r["tenant_id"],
            r["publication_id"],
            r["version_id"],
            r["session_seed"],
            r["assigned_conditions"],
            r["save_mode"],
            r["revision"],
            snapshot,
            url_params,
            r["started_at"],
            r["last_active_at"],
            r["submitted_at"],
            r["expired_at"],
            r["response_id"],
        )

    def get(self, ctx: TenantContext, session_id: str) -> ParticipantSession:
        ctx = require_ctx(ctx)
        with self._s._engine.connect() as conn:
            return self._get(conn, ctx, session_id)

    def _credential(self, where: Any) -> SessionCredential | None:
        ps = t.participant_sessions.c
        with self._s._engine.connect() as conn:
            r = conn.execute(
                select(
                    ps.id,
                    ps.tenant_id,
                    ps.token_hash,
                    ps.last_active_at,
                    ps.submitted_at,
                    ps.expired_at,
                ).where(where)
            ).first()
        return None if r is None else SessionCredential(*r)

    def credential_by_token(self, sys: SystemContext, token_hash: str) -> SessionCredential | None:
        """Look a session up by its token hash (cross-tenant: the token is the credential)."""
        require_system(sys)
        if not isinstance(token_hash, str) or len(token_hash) != 64:
            return None
        return self._credential(t.participant_sessions.c.token_hash == token_hash)

    def credential(self, sys: SystemContext, session_id: str) -> SessionCredential | None:
        require_system(sys)
        if not isinstance(session_id, str) or not session_id or len(session_id) > 36:
            return None
        return self._credential(t.participant_sessions.c.id == session_id)

    def _live(self, ctx: TenantContext, session_id: str) -> Any:
        ps = t.participant_sessions.c
        return self._ps_where(ctx, session_id) & ps.submitted_at.is_(None) & ps.expired_at.is_(None)

    def touch(self, ctx: TenantContext, session_id: str) -> bool:
        """Record activity on a live session (resume). False if submitted or expired."""
        ctx = require_ctx(ctx)
        with self._s._tx() as conn:
            n = conn.execute(
                update(t.participant_sessions)
                .where(self._live(ctx, session_id))
                .values(last_active_at=self._s._now())
            ).rowcount
        return n == 1

    def write_snapshot(
        self, ctx: TenantContext, session_id: str, base_revision: int, snapshot: object
    ) -> SnapshotWrite:
        """Conditional write: accepted only if ``base_revision`` is the current revision.

        A retry of the last accepted write (same content, base = current - 1) is a
        ``replay``. Any other stale write keeps the server copy and stores the losing
        snapshot in ``session_conflicts`` (decision R-2).
        """
        ctx = require_ctx(ctx)
        sid = _id(session_id)
        if type(base_revision) is not int or base_revision < 0:
            raise InvalidInput("baseRevision must be a non-negative integer")
        body = _json(snapshot, "snapshot")
        ps = t.participant_sessions.c
        now = self._s._now()
        with self._s._tx() as conn:
            n = conn.execute(
                update(t.participant_sessions)
                .where(
                    self._live(ctx, sid)
                    & (ps.save_mode == "every-page")
                    & (ps.revision == base_revision)
                )
                .values(revision=ps.revision + 1, last_active_at=now)
            ).rowcount
            if n == 1:
                blob, kid = self._s._enc(body, "sessions", "instance", sid)
                conn.execute(
                    update(t.sessions)
                    .where(self._s._session_where(ctx, sid))
                    .values(instance_ct=blob, instance_key_id=kid, updated_at=now)
                )
                return SnapshotWrite("ok", base_revision + 1)
            cur = self._get(conn, ctx, sid)  # NotFound for another tenant's session
            if cur.submitted_at is not None:
                return SnapshotWrite("submitted", cur.revision)
            if cur.expired_at is not None:
                return SnapshotWrite("expired", cur.revision)
            if cur.save_mode != "every-page":
                return SnapshotWrite("end-only", cur.revision)
            if base_revision == cur.revision - 1 and canonical_json(body) == canonical_json(
                cur.snapshot
            ):
                return SnapshotWrite("replay", cur.revision)
            cid = str(uuid.uuid4())
            blob, kid = self._s._enc(body, "session_conflicts", "snapshot", cid)
            conn.execute(
                insert(t.session_conflicts).values(
                    id=cid,
                    tenant_id=ctx.tenant_id,
                    session_id=sid,
                    base_revision=base_revision,
                    server_revision=cur.revision,
                    snapshot_ct=blob,
                    snapshot_key_id=kid,
                    at=now,
                )
            )
            self._s._audit(
                conn,
                ctx.tenant_id,
                ctx.actor,
                "session.snapshot_conflict",
                "session",
                sid,
                {"base": base_revision, "server": cur.revision, "conflict_id": cid},
            )
            return SnapshotWrite("stale", cur.revision, cur.snapshot, cid)

    def list_conflicts(self, ctx: TenantContext, session_id: str) -> list[SnapshotConflict]:
        ctx = require_ctx(ctx)
        c = t.session_conflicts.c
        with self._s._engine.connect() as conn:
            rows = conn.execute(
                select(t.session_conflicts)
                .where((c.tenant_id == ctx.tenant_id) & (c.session_id == _id(session_id)))
                .order_by(c.at, c.id)
            ).mappings()
            return [
                SnapshotConflict(
                    r["id"],
                    r["base_revision"],
                    r["server_revision"],
                    self._s._dec(
                        r["snapshot_ct"],
                        r["snapshot_key_id"],
                        "session_conflicts",
                        "snapshot",
                        r["id"],
                    ),
                    r["at"],
                )
                for r in rows
            ]

    # -- quotas ----------------------------------------------------------------------

    def claim_quota(
        self, ctx: TenantContext, session_id: str, node_id: str, quota_id: str
    ) -> QuotaClaim:
        """Atomic and idempotent per (session, node): a repeat returns the recorded result."""
        ctx = require_ctx(ctx)
        sid = _id(session_id)
        node_id = _name(node_id, "node id")
        quota_id = _name(quota_id, "quota id")
        now = self._s._now()
        qc, cl = t.quota_counters.c, t.quota_claims.c
        with self._s._tx() as conn:
            # First write: serialises calls for this session (row lock / SQLite write lock).
            n = conn.execute(
                update(t.participant_sessions)
                .where(self._live(ctx, sid))
                .values(last_active_at=now)
            ).rowcount
            if n == 0:
                cur = self._get(conn, ctx, sid)
                status = "submitted" if cur.submitted_at is not None else "expired"
                return QuotaClaim(status, node_id, quota_id, None)
            prior = conn.execute(
                select(cl.quota_id, cl.result).where(
                    (cl.session_id == sid) & (cl.node_id == node_id)
                )
            ).first()
            if prior is not None:
                return QuotaClaim("replay", node_id, prior.quota_id, prior.result)
            pub_id = conn.execute(
                select(t.participant_sessions.c.publication_id).where(self._ps_where(ctx, sid))
            ).scalar_one()
            mine = (qc.publication_id == pub_id) & (qc.quota_id == quota_id)
            if conn.execute(select(qc.cap).where(mine)).first() is None:
                raise NotFound(f"no quota {quota_id!r} in this publication")
            got = conn.execute(
                update(t.quota_counters).where(mine & (qc.used < qc.cap)).values(used=qc.used + 1)
            ).rowcount
            result = "admitted" if got == 1 else "full"
            conn.execute(
                insert(t.quota_claims).values(
                    session_id=sid,
                    node_id=node_id,
                    tenant_id=ctx.tenant_id,
                    publication_id=pub_id,
                    quota_id=quota_id,
                    result=result,
                    at=now,
                )
            )
            return QuotaClaim("ok", node_id, quota_id, result)

    def quota_usage(self, ctx: TenantContext, publication_id: str) -> dict[str, tuple[int, int]]:
        """``{quota_id: (used, cap)}``."""
        ctx = require_ctx(ctx)
        qc = t.quota_counters.c
        with self._s._engine.connect() as conn:
            rows = conn.execute(
                select(qc.quota_id, qc.used, qc.cap).where(
                    (qc.tenant_id == ctx.tenant_id) & (qc.publication_id == _id(publication_id))
                )
            ).all()
        return {q: (u, c) for q, u, c in rows}

    def assignment_counts(self, ctx: TenantContext, publication_id: str) -> dict[str, dict]:
        """``{variable: {level: count}}`` for balanced variables."""
        ctx = require_ctx(ctx)
        c = t.assignment_counters.c
        with self._s._engine.connect() as conn:
            rows = conn.execute(
                select(c.variable, c.level, c.count).where(
                    (c.tenant_id == ctx.tenant_id) & (c.publication_id == _id(publication_id))
                )
            ).all()
        out: dict[str, dict] = {}
        for variable, level, count in rows:
            out.setdefault(variable, {})[json.loads(level)] = count
        return out

    # -- submit ----------------------------------------------------------------------

    def submit(
        self,
        ctx: TenantContext,
        session_id: str,
        *,
        answers: Mapping[str, Mapping[str, Any]],
        record: object,
        record_checksum: str,
        realised_orders: object,
        engine_version: str | None,
    ) -> SubmitResult:
        """Store the response once. A repeat with the same ``record_checksum`` is a
        ``replay`` of the first; a different payload is a ``mismatch``. After this,
        snapshots for the session are rejected and its server snapshot is cleared."""
        ctx = require_ctx(ctx)
        sid = _id(session_id)
        ans = _answers(answers)
        rec = _json(record, "record")
        orders = _json(realised_orders, "realised_orders")
        record_checksum = _name(record_checksum, "record_checksum", 64)
        if engine_version is not None:
            engine_version = _name(engine_version, "engine_version", 64)
        rid, now = str(uuid.uuid4()), self._s._now()
        with self._s._tx() as conn:
            n = conn.execute(
                update(t.participant_sessions)
                .where(self._live(ctx, sid))
                .values(
                    submitted_at=now,
                    last_active_at=now,
                    response_id=rid,
                    submission_checksum=record_checksum,
                )
            ).rowcount
            if n == 0:
                ps = t.participant_sessions.c
                cur = self._s._one(
                    conn,
                    select(ps.submitted_at, ps.response_id, ps.submission_checksum).where(
                        self._ps_where(ctx, sid)
                    ),
                )
                if cur["submitted_at"] is None:
                    return SubmitResult("expired", None, None)
                same = cur["submission_checksum"] == record_checksum
                return SubmitResult(
                    "replay" if same else "mismatch", cur["response_id"], cur["submitted_at"]
                )
            srow = self._s._one(conn, select(t.sessions).where(self._s._session_where(ctx, sid)))
            vrow = self._s._one(
                conn,
                select(t.versions.c.checksum).where(
                    self._s._version_where(ctx, srow["version_id"])
                ),
            )
            blob, kid = self._s._enc(ans, "responses", "answers", rid)
            conn.execute(
                insert(t.responses).values(
                    id=rid,
                    tenant_id=ctx.tenant_id,
                    version_id=srow["version_id"],
                    version_checksum=vrow["checksum"],
                    session_id=sid,
                    allocation_mode="server",
                    session_seed=srow["session_seed"],
                    assigned_conditions=srow["assigned_conditions"],
                    realised_orders=orders,
                    engine_version=engine_version,
                    answers_ct=blob,
                    answers_key_id=kid,
                    started_at=srow["started_at"],
                    submitted_at=now,
                )
            )
            blob, kid = self._s._enc(rec, "response_records", "record", rid)
            conn.execute(
                insert(t.response_records).values(
                    id=rid, tenant_id=ctx.tenant_id, record_ct=blob, record_key_id=kid
                )
            )
            conn.execute(
                update(t.sessions)
                .where(self._s._session_where(ctx, sid))
                .values(
                    completed_at=now,
                    updated_at=now,
                    instance_ct=None,
                    instance_key_id=None,
                )
            )
            self._s._audit(
                conn, ctx.tenant_id, ctx.actor, "response.submit", "response", rid, {"session": sid}
            )
            return SubmitResult("ok", rid, now)

    def get_record(self, ctx: TenantContext, response_id: str) -> Any:
        """The full submitted ResponseRecord (decrypted); audited like a response read."""
        ctx = require_ctx(ctx)
        rr = t.response_records.c
        with self._s._tx() as conn:
            r = self._s._one(
                conn,
                select(t.response_records).where(
                    (rr.tenant_id == ctx.tenant_id) & (rr.id == _id(response_id))
                ),
            )
            self._s._audit(conn, ctx.tenant_id, ctx.actor, "response.read", "response", r["id"])
        return self._s._dec(
            r["record_ct"], r["record_key_id"], "response_records", "record", r["id"]
        )

    # -- inactivity release (decision R-3) -------------------------------------------

    def release_inactive(self, sys: SystemContext, cutoff: datetime) -> ReleaseReport:
        """Expire every unsubmitted session idle since ``cutoff`` or earlier, and give back
        its quota slots and balanced-assignment counts. Re-running is a no-op."""
        sys = require_system(sys)
        if not isinstance(cutoff, datetime) or cutoff.tzinfo is None:
            raise InvalidInput("cutoff must be a timezone-aware datetime")
        ps, cl = t.participant_sessions.c, t.quota_claims.c
        idle = ps.submitted_at.is_(None) & ps.expired_at.is_(None) & (ps.last_active_at <= cutoff)
        with self._s._engine.connect() as conn:
            candidates = conn.execute(select(ps.id, ps.tenant_id).where(idle)).all()
        expired = quota = assignment = 0
        for sid, tenant_id in candidates:
            now = self._s._now()
            with self._s._tx() as conn:
                n = conn.execute(
                    update(t.participant_sessions)
                    .where((ps.id == sid) & idle)
                    .values(expired_at=now)
                ).rowcount
                if n == 0:
                    continue  # became active, or another job got it
                expired += 1
                row = conn.execute(select(ps.publication_id, ps.balanced).where(ps.id == sid)).one()
                claims = conn.execute(
                    select(cl.node_id, cl.quota_id).where(
                        (cl.session_id == sid)
                        & (cl.result == "admitted")
                        & cl.released_at.is_(None)
                    )
                ).all()
                qc = t.quota_counters.c
                for node_id, quota_id in claims:
                    conn.execute(
                        update(t.quota_counters)
                        .where(
                            (qc.publication_id == row.publication_id)
                            & (qc.quota_id == quota_id)
                            & (qc.used > 0)
                        )
                        .values(used=qc.used - 1)
                    )
                    conn.execute(
                        update(t.quota_claims)
                        .where((cl.session_id == sid) & (cl.node_id == node_id))
                        .values(released_at=now)
                    )
                    quota += 1
                ac = t.assignment_counters.c
                for variable, key in (row.balanced or {}).items():
                    assignment += conn.execute(
                        update(t.assignment_counters)
                        .where(
                            (ac.publication_id == row.publication_id)
                            & (ac.variable == variable)
                            & (ac.level == key)
                            & (ac.count > 0)
                        )
                        .values(count=ac.count - 1)
                    ).rowcount
                self._s._audit(
                    conn,
                    tenant_id,
                    sys.actor,
                    "session.expire",
                    "session",
                    sid,
                    {"quota_released": len(claims)},
                )
        return ReleaseReport(expired, quota, assignment)
