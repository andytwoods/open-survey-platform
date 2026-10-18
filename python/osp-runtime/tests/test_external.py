"""External-task step and its return token (task EX2, planning/external-tasks.md).

Security: the return token is signed (tamper), expiring (expiry) and bound to one session
and node (cross-context replay). Same-context replay is the engine's job (per-node
idempotency), tested in the TS engine; here we prove the server's guards.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from osp_runtime import (
    ExternalTokenExpired,
    ExternalTokenInvalid,
    NotFoundError,
    SessionPolicy,
    SessionService,
)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@dataclass
class _Cred:
    session_id: str = "s1"
    tenant_id: str = "t"
    publication_id: str = "pub"
    submitted_at: datetime | None = None
    expired_at: datetime | None = None
    consented_at: datetime | None = None
    last_active_at: datetime = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


@dataclass
class _Pub:
    config: dict
    tenant_id: str = "t"
    publication_id: str = "pub"


class _Repo:
    """The two reads external_handoff / external_return make, nothing else."""

    def __init__(self, cred: _Cred, pub: _Pub) -> None:
        self._cred, self._pub = cred, pub

    def credential_by_token(self, token_hash: str):  # noqa: ANN201, ARG002
        return self._cred

    def get_publication(self, tenant_id: str, publication_id: str):  # noqa: ANN201, ARG002
        return self._pub


def _service(clock: Clock, external=("et1", "et2")) -> SessionService:
    cred = _Cred(last_active_at=clock.now)
    pub = _Pub(config={"surveyVersion": "1", "external": list(external)})
    return SessionService(
        _Repo(cred, pub), clock=clock, return_secret=b"k" * 32, policy=SessionPolicy()
    )


def test_handoff_mints_a_token_for_a_known_node():
    clock = Clock()
    svc = _service(clock)
    h = svc.external_handoff("s1", "tok", "et1")
    assert h.return_token.count(".") == 1
    assert h.expires_at == clock.now + SessionPolicy().external_token_ttl
    # A round trip verifies.
    ack = svc.external_return("s1", "tok", "et1", h.return_token)
    assert ack.node_id == "et1"


def test_handoff_refuses_a_node_that_is_not_an_external_task():
    svc = _service(Clock())
    with pytest.raises(NotFoundError):
        svc.external_handoff("s1", "tok", "not_a_node")


def test_return_refuses_a_node_that_is_not_an_external_task():
    svc = _service(Clock())
    h = svc.external_handoff("s1", "tok", "et1")
    with pytest.raises(NotFoundError):
        svc.external_return("s1", "tok", "nope", h.return_token)


def test_tampered_token_is_rejected():
    svc = _service(Clock())
    h = svc.external_handoff("s1", "tok", "et1")
    body, sig = h.return_token.split(".", 1)
    flipped = sig[:-1] + ("a" if sig[-1] != "a" else "b")
    with pytest.raises(ExternalTokenInvalid):
        svc.external_return("s1", "tok", "et1", f"{body}.{flipped}")
    # A changed payload (claiming a later expiry) also breaks the signature.
    with pytest.raises(ExternalTokenInvalid):
        svc.external_return("s1", "tok", "et1", "eyJmYWtlIjp0cnVlfQ." + sig)


def test_token_is_bound_to_its_node_so_it_cannot_be_replayed_elsewhere():
    """A token minted for one external node is useless at another (cross-context replay)."""
    svc = _service(Clock())
    for_et1 = svc.external_handoff("s1", "tok", "et1").return_token
    with pytest.raises(ExternalTokenInvalid):
        svc.external_return("s1", "tok", "et2", for_et1)


def test_token_is_bound_to_its_session():
    """A token signed for session s1 does not verify as session s2 (cross-session replay)."""
    svc = _service(Clock())
    for_s1 = svc.external_handoff("s1", "tok", "et1").return_token
    svc._verify_return(for_s1, "s1", "et1")  # the real session: ok
    with pytest.raises(ExternalTokenInvalid):
        svc._verify_return(for_s1, "s2", "et1")


def test_expired_token_is_rejected():
    clock = Clock()
    svc = _service(clock)
    h = svc.external_handoff("s1", "tok", "et1")
    clock.now = clock.now + SessionPolicy().external_token_ttl + timedelta(seconds=1)
    with pytest.raises(ExternalTokenExpired):
        svc.external_return("s1", "tok", "et1", h.return_token)


def test_malformed_tokens_are_rejected():
    svc = _service(Clock())
    for bad in ["", "no-dot", "a.b.c", "x" * 2000 + ".y"]:
        with pytest.raises(ExternalTokenInvalid):
            svc.external_return("s1", "tok", "et1", bad)


def test_a_different_signing_key_does_not_verify():
    clock = Clock()
    minted = _service(clock).external_handoff("s1", "tok", "et1").return_token
    other = SessionService(
        _Repo(_Cred(last_active_at=clock.now), _Pub({"surveyVersion": "1", "external": ["et1"]})),
        clock=clock,
        return_secret=b"other-key-32-bytes-xxxxxxxxxxxxx",
    )
    with pytest.raises(ExternalTokenInvalid):
        other.external_return("s1", "tok", "et1", minted)
