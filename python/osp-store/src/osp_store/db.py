"""Engine creation and migrations (SQLite for dev/tests, Postgres via pg8000)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, event
from sqlalchemy import create_engine as _sa_create_engine
from sqlalchemy.pool import StaticPool

MIGRATIONS = Path(__file__).with_name("migrations")


SQLITE_BUSY_TIMEOUT_S = 30.0


def create_engine(url: str, **kwargs: object) -> Engine:
    """Create an engine with the store's per-backend settings.

    SQLite: foreign keys switched on for every connection; ``sqlite://`` (in-memory)
    shares one connection so the schema survives. Postgres: use
    ``postgresql+pg8000://user:pass@host/db`` (pg8000 is BSD; psycopg is LGPL).

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
