"""Engine creation and migrations (SQLite for dev/tests, Postgres via pg8000)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, event
from sqlalchemy import create_engine as _sa_create_engine
from sqlalchemy.pool import StaticPool

MIGRATIONS = Path(__file__).with_name("migrations")


def create_engine(url: str, **kwargs: object) -> Engine:
    """Create an engine with the store's per-backend settings.

    SQLite: foreign keys switched on for every connection; ``sqlite://`` (in-memory)
    shares one connection so the schema survives. Postgres: use
    ``postgresql+pg8000://user:pass@host/db`` (pg8000 is BSD; psycopg is LGPL).
    """
    if url.startswith("sqlite"):
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs.setdefault("poolclass", StaticPool)
            kwargs.setdefault("connect_args", {"check_same_thread": False})
        engine = _sa_create_engine(url, **kwargs)

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

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
