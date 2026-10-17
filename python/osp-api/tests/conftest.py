"""Builder API fixtures: a SQLite store, two labs, four researchers, signed clients.

There are no accounts (plan P): ``benv.login(email)`` returns a client that signs every
request as that host user with :func:`osp_api.signing.sign_identity_headers`, so all the
API tests go through the real :class:`~osp_api.identity.TrustedHeaders` path.
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, field

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from osp_api.app import create_app
from osp_api.identity import TrustedHeaders
from osp_api.signing import sign_identity_headers
from osp_app import AppServices, build_services
from osp_app.auth.testing import FakeClock
from osp_store import Keyring, Store, create_engine, migrate

KEY = "a" * 43 + "="
KEY_ID = "host1"
SECRET = "test-only-identity-secret-0123456789abcdef"  # never a real key
BASE_URL = "https://testserver"


class SignAs(httpx.Auth):
    """Sign each request as ``user`` with the roles in ``roles`` *at send time*."""

    requires_request_body = True

    def __init__(self, env: BuilderEnv, user: str, *, key_id: str = KEY_ID, secret: str = SECRET):
        self.env, self.user, self.key_id, self.secret = env, user, key_id, secret

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response]:
        path = request.url.raw_path.decode("ascii")
        request.headers.update(
            sign_identity_headers(
                key_id=self.key_id,
                secret=self.secret,
                method=request.method,
                path=path,
                body=request.content,
                user_id=self.user,
                roles=self.env.roles.get(self.user, {}),
                display_name=self.user,
                timestamp=int(self.env.clock.now().timestamp()),
            )
        )
        yield request


@dataclass
class BuilderEnv:
    store: Store
    services: AppServices
    clock: FakeClock
    tenants: dict[str, str] = field(default_factory=dict)  # "A"/"B" -> lab id
    roles: dict[str, dict[str, str]] = field(default_factory=dict)  # user -> {lab: role}

    def __post_init__(self) -> None:
        self.identity = TrustedHeaders({KEY_ID: SECRET}, clock=lambda: self.clock.now().timestamp())
        self.app = create_app(builder=self.services, identity=self.identity)

    @property
    def users(self) -> dict[str, str]:
        return {u: u for u in self.roles}  # the host's user id is the email here

    def client(self) -> TestClient:
        return TestClient(self.app, base_url=BASE_URL)

    def login(self, email: str) -> TestClient:
        """A client the host vouches for as ``email`` (no sign-in of our own)."""
        c = self.client()
        c.auth = SignAs(self, email)
        return c


@pytest.fixture
def benv(tmp_path) -> BuilderEnv:
    engine = create_engine(f"sqlite:///{tmp_path / 'builder.db'}")
    migrate(engine)
    store = Store(engine, Keyring({"k1": KEY}, active="k1"))
    clock = FakeClock()
    services = build_services(store, clock=clock)
    env = BuilderEnv(store, services, clock)
    for lab in ("A", "B"):
        env.tenants[lab] = services.create_lab(f"lab-{lab.lower()}", f"Lab {lab}")
    for email, lab, role in (
        ("owner@a.example", "A", "owner"),
        ("editor@a.example", "A", "editor"),
        ("viewer@a.example", "A", "viewer"),
        ("owner@b.example", "B", "owner"),
    ):
        env.roles[email] = {env.tenants[lab]: role}
    return env
