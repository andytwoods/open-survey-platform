"""Who a builder request acts as: the host decides (plan P, planning/pages-split.md).

osp-api has no accounts, passwords or sessions. An :class:`IdentityProvider` turns a
request into an :class:`~osp_app.identity.Identity` (an :class:`~osp_app.auth.Actor`, i.e.
user id + ``{lab: role}``, and an optional display name), or ``None`` (401). Shipped:

- :class:`TrustedHeaders`: a host or reverse proxy authenticates the request, then forwards
  it with HMAC-signed ``X-OSP-*`` headers (D2; format in :mod:`osp_api.signing`).
- :class:`InProcess`: a Python host that mounts the ASGI app passes a callable.
- :class:`Dev`: everyone is the dev researcher (D12): only with ``OSP_ENV=dev`` and a
  loopback bind.

Every provider's output goes through :func:`osp_app.make_identity`, so caps, the id
character set and the strict role names apply whichever host sent it.
"""

from __future__ import annotations

import hmac
import inspect
import logging
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol, runtime_checkable
from urllib.parse import quote, unquote

from osp_app import Identity, InvalidIdentity, make_identity
from osp_app.auth import Actor
from osp_app.identity import dev_identity, parse_roles
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from . import signing

log = logging.getLogger("osp_api.identity")

MAX_SKEW_S = 60
NONCE_TTL_S = 120
NONCE_CACHE_MAX = 1_000_000
MIN_SECRET_BYTES = 32
_KID = re.compile(r"[A-Za-z0-9_-]{1,32}")
_NONCE = re.compile(r"[A-Za-z0-9_-]{22,64}")
_SIG = re.compile(r"[0-9a-f]{64}")
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


class IdentityConfigError(Exception):
    """A provider can't be built from its settings (osp-api refuses to start)."""


@runtime_checkable
class IdentityProvider(Protocol):
    async def identify(self, request: Request) -> Identity | None:
        """The identity the request acts as, or ``None`` (osp-api answers 401)."""
        ...


def _checked(value: Identity | Actor | None) -> Identity | None:
    """Re-check whatever a provider produced, so every host meets the same rules."""
    if value is None:
        return None
    if isinstance(value, Actor):
        value = Identity(value)
    if not isinstance(value, Identity):
        log.warning("identity refused: provider returned %s", type(value).__name__)
        return None
    try:
        return make_identity(value.actor.user_id, value.actor.roles, value.display_name)
    except InvalidIdentity as exc:
        log.warning("identity refused: %s", exc)
        return None


# -- TrustedHeaders (D2) -----------------------------------------------------------------


def parse_keyring(text: str) -> dict[str, bytes]:
    """``OSP_IDENTITY_KEYS``: ``kid:secret,kid2:secret2``. Several keys verify at once, so
    a host can rotate without downtime (add the new key, switch the host, drop the old)."""
    keys: dict[str, bytes] = {}
    for part in (p.strip() for p in text.split(",")):
        if not part:
            continue
        kid, sep, secret = part.partition(":")
        kid, secret = kid.strip(), secret.strip()
        if not sep or not _KID.fullmatch(kid):
            raise IdentityConfigError(
                "OSP_IDENTITY_KEYS entries are kid:secret (kid: 1-32 of A-Z a-z 0-9 _ -)"
            )
        if len(secret.encode("utf-8")) < MIN_SECRET_BYTES:
            raise IdentityConfigError(
                f"identity key {kid!r} is shorter than {MIN_SECRET_BYTES} bytes"
            )
        if kid in keys:
            raise IdentityConfigError(f"identity key {kid!r} is listed twice")
        keys[kid] = secret.encode("utf-8")
    if not keys:
        raise IdentityConfigError("OSP_IDENTITY_KEYS is empty")
    return keys


class NonceCache:
    """Nonces seen in the last ``ttl`` seconds (one process, in memory: a documented limit;
    several workers each keep their own). Full of live nonces: refuse, never evict."""

    def __init__(self, ttl: float = NONCE_TTL_S, max_size: int = NONCE_CACHE_MAX) -> None:
        self.ttl = ttl
        self.max_size = max_size
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()

    def add(self, nonce: str, now: float) -> bool:
        """True if ``nonce`` is new (and now remembered), False on a replay or when full."""
        with self._lock:
            while self._seen:
                oldest, expires = next(iter(self._seen.items()))
                if expires > now:
                    break
                del self._seen[oldest]
            if nonce in self._seen or len(self._seen) >= self.max_size:
                return False
            self._seen[nonce] = now + self.ttl
            return True


def _raw_path(request: Request) -> str:
    raw = request.scope.get("raw_path")
    if isinstance(raw, bytes | bytearray):
        return bytes(raw).split(b"?", 1)[0].decode("latin-1")
    return quote(request.url.path)


class TrustedHeaders:
    """Verify the host's signed ``X-OSP-*`` headers (format: :mod:`osp_api.signing`).

    Unsigned, wrongly signed, stale (more than 60 s off), replayed, unknown key id or a
    malformed identity: ``None`` (401). The reason is logged, never the values."""

    def __init__(
        self,
        keys: Mapping[str, bytes | str],
        *,
        clock: Callable[[], float] = time.time,
        max_skew: float = MAX_SKEW_S,
        nonces: NonceCache | None = None,
    ) -> None:
        if not keys:
            raise IdentityConfigError("TrustedHeaders needs at least one key")
        self.keys = {k: v.encode("utf-8") if isinstance(v, str) else v for k, v in keys.items()}
        self.clock = clock
        self.max_skew = max_skew
        self.nonces = nonces or NonceCache()

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> TrustedHeaders:
        text = environ.get("OSP_IDENTITY_KEYS", "")
        if not text.strip():
            raise IdentityConfigError(
                "OSP_IDENTITY=trusted-headers needs OSP_IDENTITY_KEYS=kid:secret "
                "(a shared secret of at least 32 bytes, also given to the host); "
                "for local development use OSP_IDENTITY=dev"
            )
        return cls(parse_keyring(text))

    def _refuse(self, why: str) -> None:
        log.warning("identity refused: %s", why)

    async def identify(self, request: Request) -> Identity | None:
        h = request.headers
        if not any(name in h for name in signing.ALL_HEADERS):
            return None  # no identity sent at all: a plain 401, nothing to log
        if any(len(h.getlist(name)) > 1 for name in signing.ALL_HEADERS):
            return self._refuse("an X-OSP-* header was sent twice")
        values = {name: h.get(name) for name in signing.ALL_HEADERS}
        required = [n for n in signing.ALL_HEADERS if n != signing.H_NAME]
        if any(values[n] is None for n in required):
            return self._refuse("missing X-OSP-* header")
        kid, sig, ts, nonce = (
            values[signing.H_KEY_ID],
            values[signing.H_SIGNATURE],
            values[signing.H_TIMESTAMP],
            values[signing.H_NONCE],
        )
        assert kid is not None and sig is not None and ts is not None and nonce is not None
        secret = self.keys.get(kid)
        if secret is None:
            return self._refuse("unknown key id")
        if not _SIG.fullmatch(sig) or not _NONCE.fullmatch(nonce):
            return self._refuse("malformed signature or nonce")
        if not ts.isdigit() or len(ts) > 12:
            return self._refuse("malformed timestamp")
        now = self.clock()
        if abs(now - int(ts)) > self.max_skew:
            return self._refuse("timestamp outside the allowed clock skew")
        body = await request.body()
        canonical = signing.canonical_string(
            method=request.method,
            path=_raw_path(request),
            query=request.url.query,
            body_sha256=signing.body_digest(body),
            user=values[signing.H_USER] or "",
            roles=values[signing.H_ROLES] or "",
            display_name=values[signing.H_NAME] or "",
            timestamp=ts,
            nonce=nonce,
        )
        if not hmac.compare_digest(signing.signature(secret, canonical), sig):
            return self._refuse("bad signature")
        if not self.nonces.add(nonce, now):
            return self._refuse("replayed nonce")
        try:
            name_raw = values[signing.H_NAME]
            name = None if not name_raw else unquote(name_raw, errors="strict")
            return make_identity(
                values[signing.H_USER], parse_roles(values[signing.H_ROLES] or ""), name
            )
        except (InvalidIdentity, UnicodeDecodeError) as exc:
            return self._refuse(f"invalid identity ({exc})")


# -- InProcess -----------------------------------------------------------------------------

HostCallable = Callable[[Request], "Identity | Actor | None | Awaitable[Identity | Actor | None]"]


class InProcess:
    """A Python host that mounts the ASGI app says who the request is, e.g. from its own
    session. ``fn(request)`` returns an Identity, an Actor or None; it may be async. A sync
    one runs in a worker thread (so it may use a synchronous ORM). The host checks CSRF
    before its request reaches osp-api (D4)."""

    def __init__(self, fn: HostCallable) -> None:
        self.fn = fn

    async def identify(self, request: Request) -> Identity | None:
        if inspect.iscoroutinefunction(self.fn):
            result = await self.fn(request)
        else:
            result = await run_in_threadpool(self.fn, request)
            if inspect.isawaitable(result):
                result = await result
        return _checked(result)  # type: ignore[arg-type]


# -- Dev (D12) -----------------------------------------------------------------------------


class Dev:
    """Every request is the dev researcher, owner of the dev lab (``osp_app.identity``).
    Refuses to exist unless ``env == "dev"`` and the server binds a loopback address."""

    def __init__(self, *, env: str, host: str) -> None:
        if (env or "").strip().lower() != "dev":
            raise IdentityConfigError(
                f"OSP_IDENTITY=dev is for local development only (OSP_ENV is {env!r}, not 'dev')"
            )
        if host not in LOOPBACK:
            raise IdentityConfigError(
                f"OSP_IDENTITY=dev only serves on 127.0.0.1, not {host!r}: anyone who can "
                "reach it would be the lab owner"
            )
        self.identity = dev_identity()

    async def identify(self, request: Request) -> Identity | None:
        return self.identity


class Nobody:
    """No provider configured: every builder request is 401 (fail closed)."""

    async def identify(self, request: Request) -> Identity | None:
        return None


PROVIDERS = ("trusted-headers", "dev")


def provider_from_env(environ: Mapping[str, str], *, env: str, host: str) -> IdentityProvider:
    """``OSP_IDENTITY`` = ``trusted-headers`` (default) or ``dev``."""
    name = (environ.get("OSP_IDENTITY") or "trusted-headers").strip().lower()
    if name == "trusted-headers":
        return TrustedHeaders.from_env(environ)
    if name == "dev":
        return Dev(env=env, host=host)
    raise IdentityConfigError(f"OSP_IDENTITY must be one of {', '.join(PROVIDERS)}, not {name!r}")
