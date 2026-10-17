"""``osp-api``: run the HTTP API with uvicorn.

    osp-api serve [--host 127.0.0.1] [--port 8000]
    osp-api init                 # data dir, dev keys, migrations; then exit

Settings come from the environment, with defaults for local development:

==================  ==========================================  =====================
variable            meaning                                     dev default
==================  ==========================================  =====================
OSP_ENV             ``dev`` or ``production``                   ``dev``
OSP_DATA_DIR        where dev state lives (gitignored)          ``.data``
OSP_DATABASE_URL    SQLAlchemy URL                              ``sqlite:///<data>/osp.db``
OSP_STORE_KEYS      encryption keyring (``osp-cli gen-key``)    see below
OSP_HOST/OSP_PORT   where to listen                             ``127.0.0.1`` / ``8000``
OSP_IDENTITY        ``trusted-headers`` or ``dev`` (who a       ``trusted-headers``
                    builder request is; see ``identity.py``)
OSP_IDENTITY_KEYS   ``kid:secret,...`` shared with the host     (required for
                    (TrustedHeaders; >= 32 bytes each)          trusted-headers)
OSP_AUTO_CREATE_LABS  create a lab on first sight of its id     ``on``
OSP_ALLOWED_ORIGINS   exact origins allowed cross-origin (CORS)  none
OSP_PUBLIC_ORIGINS    the host's public origins: pass the        none
                      Origin check, no CORS (D14)
OSP_TRUSTED_PROXIES   IPs/CIDRs whose X-Forwarded-For gives the  none
                      participant address (rate limits, D13)
OSP_NONCE_STORE       ``memory`` or ``database`` (D16)           ``memory`` in dev,
                                                                 ``database`` in production
==================  ==========================================  =====================

Identity (plan P): osp-api has no sign-in. Behind a host, ``trusted-headers`` verifies the
host's signed ``X-OSP-*`` headers; the host must be the only route to the API and strip any
``X-OSP-*`` a browser sends (D3), which is why the default bind is 127.0.0.1. ``dev`` makes
everyone the dev researcher and is refused unless ``OSP_ENV=dev`` and the bind is loopback.

Keys: in dev, if ``OSP_STORE_KEYS`` is unset, a keyring is generated on the first run into
``<data>/dev-keys.env`` (mode 0600) and reused after. That file is a convenience for a
laptop and nothing else: with ``OSP_ENV=production`` it is never read or written, and
``OSP_STORE_KEYS`` and ``OSP_DATABASE_URL`` must both be set.

The builder talks to this server through its dev server's ``/api`` proxy
(``web/builder/vite.config.ts``), so the browser sees one origin and no CORS is needed.

Logs never hold a client IP address (runtime-design §7, review §9 Q8): uvicorn's access
log is written without ``client_addr`` (``LOG_CONFIG``), and :class:`NoClientAddress`
blanks the address in the arguments of every uvicorn log record, so no other handler or
format can print it either. uvicorn's ``proxy_headers`` stays off; a forwarded address is
read only from ``OSP_TRUSTED_PROXIES`` peers, only as a rate-limit key (``client_address``).
"""

from __future__ import annotations

import argparse
import copy
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from osp_app import build_services
from osp_store import Keyring, Store, create_engine, generate_key, migrate
from osp_store.crypto import ENV_ACTIVE, ENV_KEYS
from sqlalchemy import Engine

from .client_address import TrustedProxiesError, parse_trusted_proxies
from .identity import (
    NONCE_STORES,
    IdentityConfigError,
    IdentityProvider,
    TrustedHeaders,
    nonce_store_from_name,
    provider_from_env,
)

ENVIRONMENTS = ("dev", "production")
_ON = frozenset({"1", "true", "on", "yes"})
_OFF = frozenset({"0", "false", "off", "no"})
DEV_KEYS_FILE = "dev-keys.env"


class ConfigError(Exception):
    """Bad or missing settings: printed, exit code 2."""


@dataclass(frozen=True)
class Settings:
    env: str
    data_dir: Path
    database_url: str
    host: str
    port: int
    auto_create_labs: bool = True
    allowed_origins: tuple[str, ...] = ()
    public_origins: tuple[str, ...] = ()
    trusted_proxies: tuple[str, ...] = ()
    nonce_store: str = "memory"

    @property
    def production(self) -> bool:
        return self.env == "production"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        name = (env.get("OSP_ENV") or "dev").strip().lower()
        if name not in ENVIRONMENTS:
            raise ConfigError(f"OSP_ENV must be one of {', '.join(ENVIRONMENTS)}, not {name!r}")
        data_dir = Path(env.get("OSP_DATA_DIR") or ".data")
        db = (env.get("OSP_DATABASE_URL") or "").strip()
        if not db:
            if name == "production":
                raise ConfigError("OSP_DATABASE_URL must be set when OSP_ENV=production")
            db = f"sqlite:///{data_dir / 'osp.db'}"
        raw_port = (env.get("OSP_PORT") or "8000").strip()
        if not raw_port.isdigit() or not 0 < int(raw_port) < 65536:
            raise ConfigError(f"OSP_PORT must be a port number, not {raw_port[:20]!r}")
        host = (env.get("OSP_HOST") or "127.0.0.1").strip()
        auto = (env.get("OSP_AUTO_CREATE_LABS") or "on").strip().lower()
        if auto not in _ON | _OFF:
            raise ConfigError(f"OSP_AUTO_CREATE_LABS must be on or off, not {auto[:20]!r}")
        allowed = _origins(env, "OSP_ALLOWED_ORIGINS")
        public = _origins(env, "OSP_PUBLIC_ORIGINS")
        proxies = tuple(p.strip() for p in (env.get("OSP_TRUSTED_PROXIES") or "").split(","))
        proxies = tuple(p for p in proxies if p)
        try:
            parse_trusted_proxies(proxies)
        except TrustedProxiesError as exc:
            raise ConfigError(str(exc)) from None
        # D16: production shares nonces through the database (several workers); dev keeps
        # them in memory (one process, nothing to set up).
        nonces = (env.get("OSP_NONCE_STORE") or "").strip().lower() or (
            "database" if name == "production" else "memory"
        )
        if nonces not in NONCE_STORES:
            raise ConfigError(
                f"OSP_NONCE_STORE must be one of {', '.join(NONCE_STORES)}, not {nonces[:20]!r}"
            )
        return cls(
            name,
            data_dir,
            db,
            host,
            int(raw_port),
            auto in _ON,
            allowed,
            public,
            proxies,
            nonces,
        )


def _origins(env: Mapping[str, str], var: str) -> tuple[str, ...]:
    origins = tuple(o.strip().rstrip("/") for o in (env.get(var) or "").split(","))
    origins = tuple(o for o in origins if o)
    for o in origins:
        if o == "*" or not o.startswith(("https://", "http://")) or o.count("/") != 2:
            raise ConfigError(f"{var} takes exact origins, not {o[:60]!r}")
    return origins


def _read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip()
    return out


def dev_keys_path(settings: Settings) -> Path:
    return settings.data_dir / DEV_KEYS_FILE


def keyring_env(settings: Settings, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """``OSP_STORE_KEYS`` (+ ``OSP_STORE_ACTIVE_KEY``) from the environment, or in dev from
    ``<data>/dev-keys.env``, generating that file on first use. Production never falls back."""
    env = os.environ if environ is None else environ
    if env.get(ENV_KEYS):
        return {k: env[k] for k in (ENV_KEYS, ENV_ACTIVE) if env.get(k)}
    if settings.production:
        raise ConfigError(
            f"{ENV_KEYS} must be set when OSP_ENV=production "
            "(generate one with `osp-cli gen-key` and keep it in your secret store)"
        )
    path = dev_keys_path(settings)
    if not path.exists():
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        text = (
            "# Dev-only encryption keys for the local osp-api (generated by `osp-api`).\n"
            "# Never use these for real data. Delete .data/ (`make dev-reset`) to start over.\n"
            f"{ENV_KEYS}=k1:{generate_key()}\n"
        )
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
    keys = _read_env_file(path)
    if not keys.get(ENV_KEYS):
        raise ConfigError(f"{path} has no {ENV_KEYS}; delete it to regenerate")
    return keys


def prepare(settings: Settings, environ: Mapping[str, str] | None = None) -> Store:
    """Create the data dir (SQLite), load the keyring, migrate, and open the store."""
    if settings.database_url.startswith("sqlite:///") and not settings.production:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
    keyring = Keyring.from_env(keyring_env(settings, environ))
    engine = create_engine(settings.database_url)
    migrate(engine)
    return Store(engine, keyring)


class NoClientAddress(logging.Filter):
    """Blank the client address in uvicorn log records. uvicorn passes it as the first
    argument of its access lines (``'%s - "%s %s HTTP/%s" %d'``) and of its WebSocket
    lines; the record is changed in place, so every handler sees ``-`` instead."""

    def filter(self, record: logging.LogRecord) -> bool:
        if (
            isinstance(record.args, tuple)
            and record.args
            and isinstance(record.msg, str)
            and record.msg.startswith("%s - ")
        ):
            record.args = ("-", *record.args[1:])
        return True


def log_config() -> dict:
    """uvicorn's default logging, minus the client address (see module docstring)."""
    import uvicorn.config

    cfg = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    cfg["formatters"]["access"]["fmt"] = '%(levelprefix)s "%(request_line)s" %(status_code)s'
    cfg.setdefault("filters", {})["no_client_address"] = {"()": NoClientAddress}
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        cfg["loggers"].setdefault(name, {})["filters"] = ["no_client_address"]
    return cfg


def identity_provider(
    settings: Settings,
    host: str,
    environ: Mapping[str, str] | None = None,
    engine: Engine | None = None,
) -> IdentityProvider:
    env = os.environ if environ is None else environ
    try:
        provider = provider_from_env(env, env=settings.env, host=host)
        if isinstance(provider, TrustedHeaders):
            provider.nonces = nonce_store_from_name(settings.nonce_store, engine)
        return provider
    except IdentityConfigError as exc:
        raise ConfigError(str(exc)) from exc


def build_app(
    settings: Settings, environ: Mapping[str, str] | None = None, *, host: str | None = None
) -> FastAPI:
    from .app import create_app

    store = prepare(settings, environ)
    identity = identity_provider(settings, host or settings.host, environ, store.engine)
    services = build_services(store, auto_create_labs=settings.auto_create_labs)
    return create_app(
        builder=services,
        identity=identity,
        allowed_origins=settings.allowed_origins,
        public_origins=settings.public_origins,
        trusted_proxies=settings.trusted_proxies,
    )


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="osp-api", description="Run the Open Survey Platform API.")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("serve", help="serve the API with uvicorn")
    s.add_argument("--host", help="default: OSP_HOST or 127.0.0.1")
    s.add_argument("--port", type=int, help="default: OSP_PORT or 8000")
    sub.add_parser("init", help="create the data dir and dev keys, migrate, and exit")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = Settings.from_env()
        if args.command == "init":
            prepare(settings)
            if not settings.production and not os.environ.get(ENV_KEYS):
                print(f"osp-api: dev keys in {dev_keys_path(settings)}")
            return 0
        host = args.host or settings.host
        app = build_app(settings, host=host)
    except ConfigError as exc:
        print(f"osp-api: {exc}", file=sys.stderr)
        return 2
    import uvicorn

    uvicorn.run(
        app,
        host=host,
        port=args.port or settings.port,
        log_level="info",
        log_config=log_config(),
        proxy_headers=False,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
