from __future__ import annotations

import pytest
from osp_app.auth import (
    AuthService,
    InMemoryMembershipRepo,
    InMemorySessionRepo,
    InMemoryUserRepo,
)
from osp_app.auth.testing import FakeClock, FakeRandom, cheap_hasher


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def rng() -> FakeRandom:
    return FakeRandom()


@pytest.fixture
def auth(clock: FakeClock, rng: FakeRandom) -> AuthService:
    return AuthService(
        users=InMemoryUserRepo(),
        memberships=InMemoryMembershipRepo(),
        sessions=InMemorySessionRepo(),
        clock=clock,
        rng=rng,
        hasher=cheap_hasher(),
    )
