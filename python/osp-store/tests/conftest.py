"""Fixtures: every ``store``-using test runs on SQLite and on Postgres.

Postgres is opt-in so ``make check`` never needs Docker:

- ``make test-postgres`` (sets ``OSP_TEST_POSTGRES=1``) starts a throwaway
  ``postgres`` container with Docker and runs the store tests against it;
- or point ``OSP_TEST_POSTGRES_URL`` at an existing server
  (``postgresql+pg8000://user:pass@host:port/db``; the user must be able to
  CREATE DATABASE).

Each test gets a fresh database (a new file for SQLite, a new database on the
Postgres server), migrated with Alembic.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from osp_store import Keyring, Store, SystemContext, TenantContext, create_engine, migrate
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

PG_IMAGE = os.environ.get("OSP_TEST_POSTGRES_IMAGE", "postgres:17-alpine")
KEY_A = "a" * 43 + "="  # 32 bytes of 0x69.. (base64url); test keys only
KEY_B = "b" * 43 + "="


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> datetime:
        self.now += timedelta(**kwargs)
        return self.now


def _docker_ok() -> tuple[bool, str]:
    if shutil.which("docker") is None:
        return False, "docker CLI not found"
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"docker info failed: {exc}"
    if r.returncode != 0:
        return False, "Docker isn't running (start Colima: `colima start`)"
    return True, ""


def _wait_for(url: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        eng = create_engine(url)
        try:
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001 - server still starting
            last = exc
            time.sleep(0.5)
        finally:
            eng.dispose()
    raise RuntimeError(f"Postgres did not become ready: {last}")


@pytest.fixture(scope="session")
def pg_admin_url() -> Iterator[str]:
    url = os.environ.get("OSP_TEST_POSTGRES_URL")
    if url:
        _wait_for(url, timeout=10)
        yield url
        return
    if os.environ.get("OSP_TEST_POSTGRES") != "1":
        pytest.skip("Postgres store tests are opt-in: run `make test-postgres` (needs Docker)")
    ok, why = _docker_ok()
    if not ok:
        pytest.skip(f"Postgres store tests skipped: {why}")
    name = f"osp-store-test-{uuid.uuid4().hex[:10]}"
    run = subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--name", name,
            "-e", "POSTGRES_PASSWORD=osp", "-e", "POSTGRES_USER=osp", "-e", "POSTGRES_DB=osp",
            "-p", "127.0.0.1::5432", PG_IMAGE,
        ],
        capture_output=True, text=True, timeout=300, check=False,
    )  # fmt: skip
    if run.returncode != 0:
        pytest.skip(
            f"Postgres store tests skipped: could not start container: {run.stderr.strip()}"
        )
    try:
        port = subprocess.run(
            ["docker", "port", name, "5432/tcp"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip().splitlines()[0].rsplit(":", 1)[1]  # fmt: skip
        url = f"postgresql+pg8000://osp:osp@127.0.0.1:{port}/osp"
        _wait_for(url)
        yield url
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60, check=False)


@dataclass
class Backend:
    name: str
    engine: Engine
    sqlite_path: str | None = None


@pytest.fixture(params=["sqlite", "postgres"])
def backend(request: pytest.FixtureRequest, tmp_path) -> Iterator[Backend]:  # noqa: ANN001
    if request.param == "sqlite":
        path = tmp_path / "store.db"
        engine = create_engine(f"sqlite:///{path}")
        yield Backend("sqlite", engine, str(path))
        engine.dispose()
        return
    admin_url = request.getfixturevalue("pg_admin_url")
    db = f"osp_t_{uuid.uuid4().hex[:12]}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db}"'))
    engine = create_engine(make_url(admin_url).set(database=db).render_as_string(False))
    try:
        yield Backend("postgres", engine)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def engine(backend: Backend) -> Engine:
    migrate(backend.engine)
    return backend.engine


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def keyring() -> Keyring:
    return Keyring({"k1": KEY_A}, active="k1")


@pytest.fixture
def store(engine: Engine, keyring: Keyring, clock: FakeClock) -> Store:
    return Store(engine, keyring, clock=clock)


@pytest.fixture
def sys_ctx() -> SystemContext:
    return SystemContext("system:test")


@pytest.fixture
def tenants(store: Store, sys_ctx: SystemContext) -> tuple[TenantContext, TenantContext]:
    """Two tenants, each with one researcher; contexts act as that researcher."""
    out = []
    for name in ("Lab A", "Lab B"):
        tenant = store.create_tenant(sys_ctx, name)
        admin = TenantContext(tenant.id, "system:bootstrap")
        user = store.create_user(admin, f"r@{name[-1].lower()}.example", "researcher")
        out.append(TenantContext(tenant.id, user.id))
    return out[0], out[1]
