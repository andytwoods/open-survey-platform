"""OSP_DATABASE_URL as PaaS hosts hand it out (task H2a): ``postgres://`` and
``postgresql://`` mean pg8000; libpq's ``sslmode`` becomes pg8000's ``ssl_context``."""

from __future__ import annotations

import ssl

import pytest
from osp_store import DatabaseUrlError, create_engine, db, normalise_database_url
from sqlalchemy import text


@pytest.mark.parametrize(
    "url",
    [
        "postgres://u:p%40ss@db.example:5432/osp",
        "postgresql://u:p%40ss@db.example:5432/osp",
        "POSTGRES://u:p%40ss@db.example:5432/osp",
        "postgresql+pg8000://u:p%40ss@db.example:5432/osp",
        "  postgres://u:p%40ss@db.example:5432/osp\n",
    ],
)
def test_postgres_schemes_map_to_pg8000(url: str) -> None:
    out, args = normalise_database_url(url)
    assert out == "postgresql+pg8000://u:p%40ss@db.example:5432/osp"
    assert args == {}


@pytest.mark.parametrize(
    "url",
    ["sqlite:///.data/osp.db", "sqlite://", "sqlite:///:memory:", "mysql+pymysql://u@h/d"],
)
def test_other_urls_are_untouched(url: str) -> None:
    assert normalise_database_url(url) == (url, {})


def test_engine_uses_pg8000_without_connecting() -> None:
    for url in ("postgres://u:p@h/d", "postgresql://u:p@h/d"):
        engine = create_engine(url)
        assert engine.dialect.driver == "pg8000"
        assert engine.url.drivername == "postgresql+pg8000"
        assert engine.url.password == "p"
        engine.dispose()


@pytest.mark.parametrize("mode", ["disable", "allow", "prefer", "DISABLE"])
def test_sslmode_without_tls(mode: str) -> None:
    out, args = normalise_database_url(f"postgres://u@h/d?sslmode={mode}&application_name=x")
    assert out == "postgresql+pg8000://u@h/d?application_name=x"
    assert args == {}


def test_sslmode_require_is_tls_without_verification() -> None:
    out, args = normalise_database_url("postgres://u@h/d?sslmode=require")
    assert out == "postgresql+pg8000://u@h/d"
    ctx = args["ssl_context"]
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_NONE and not ctx.check_hostname


@pytest.mark.parametrize(("mode", "hostname"), [("verify-ca", False), ("verify-full", True)])
def test_sslmode_verify(mode: str, hostname: bool) -> None:
    _, args = normalise_database_url(f"postgresql://u@h/d?sslmode={mode}")
    ctx = args["ssl_context"]
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is hostname


def test_engine_gets_ssl_context_and_caller_args_win(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake(url: str, **kwargs: object) -> str:
        seen.update(kwargs, url=url)
        return "engine"

    monkeypatch.setattr(db, "_sa_create_engine", fake)
    create_engine("postgres://u@h/d?sslmode=require", connect_args={"timeout": 5})
    assert seen["url"] == "postgresql+pg8000://u@h/d"
    cargs = seen["connect_args"]
    assert isinstance(cargs, dict)
    assert isinstance(cargs["ssl_context"], ssl.SSLContext)
    assert cargs["timeout"] == 5
    create_engine("postgres://u@h/d?sslmode=require", connect_args={"ssl_context": False})
    assert seen["connect_args"] == {"ssl_context": False}


@pytest.mark.parametrize(
    "url",
    [
        "postgres://u@h/d?sslmode=sometimes",
        "postgres://u@h/d?sslmode=require&sslmode=disable",
        "postgres://u@h:notaport/d",
    ],
)
def test_bad_urls_are_a_clear_error(url: str) -> None:
    with pytest.raises(DatabaseUrlError):
        create_engine(url)


def test_postgres_scheme_connects(pg_admin_url: str) -> None:
    """Against the real server when ``make test-postgres`` runs (skipped otherwise)."""
    bare = pg_admin_url.replace("postgresql+pg8000://", "postgres://", 1)
    engine = create_engine(bare)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar() == 1
    finally:
        engine.dispose()
