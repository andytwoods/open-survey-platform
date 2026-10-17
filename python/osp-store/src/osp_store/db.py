"""Engine creation and migrations (SQLite for dev/tests, Postgres via pg8000)."""

from __future__ import annotations

import ssl
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, event
from sqlalchemy import create_engine as _sa_create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.pool import StaticPool

MIGRATIONS = Path(__file__).with_name("migrations")


SQLITE_BUSY_TIMEOUT_S = 30.0

# Bare Postgres schemes as PaaS hosts hand them out (Heroku, Dokku, Render, Appliku ...):
# SQLAlchemy reads ``postgresql://`` as psycopg2 (LGPL, not installed) and doesn't know
# ``postgres://`` at all. Both mean pg8000 here.
_PG_SCHEMES = frozenset({"postgres", "postgresql"})
PG_DRIVER = "postgresql+pg8000"
# libpq's sslmode, which those URLs often carry (``?sslmode=require``), is not a pg8000
# argument; it becomes pg8000's ``ssl_context`` instead.
_SSLMODES = frozenset({"disable", "allow", "prefer", "require", "verify-ca", "verify-full"})


class DatabaseUrlError(ValueError):
    """``OSP_DATABASE_URL`` can't be used (unparseable, or an unsupported sslmode)."""


def normalise_database_url(url: str) -> tuple[str, dict[str, object]]:
    """``(url, connect_args)`` for SQLAlchemy.

    ``postgres://`` and ``postgresql://`` become ``postgresql+pg8000://``, and a libpq
    ``sslmode`` query parameter becomes pg8000's ``ssl_context``: ``disable``, ``allow``,
    ``prefer``: no TLS; ``require``: TLS without certificate checks (as libpq does);
    ``verify-ca`` / ``verify-full``: TLS against the system trust store (``verify-full``
    also checks the host name). Anything else (``sqlite:...``) is returned unchanged."""
    text = url.strip()
    scheme = text.partition(":")[0].lower()
    if scheme not in _PG_SCHEMES and scheme != PG_DRIVER:
        return text, {}
    try:
        parsed: URL = make_url(text)
    except (ArgumentError, ValueError) as exc:
        raise DatabaseUrlError(f"not a database URL: {exc}") from None
    if scheme in _PG_SCHEMES:
        parsed = parsed.set(drivername=PG_DRIVER)
    connect_args: dict[str, object] = {}
    mode = parsed.query.get("sslmode")
    if mode is not None:
        if isinstance(mode, tuple):
            raise DatabaseUrlError("sslmode is given more than once")
        mode = mode.lower()
        if mode not in _SSLMODES:
            raise DatabaseUrlError(f"unsupported sslmode {mode[:20]!r}")
        parsed = parsed.difference_update_query(["sslmode"])
        if mode == "require":
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            connect_args["ssl_context"] = ctx
        elif mode in ("verify-ca", "verify-full"):
            ctx = ssl.create_default_context()
            ctx.check_hostname = mode == "verify-full"
            connect_args["ssl_context"] = ctx
    return parsed.render_as_string(hide_password=False), connect_args


def create_engine(url: str, **kwargs: object) -> Engine:
    """Create an engine with the store's per-backend settings.

    SQLite: foreign keys switched on for every connection; ``sqlite://`` (in-memory)
    shares one connection so the schema survives. Postgres goes through pg8000 (BSD;
    psycopg is LGPL): ``postgresql+pg8000://user:pass@host/db``, or the bare
    ``postgres://`` / ``postgresql://`` a PaaS hands out (:func:`normalise_database_url`).

    SQLite files are set up for concurrent writers (several threads, or the API and
    ``osp-cli`` at once): WAL journal, a busy timeout, and every transaction opened with
    ``BEGIN IMMEDIATE``. The last one is the important part. pysqlite's default deferred
    ``BEGIN`` takes a read lock first and upgrades on the first write; two transactions
    that both read then write deadlock on the upgrade, and SQLite answers ``database is
    locked`` at once, without waiting out the busy timeout. Taking the write lock up front
    makes such transactions queue on the busy timeout instead.
    """
    if url.startswith("sqlite"):
        memory = url in ("sqlite://", "sqlite:///:memory:")
        if memory:
            kwargs.setdefault("poolclass", StaticPool)
            kwargs.setdefault("connect_args", {"check_same_thread": False})
        else:
            kwargs.setdefault("connect_args", {"timeout": SQLITE_BUSY_TIMEOUT_S})
        engine = _sa_create_engine(url, **kwargs)

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            if not memory:
                cur.execute(f"PRAGMA busy_timeout={int(SQLITE_BUSY_TIMEOUT_S * 1000)}")
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()
            if not memory:
                # Stop pysqlite issuing its own deferred BEGIN; `_begin` below does it.
                dbapi_conn.isolation_level = None

        if not memory:

            @event.listens_for(engine, "begin")
            def _begin(conn):  # noqa: ANN001
                conn.exec_driver_sql("BEGIN IMMEDIATE")

        return engine
    url, connect_args = normalise_database_url(url)
    if connect_args:
        given = kwargs.get("connect_args")
        kwargs["connect_args"] = {**connect_args, **(given if isinstance(given, dict) else {})}
    return _sa_create_engine(url, **kwargs)


def alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    return cfg


def migrate(engine: Engine, revision: str = "head") -> None:
    """Upgrade the database schema to ``revision`` (default: latest)."""
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, revision)


def downgrade(engine: Engine, revision: str = "base") -> None:
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, revision)
