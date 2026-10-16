"""The participant session service (``planning/runtime-design.md`` §5, decisions R-2, R-3).

The server only saves data and counts across participants. This module decides
*what* to store; the atomic writes are the repository's job (``osp-store``'s
``ParticipantStore``, adapted in ``osp-api``, since packages in one layer may not
import each other).

- **Start**: a ``sessionSeed`` from the CSPRNG (1 … 2^53 − 1); simple random
  assignment from ``osp_engine.random.assign`` with ``node_seed``; balanced
  assignment under the store's counter lock. Seed and assignment are stored
  before the reply. URL parameters are stored (encrypted) only in ``every-page``.
- **Resume token**: 256 random bits; only its SHA-256 is stored. It authenticates
  every session call and stops working after ``resume_expiry`` without activity
  (default 30 days; per survey ``RuntimeConfig.resumeExpiryDays``; decision S-1).
- **Snapshot**: conditional on ``baseRevision``; stale → :class:`StaleRevision` with
  the server copy (the server copy wins; the loser is kept, R-2).
- **Quota**: idempotent per (session, node); a place is held when admitted, used up on
  completion, and released by :meth:`SessionService.release_inactive` after
  ``release_after`` (24 h) idle (R-3, C3a-3). This is a separate timer from the token:
  a session whose holds were released can still resume, and then takes its places
  again if they are free (the store does this atomically).
- **Submit**: idempotent on the session; validates shape, plan checksum, assignment.
  Accepted even after the token's expiry or after the holds were released: such a
  submit is flagged ``late`` (``SubmitAck.late`` and ``server.late`` in the stored
  record) and is not counted toward quotas (decision S-2). A retry with identical data
  returns the original success; different data is :class:`SubmitMismatch` (S-4).
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from osp_engine.random import MAX_SEED, assign, node_seed

from .config import RuntimeConfig, SaveMode
from .errors import (
    InvalidPayload,
    InvalidToken,
    NotFoundError,
    PayloadTooLarge,
    RateLimited,
    SaveModeForbidden,
    SessionExpired,
    SessionSubmitted,
    StaleRevision,
    SubmitMismatch,
    SurveyClosed,
)
from .limiter import TokenBucket
from .ports import Clock, RandomSource, SystemRandom, system_clock

TOKEN_BYTES = 32
ANSWER_STATES = frozenset({"answered", "unanswered", "irrelevant", "not-reached"})  # semantics §1


# -- repository port (implemented by osp-store's ParticipantStore via osp-api) -------


class PublicationRow(Protocol):
    id: str
    tenant_id: str
    slug: str
    plan: Any
    plan_checksum: str
    save_mode: str
    config: Any
    closed_at: datetime | None


class CredentialRow(Protocol):
    session_id: str
    tenant_id: str
    last_active_at: datetime
    submitted_at: datetime | None
    expired_at: datetime | None  # holds released (not the token's expiry)
    publication_id: str


class SessionRow(Protocol):
    id: str
    publication_id: str
    session_seed: int
    assigned: Any
    save_mode: str
    revision: int
    snapshot: Any
    submitted_at: datetime | None


class ParticipantRepo(Protocol):
    """Tenant-scoped persistence. ``tenant_id`` always comes from a verified credential
    or a resolved slug, never from the client."""

    def create_publication(
        self,
        tenant_id: str,
        actor: str,
        version_id: str,
        slug: str,
        plan: object,
        plan_checksum: str,
        save_mode: str,
        config: object,
        quotas: Mapping[str, int],
        balanced: Mapping[str, tuple[Any, ...]],
    ) -> PublicationRow: ...
    def find_publication(self, slug: str) -> PublicationRow | None: ...
    def get_publication(self, tenant_id: str, publication_id: str) -> PublicationRow: ...
    def start(
        self,
        tenant_id: str,
        publication_id: str,
        session_seed: int,
        assigned: Mapping[str, Any],
        token_hash: str,
        url_params: object,
        balanced: tuple[str, ...],
        choose: Any,
    ) -> SessionRow: ...
    def credential_by_token(self, token_hash: str) -> CredentialRow | None: ...
    def get(self, tenant_id: str, session_id: str) -> SessionRow: ...
    def touch(self, tenant_id: str, session_id: str) -> bool: ...
    def write_snapshot(
        self, tenant_id: str, session_id: str, base_revision: int, snapshot: object
    ) -> Any: ...
    def claim_quota(self, tenant_id: str, session_id: str, node_id: str, quota_id: str) -> Any: ...
    def submit(
        self,
        tenant_id: str,
        session_id: str,
        answers: Mapping[str, Any],
        record: object,
        record_checksum: str,
        realised_orders: object,
        engine_version: str | None,
        late: bool = False,
    ) -> Any: ...
    def release_inactive(self, cutoff: datetime) -> Any: ...


# -- results ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Started:
    session_id: str
    resume_token: str
    session_seed: int
    assigned: dict[str, Any]
    slug: str
    plan_checksum: str
    save_mode: SaveMode
    revision: int = 0


@dataclass(frozen=True, slots=True)
class SnapshotAck:
    revision: int
    replay: bool = False


@dataclass(frozen=True, slots=True)
class QuotaOutcome:
    node_id: str
    result: str  # "admitted" | "full"
    replay: bool


@dataclass(frozen=True, slots=True)
class SubmitAck:
    response_id: str
    submitted_at: datetime
    replay: bool
    late: bool = False


@dataclass(frozen=True, slots=True)
class Resumed:
    session_id: str
    revision: int
    snapshot: Any
    session_seed: int
    assigned: Any
    slug: str
    plan_checksum: str
    save_mode: str
    submitted: bool


@dataclass(frozen=True)
class SessionPolicy:
    resume_expiry: timedelta = timedelta(days=30)  # token stops working (S-1)
    release_after: timedelta = timedelta(hours=24)  # quota / balanced slots back (R-3)
    max_snapshot_bytes: int = 2_000_000
    max_record_bytes: int = 5_000_000
    max_url_params: int = 50
    max_url_param_chars: int = 1000


def canonical_json(value: object) -> str:
    """Sorted keys, no whitespace, no NaN (the same rule as osp-store)."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _size(value: object, limit: int, what: str) -> str:
    try:
        text = canonical_json(value)
    except (TypeError, ValueError, RecursionError) as exc:
        raise InvalidPayload(f"{what} is not JSON: {exc}") from exc
    if len(text.encode("utf-8")) > limit:
        raise PayloadTooLarge(f"{what} is larger than {limit} bytes")
    return text


class SessionService:
    def __init__(
        self,
        repo: ParticipantRepo,
        *,
        clock: Clock = system_clock,
        rng: RandomSource | None = None,
        policy: SessionPolicy | None = None,
        start_limiter: TokenBucket | None = None,
        resume_limiter: TokenBucket | None = None,
    ) -> None:
        self._repo = repo
        self._clock = clock
        self._rng = rng or SystemRandom()
        self.policy = policy or SessionPolicy()
        # Defaults: bursts of 30 starts per survey link, refilling 5 a second, and 10
        # per client, refilling one every 6 s.
        self._start_limiter = start_limiter or TokenBucket(30, 5, clock)
        self._client_limiter = TokenBucket(10, 1 / 6, clock)
        self._resume_limiter = resume_limiter or TokenBucket(20, 1, clock)

    # -- publish (researcher side; auth is the caller's job) -------------------------

    def publish(
        self,
        tenant_id: str,
        actor: str,
        version_id: str,
        slug: str,
        plan: object,
        config: object,
    ) -> PublicationRow:
        """Make ``version_id`` startable at ``/s/{slug}``. ``plan`` is the runtime plan
        (opaque JSON with a ``checksum``); ``config`` a :class:`RuntimeConfig` JSON."""
        if not isinstance(plan, dict) or not isinstance(plan.get("checksum"), str):
            raise InvalidPayload("the runtime plan must be an object with a string checksum")
        cfg = RuntimeConfig.from_json(config)
        return self._repo.create_publication(
            tenant_id,
            actor,
            version_id,
            slug,
            plan,
            plan["checksum"],
            cfg.save_mode,
            cfg.to_json(),
            cfg.quota_limits,
            cfg.balanced,
        )

    def plan(self, slug: str, checksum: str) -> Any:
        pub = self._repo.find_publication(slug)
        if pub is None or pub.plan_checksum != checksum:
            raise NotFoundError("no such plan")
        return pub.plan

    # -- start -----------------------------------------------------------------------

    def _url_params(self, raw: object) -> dict[str, str]:
        if raw is None:
            return {}
        p = self.policy
        if not isinstance(raw, Mapping) or len(raw) > p.max_url_params:
            raise InvalidPayload(f"urlParams must be an object of at most {p.max_url_params} keys")
        out: dict[str, str] = {}
        for k, v in raw.items():
            if not isinstance(k, str) or not k or len(k) > 100:
                raise InvalidPayload("urlParams keys must be strings of 1-100 characters")
            if not isinstance(v, str) or len(v) > p.max_url_param_chars:
                raise InvalidPayload(
                    f"urlParams values must be strings of at most {p.max_url_param_chars} chars"
                )
            out[k] = v
        return out

    def start(self, slug: str, url_params: object = None, client_key: str | None = None) -> Started:
        if not self._start_limiter.allow(f"slug:{slug}") or (
            client_key is not None and not self._client_limiter.allow(f"client:{client_key}")
        ):
            raise RateLimited("too many new sessions; try again shortly")
        pub = self._repo.find_publication(slug)
        if pub is None:
            raise NotFoundError("no such survey")
        if pub.closed_at is not None:
            raise SurveyClosed("this survey is closed")
        cfg = RuntimeConfig.from_json(pub.config)
        params = self._url_params(url_params)
        seed = self._rng.randbelow(MAX_SEED) + 1  # 1 .. 2**53 - 1, server-side CSPRNG
        assigned: dict[str, Any] = {}
        seed_nodes: dict[str, str] = {}
        for a in cfg.assignments:
            seed_nodes[a.variable] = a.seed_node
            if a.method == "simple":
                assigned[a.variable] = assign(
                    list(a.levels), a.weights, node_seed(cfg.survey_version, seed, a.seed_node)
                )

        def choose(variable: str, counts: list[tuple[Any, int]]) -> Any:
            # Least-filled level; ties broken by the session's own seeded draw.
            low = min(n for _, n in counts)
            tied = [lv for lv, n in counts if n == low]
            return assign(tied, None, node_seed(cfg.survey_version, seed, seed_nodes[variable]))

        token = base64.urlsafe_b64encode(self._rng.token_bytes(TOKEN_BYTES)).decode().rstrip("=")
        row = self._repo.start(
            pub.tenant_id,
            pub.id,
            seed,
            assigned,
            hash_token(token),
            # end-only: no response data before submit, URL parameters included (§5.0).
            params if cfg.save_mode == "every-page" else None,
            tuple(cfg.balanced),
            choose,
        )
        return Started(
            row.id,
            token,
            seed,
            dict(row.assigned),
            pub.slug,
            pub.plan_checksum,
            cfg.save_mode,
            row.revision,
        )

    # -- authentication --------------------------------------------------------------

    def _token_expired(self, cred: CredentialRow) -> bool:
        """The resume token has been idle for its survey's resume expiry (S-1)."""
        expiry = self.policy.resume_expiry
        pub = self._repo.get_publication(cred.tenant_id, cred.publication_id)
        days = RuntimeConfig.from_json(pub.config).resume_expiry_days
        if days is not None:
            expiry = timedelta(days=days)
        return self._clock() - cred.last_active_at >= expiry

    def _auth(
        self, token: object, session_id: str | None = None, *, allow_expired: bool = False
    ) -> CredentialRow:
        if not isinstance(token, str) or not token or len(token) > 256:
            raise InvalidToken("a resume token is required")
        cred = self._repo.credential_by_token(hash_token(token))
        if cred is None or (session_id is not None and cred.session_id != session_id):
            raise InvalidToken("invalid resume token")
        if not allow_expired and cred.submitted_at is None and self._token_expired(cred):
            raise SessionExpired("this session expired after inactivity")
        return cred

    # -- snapshot --------------------------------------------------------------------

    def save_snapshot(
        self, session_id: str, token: object, base_revision: object, snapshot: object
    ) -> SnapshotAck:
        cred = self._auth(token, session_id)
        if isinstance(base_revision, bool) or not isinstance(base_revision, int):
            raise InvalidPayload("baseRevision must be an integer")
        if base_revision < 0:
            raise InvalidPayload("baseRevision must be >= 0")
        _size(snapshot, self.policy.max_snapshot_bytes, "snapshot")
        w = self._repo.write_snapshot(cred.tenant_id, session_id, base_revision, snapshot)
        match w.status:
            case "ok" | "replay":
                return SnapshotAck(w.revision, w.status == "replay")
            case "stale":
                raise StaleRevision(w.revision, w.snapshot)
            case "submitted":
                raise SessionSubmitted("this session was submitted; snapshots are closed")
            case "end-only":
                raise SaveModeForbidden("this survey saves only at the end (end-only mode)")
            case _:
                raise SessionExpired("this session expired after inactivity")

    # -- quota -----------------------------------------------------------------------

    def check_quota(self, session_id: str, token: object, node_id: str) -> QuotaOutcome:
        cred = self._auth(token, session_id)
        if cred.submitted_at is not None:
            raise SessionSubmitted("this session was submitted")
        sess = self._repo.get(cred.tenant_id, session_id)
        pub = self._repo.get_publication(cred.tenant_id, sess.publication_id)
        q = RuntimeConfig.from_json(pub.config).quota_by_node.get(node_id)
        if q is None:
            raise NotFoundError(f"no quotaCheck node {node_id!r} in this survey")
        c = self._repo.claim_quota(cred.tenant_id, session_id, node_id, q.quota)
        match c.status:
            case "ok" | "replay":
                return QuotaOutcome(node_id, c.result, c.status == "replay")
            case "submitted":
                raise SessionSubmitted("this session was submitted")
            case _:
                raise SessionExpired("this session expired after inactivity")

    # -- submit ----------------------------------------------------------------------

    def submit(self, session_id: str, token: object, record: object) -> SubmitAck:
        # Late submits are accepted (decision S-2): rejecting them lost data.
        cred = self._auth(token, session_id, allow_expired=True)
        late = cred.submitted_at is None and (
            cred.expired_at is not None or self._token_expired(cred)
        )
        text = _size(record, self.policy.max_record_bytes, "record")
        sess = self._repo.get(cred.tenant_id, session_id)
        pub = self._repo.get_publication(cred.tenant_id, sess.publication_id)
        answers, orders, engine_version = validate_record(record, sess, pub)
        stored = {
            "record": record,
            "server": {
                "saveMode": sess.save_mode,
                "allocationMode": "server",
                "sessionSeed": sess.session_seed,
                "assigned": sess.assigned,
                "planChecksum": pub.plan_checksum,
                "late": late,  # the store sets the final value
            },
        }
        r = self._repo.submit(
            cred.tenant_id,
            session_id,
            answers,
            stored,
            hashlib.sha256(text.encode("utf-8")).hexdigest(),
            orders,
            engine_version,
            late=late,
        )
        match r.status:
            case "ok" | "replay":
                return SubmitAck(r.response_id, r.submitted_at, r.status == "replay", bool(r.late))
            case "mismatch":
                raise SubmitMismatch("this session was already submitted with different data")
            case _:
                raise SessionExpired("this session expired after inactivity")

    # -- resume ----------------------------------------------------------------------

    def resume(self, token: object, client_key: str | None = None) -> Resumed:
        if client_key is not None and not self._resume_limiter.allow(f"client:{client_key}"):
            raise RateLimited("too many resume attempts; try again shortly")
        cred = self._auth(token)
        if cred.submitted_at is None:
            self._repo.touch(cred.tenant_id, cred.session_id)
        sess = self._repo.get(cred.tenant_id, cred.session_id)
        pub = self._repo.get_publication(cred.tenant_id, sess.publication_id)
        return Resumed(
            sess.id,
            sess.revision,
            sess.snapshot,
            sess.session_seed,
            sess.assigned,
            pub.slug,
            pub.plan_checksum,
            sess.save_mode,
            sess.submitted_at is not None,
        )

    # -- release job (decision R-3) --------------------------------------------------

    def release_inactive(self) -> Any:
        """Run periodically: release the quota places and balanced-assignment counts of
        sessions idle for ``release_after``. Their resume tokens keep working until
        ``resume_expiry``; resuming takes the places again if they are free."""
        return self._repo.release_inactive(self._clock() - self.policy.release_after)


def validate_record(
    record: object, sess: SessionRow, pub: PublicationRow
) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    """Check a submitted ResponseRecord against its session. Returns answers, realised
    orders and engine version (the columns the store keeps outside the record).

    Required: ``sessionId``, ``planChecksum``, ``assigned``, ``answers`` (``{var: {state,
    value}}``, semantics §1). Optional: ``orders`` (object), ``events`` (list),
    ``engineVersion`` (string). Other fields are kept as given.
    """
    if not isinstance(record, dict):
        raise InvalidPayload("the record must be an object")
    if record.get("sessionId") != sess.id:
        raise InvalidPayload("record.sessionId does not match this session", "submit.session")
    if record.get("planChecksum") != pub.plan_checksum:
        raise InvalidPayload("planChecksum does not match the published plan", "submit.plan")
    if canonical_json(record.get("assigned")) != canonical_json(sess.assigned):
        raise InvalidPayload("assigned conditions do not match the session", "submit.assignment")
    answers = record.get("answers")
    if not isinstance(answers, dict):
        raise InvalidPayload("answers must be an object of {var: {state, value}}")
    for var, ans in answers.items():
        if not isinstance(ans, dict) or ans.get("state") not in ANSWER_STATES:
            raise InvalidPayload(f"answer {var!r} needs a state in {sorted(ANSWER_STATES)}")
        if ans["state"] != "answered" and ans.get("value") is not None:
            raise InvalidPayload(f"answer {var!r} is {ans['state']} so its value must be null")
    orders = record.get("orders", {})
    if not isinstance(orders, dict):
        raise InvalidPayload("orders must be an object")
    if not isinstance(record.get("events", []), list):
        raise InvalidPayload("events must be a list")
    engine = record.get("engineVersion")
    if engine is not None and (not isinstance(engine, str) or not engine or len(engine) > 64):
        raise InvalidPayload("engineVersion must be a string of at most 64 characters")
    return answers, orders, engine
