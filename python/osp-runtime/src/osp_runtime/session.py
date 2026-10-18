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
  the server copy (the server copy wins; the loser is kept, R-2). A late save whose
  event log is a prefix of the server copy's (a dead page catching up) is not a
  conflict: it is acknowledged as ``superseded`` and nothing is written. A save whose
  event log strictly extends the server copy's (a *fast-forward*) is written whatever its
  base: it holds everything the server has and more, so nothing is overwritten. This is
  what keeps a refresh straight after typing from losing answers when the dead page's two
  keepalive saves arrive out of order (decision R9-1, semantics.md §5).
- **Quota**: idempotent per (session, node); the result uses the engine's words,
  ``open`` or ``full``. A place is held when open, used up on
  completion, and released by :meth:`SessionService.release_inactive` after
  ``release_after`` (24 h) idle (R-3, C3a-3). This is a separate timer from the token:
  a session whose holds were released can still resume, and then takes its places
  again if they are free (the store does this atomically).
- **Consent** (semantics.md §11): for a survey with a consent page, no URL parameters are
  stored at start, and snapshots, quota checks and submits are refused
  (:class:`ConsentRequired`) until the session agreed to the plan's consent version. A
  decline deletes the session and keeps at most an anonymous count; a withdrawal
  (after agreeing, before or after submit) deletes session and response, audited
  without answer data.
- **Submit**: idempotent on the session; validates shape, plan checksum, assignment.
  Accepted even after the token's expiry or after the holds were released: such a
  submit is flagged ``late`` (``SubmitAck.late`` and ``server.late`` in the stored
  record) and is not counted toward quotas (decision S-2). A retry with identical data
  returns the original success; different data is :class:`SubmitMismatch` (S-4).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from osp_engine.random import MAX_SEED, assign, node_seed

from .config import RuntimeConfig, SaveMode
from .errors import (
    ConsentRequired,
    ExternalTokenExpired,
    ExternalTokenInvalid,
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
LocalCopy = Literal["browser", "memory"]
QuotaResult = Literal["open", "full"]
#: Store / older-contract words for a quota result -> the engine's (``open`` | ``full``).
_QUOTA_RESULT: dict[str, QuotaResult] = {"open": "open", "admitted": "open", "full": "full"}
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
    consented_at: datetime | None


class SessionRow(Protocol):
    id: str
    publication_id: str
    session_seed: int
    assigned: Any
    save_mode: str
    revision: int
    snapshot: Any
    submitted_at: datetime | None
    consent_version: str | None
    consented_at: datetime | None


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
    def find_publication(
        self, slug: str, plan_checksum: str | None = None
    ) -> PublicationRow | None:
        """The newest version's publication under ``slug``; with ``plan_checksum``, the
        one under ``slug`` with that plan (an older version a session is still on)."""
        ...

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
        self,
        tenant_id: str,
        session_id: str,
        base_revision: int,
        snapshot: object,
        judge: Callable[[object, int], str | None] | None = None,
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
    def record_consent(self, tenant_id: str, session_id: str, version: str) -> Any: ...
    def decline(self, tenant_id: str, session_id: str, count: bool) -> bool: ...
    def withdraw(self, tenant_id: str, session_id: str, reason: str) -> int: ...


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
    local_copy: LocalCopy = "browser"


@dataclass(frozen=True, slots=True)
class SnapshotAck:
    revision: int
    replay: bool = False
    superseded: bool = False  # an older prefix of the server copy: nothing written


@dataclass(frozen=True, slots=True)
class QuotaOutcome:
    node_id: str
    result: QuotaResult
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
    local_copy: LocalCopy = "browser"


@dataclass(frozen=True, slots=True)
class ConsentAck:
    version: str
    consented_at: datetime
    replay: bool


@dataclass(frozen=True, slots=True)
class ExternalHandoff:
    """What the app needs to send the participant to an external task (task EX2): the signed
    return token and when it expires. The app appends it as ``osp_token`` and ``osp_return``
    to the outbound URL it builds from the node's template."""

    return_token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ExternalReturnAck:
    """The server verified the return token (task EX2). It stores nothing itself; the app
    resolves the engine's external effect with the (untrusted) return values."""

    node_id: str


@dataclass(frozen=True)
class SessionPolicy:
    resume_expiry: timedelta = timedelta(days=30)  # token stops working (S-1)
    release_after: timedelta = timedelta(hours=24)  # quota / balanced slots back (R-3)
    max_snapshot_bytes: int = 2_000_000
    max_record_bytes: int = 5_000_000
    max_url_params: int = 50
    max_url_param_chars: int = 1000
    external_token_ttl: timedelta = timedelta(hours=6)  # external-task return token life (EX2)


def canonical_json(value: object) -> str:
    """Sorted keys, no whitespace, no NaN (the same rule as osp-store)."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def quota_result(value: object) -> QuotaResult:
    """The engine's quota word for a stored or older-contract one (``admitted`` -> ``open``)."""
    if isinstance(value, str) and value in _QUOTA_RESULT:
        return _QUOTA_RESULT[value]
    raise InvalidPayload(f"unknown quota result {str(value)[:20]!r}")


def local_copy(plan: object) -> LocalCopy:
    """``settings.localCopy`` from a runtime plan (default ``browser``, semantics §5)."""
    settings = plan.get("settings") if isinstance(plan, Mapping) else None
    value = settings.get("localCopy") if isinstance(settings, Mapping) else None
    return "memory" if value == "memory" else "browser"


def _events(snapshot: object) -> list[Any] | None:
    """The engine event log of a snapshot (``data.events``), or None if it has none."""
    data = snapshot.get("data") if isinstance(snapshot, Mapping) else None
    events = data.get("events") if isinstance(data, Mapping) else None
    return events if isinstance(events, list) else None


def is_older_prefix(snapshot: object, server: object) -> bool:
    """True when ``snapshot`` is an older state of ``server``: its event log is a prefix
    of the server copy's (compared as canonical JSON) and its engine revision is not
    newer. A dead page's late save then carries nothing the server lacks."""
    mine, theirs = _events(snapshot), _events(server)
    if mine is None or theirs is None or len(mine) > len(theirs):
        return False
    rev = snapshot.get("revision") if isinstance(snapshot, Mapping) else None
    server_rev = server.get("revision") if isinstance(server, Mapping) else None
    if isinstance(rev, int) and isinstance(server_rev, int) and rev > server_rev:
        return False
    try:
        return canonical_json(mine) == canonical_json(theirs[: len(mine)])
    except TypeError, ValueError, RecursionError:
        return False


def is_fast_forward(snapshot: object, server: object) -> bool:
    """True when ``snapshot`` strictly extends ``server``: the server copy's event log is a
    proper prefix of its log (compared as canonical JSON) and its engine revision is newer.
    Writing it loses nothing the server holds. Copies that diverged (neither log a prefix
    of the other, e.g. two devices) are never a fast-forward. No server copy yet counts as
    an empty log."""
    mine = _events(snapshot)
    theirs: list[Any] | None = [] if server is None else _events(server)
    if mine is None or theirs is None or len(mine) <= len(theirs):
        return False
    rev = snapshot.get("revision") if isinstance(snapshot, Mapping) else None
    server_rev = server.get("revision") if isinstance(server, Mapping) else None
    if isinstance(rev, int) and isinstance(server_rev, int) and rev <= server_rev:
        return False
    try:
        return canonical_json(mine[: len(theirs)]) == canonical_json(theirs)
    except TypeError, ValueError, RecursionError:
        return False


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
        return_secret: bytes | None = None,
    ) -> None:
        self._repo = repo
        self._clock = clock
        self._rng = rng or SystemRandom()
        self.policy = policy or SessionPolicy()
        # Key that signs external-task return tokens (task EX2). A per-process random default
        # is fine for one dev process; production passes an explicit secret so every worker
        # (and a restart) verifies the same tokens (osp-api serve: OSP_EXTERNAL_TOKEN_KEY).
        self._return_secret = return_secret or secrets.token_bytes(32)
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
        """The immutable plan for ``(slug, checksum)``, also for an older version."""
        pub = self._repo.find_publication(slug, checksum)
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
            # A consent page: nothing about the participant before they agree (§11).
            params if cfg.save_mode == "every-page" and cfg.consent is None else None,
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
            local_copy(pub.plan),
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

    def _config(self, cred: CredentialRow) -> RuntimeConfig:
        pub = self._repo.get_publication(cred.tenant_id, cred.publication_id)
        return RuntimeConfig.from_json(pub.config)

    @staticmethod
    def _require_consent(cfg: RuntimeConfig, cred: CredentialRow) -> None:
        """semantics.md §11: no response data before the participant agreed."""
        if cfg.consent is not None and getattr(cred, "consented_at", None) is None:
            raise ConsentRequired("the participant has not agreed to take part")

    # -- consent, decline, withdrawal (semantics.md §11) -----------------------------

    def consent(self, session_id: str, token: object, version: object) -> ConsentAck:
        """Record the participant's agreement to the plan's consent ``version`` (server
        time). Idempotent; a different version than the plan's is refused."""
        cred = self._auth(token, session_id)
        cfg = self._config(cred)
        if cfg.consent is None:
            raise NotFoundError("this survey has no consent page")
        if version != cfg.consent.version:
            raise InvalidPayload("this is not the survey's consent version", "consent.version")
        r = self._repo.record_consent(cred.tenant_id, session_id, cfg.consent.version)
        match r.status:
            case "ok" | "replay":
                return ConsentAck(r.version, r.consented_at, r.status == "replay")
            case "submitted":
                raise SessionSubmitted("this session was submitted")
            case _:
                raise InvalidPayload("another consent version was recorded", "consent.version")

    def decline(self, session_id: str, token: object) -> bool:
        """The participant declined: the session is deleted (its token stops working) and
        nothing is kept but, if the survey asks for it, an anonymous count. Refused after
        agreeing (use withdraw)."""
        cred = self._auth(token, session_id, allow_expired=True)
        cfg = self._config(cred)
        if cfg.consent is None:
            raise NotFoundError("this survey has no consent page")
        if not self._repo.decline(cred.tenant_id, session_id, cfg.consent.count_declines):
            raise InvalidPayload(
                "the participant already agreed; withdraw instead", "consent.already_given"
            )
        return True

    def withdraw(self, session_id: str, token: object) -> int:
        """Participant withdrawal (before or after submit): delete the session and its
        response. Audited by the store without answer data. Returns responses deleted."""
        cred = self._auth(token, session_id, allow_expired=True)
        return self._repo.withdraw(cred.tenant_id, session_id, "participant withdrawal")

    # -- snapshot --------------------------------------------------------------------

    def save_snapshot(
        self, session_id: str, token: object, base_revision: object, snapshot: object
    ) -> SnapshotAck:
        cred = self._auth(token, session_id)
        self._require_consent(self._config(cred), cred)
        if isinstance(base_revision, bool) or not isinstance(base_revision, int):
            raise InvalidPayload("baseRevision must be an integer")
        if base_revision < 0:
            raise InvalidPayload("baseRevision must be >= 0")
        _size(snapshot, self.policy.max_snapshot_bytes, "snapshot")
        base = base_revision

        def judge(server: object, server_revision: int) -> str | None:
            """The base is not current: is this save still safe to take? Asked by the
            store inside its transaction, against the copy it holds right then."""
            # A late save from a dead page that the server copy already contains: a no-op,
            # not a conflict.
            if base < server_revision and is_older_prefix(snapshot, server):
                return "superseded"
            # A fast-forward (R9-1): it extends the server copy, so nothing is overwritten.
            if is_fast_forward(snapshot, server):
                return "fast-forward"
            return None

        w = self._repo.write_snapshot(cred.tenant_id, session_id, base_revision, snapshot, judge)
        match w.status:
            case "ok" | "replay":
                return SnapshotAck(w.revision, w.status == "replay")
            case "superseded":
                return SnapshotAck(w.revision, superseded=True)
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
        cfg = RuntimeConfig.from_json(pub.config)
        self._require_consent(cfg, cred)
        q = cfg.quota_by_node.get(node_id)
        if q is None:
            raise NotFoundError(f"no quotaCheck node {node_id!r} in this survey")
        c = self._repo.claim_quota(cred.tenant_id, session_id, node_id, q.quota)
        match c.status:
            case "ok" | "replay":
                return QuotaOutcome(node_id, quota_result(c.result), c.status == "replay")
            case "submitted":
                raise SessionSubmitted("this session was submitted")
            case _:
                raise SessionExpired("this session expired after inactivity")

    # -- external task (task EX2, planning/external-tasks.md) ------------------------

    def _sign_return(self, session_id: str, node_id: str, exp: int) -> str:
        """A return token: ``base64url(payload).hmac_hex`` over ``{v,sid,node,exp}``. The
        signature binds it to this session and node, and ``exp`` bounds its life."""
        payload = {"v": 1, "sid": session_id, "node": node_id, "exp": exp}
        body = (
            base64.urlsafe_b64encode(canonical_json(payload).encode("utf-8")).decode().rstrip("=")
        )
        sig = hmac.new(self._return_secret, body.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{body}.{sig}"

    def _verify_return(self, token: object, session_id: str, node_id: str) -> None:
        """Raise unless ``token`` is a valid, unexpired return token for this session/node."""
        if not isinstance(token, str) or token.count(".") != 1 or not 0 < len(token) <= 1024:
            raise ExternalTokenInvalid("the return token is missing or malformed")
        body, sig = token.split(".", 1)
        expected = hmac.new(self._return_secret, body.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise ExternalTokenInvalid("the return token's signature does not verify")
        try:
            raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
            payload = json.loads(raw)
        except ValueError, TypeError:
            raise ExternalTokenInvalid("the return token is not readable") from None
        if not isinstance(payload, dict) or payload.get("v") != 1:
            raise ExternalTokenInvalid("the return token is of an unknown version")
        if payload.get("sid") != session_id or payload.get("node") != node_id:
            raise ExternalTokenInvalid("the return token is for another session or task")
        exp = payload.get("exp")
        if isinstance(exp, bool) or not isinstance(exp, int):
            raise ExternalTokenInvalid("the return token has no expiry")
        if int(self._clock().timestamp()) >= exp:
            raise ExternalTokenExpired("the return token has expired")

    def external_handoff(self, session_id: str, token: object, node_id: str) -> ExternalHandoff:
        """Mint a signed, expiring return token for an ``externalTask`` node (task EX2). The
        app appends it (``osp_token``) and the survey's return URL (``osp_return``) to the
        outbound URL it builds from the node's template, then navigates. The node must be one
        of the published survey's external-task nodes."""
        cred = self._auth(token, session_id)
        cfg = self._config(cred)
        self._require_consent(cfg, cred)
        if node_id not in cfg.external:
            raise NotFoundError(f"no externalTask node {node_id!r} in this survey")
        exp = int(self._clock().timestamp()) + int(self.policy.external_token_ttl.total_seconds())
        return ExternalHandoff(
            self._sign_return(session_id, node_id, exp), datetime.fromtimestamp(exp, tz=UTC)
        )

    def external_return(
        self, session_id: str, token: object, node_id: str, return_token: object
    ) -> ExternalReturnAck:
        """Verify an external-task return token (task EX2): signature (tamper), expiry, and
        that it is bound to this session and node (cross-context replay). Stores nothing; the
        app resolves the engine's external effect with the (untrusted) return values. A second
        return with the same token is harmless: the engine already recorded the node's result,
        so it changes nothing (same-context replay)."""
        cred = self._auth(token, session_id)
        cfg = self._config(cred)
        self._require_consent(cfg, cred)
        if node_id not in cfg.external:
            raise NotFoundError(f"no externalTask node {node_id!r} in this survey")
        self._verify_return(return_token, session_id, node_id)
        return ExternalReturnAck(node_id)

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
        cfg = RuntimeConfig.from_json(pub.config)
        if cred.submitted_at is None:
            self._require_consent(cfg, cred)
        answers, orders, engine_version = validate_record(record, sess, pub)
        server: dict[str, Any] = {
            "saveMode": sess.save_mode,
            "allocationMode": "server",
            "sessionSeed": sess.session_seed,
            "assigned": sess.assigned,
            "planChecksum": pub.plan_checksum,
            "late": late,  # the store sets the final value
        }
        if cfg.consent is not None:
            if cred.submitted_at is None and record.get("consentVersion") != cfg.consent.version:
                raise InvalidPayload("consentVersion does not match the survey", "submit.consent")
            # The server's own record of what was agreed and when (semantics.md §11).
            consented = getattr(sess, "consented_at", None)
            server["consentVersion"] = getattr(sess, "consent_version", None)
            server["consentedAt"] = consented.isoformat() if consented else None
        stored = {"record": record, "server": server}
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
            local_copy(pub.plan),
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
