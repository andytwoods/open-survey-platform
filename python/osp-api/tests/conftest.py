"""Builder API fixtures: a SQLite store, two labs, four researchers, cookie clients."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from osp_api.app import create_app
from osp_app import AppServices, build_services
from osp_app.auth.testing import FakeClock, FakeRandom, cheap_hasher
from osp_store import Keyring, Store, SystemContext, create_engine, migrate

KEY = "a" * 43 + "="
PASSWORD = "correct horse battery staple 42"
BASE_URL = "https://testserver"  # Secure cookies are only sent over https


@dataclass
class BuilderEnv:
    store: Store
    services: AppServices
    clock: FakeClock
    tenants: dict[str, str] = field(default_factory=dict)  # "A"/"B" -> tenant id
    users: dict[str, str] = field(default_factory=dict)  # email -> user id

    def __post_init__(self) -> None:
        self.app = create_app(builder=self.services)

    def client(self) -> TestClient:
        return TestClient(self.app, base_url=BASE_URL)

    def login(self, email: str) -> TestClient:
        c = self.client()
        r = c.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        c.headers["X-CSRF-Token"] = body["me"]["csrfToken"]
        return c


@pytest.fixture
def benv(tmp_path) -> BuilderEnv:
    engine = create_engine(f"sqlite:///{tmp_path / 'builder.db'}")
    migrate(engine)
    store = Store(engine, Keyring({"k1": KEY}, active="k1"))
    clock = FakeClock()
    services = build_services(store, clock=clock, rng=FakeRandom("api"), hasher=cheap_hasher())
    env = BuilderEnv(store, services, clock)
    sys = SystemContext("system:test")
    for lab in ("A", "B"):
        env.tenants[lab] = store.create_tenant(sys, f"Lab {lab}").id
    for email, lab, role in (
        ("owner@a.example", "A", "owner"),
        ("editor@a.example", "A", "editor"),
        ("viewer@a.example", "A", "viewer"),
        ("owner@b.example", "B", "owner"),
    ):
        env.users[email] = services.create_account(env.tenants[lab], email, PASSWORD, role)
    return env
