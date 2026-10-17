"""osp-host-signing (what hosts install) against osp-api's verifier (task H2c): one
implementation, and headers signed by the package are accepted by TrustedHeaders."""

from __future__ import annotations

import json

import osp_host_signing
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from osp_api import signing
from osp_api.identity import TrustedHeaders

SECRET = "crosscheck-secret-for-tests-only-0123456789"


def test_osp_api_signing_is_the_package() -> None:
    for name in osp_host_signing.__all__:
        assert getattr(signing, name) is getattr(osp_host_signing, name), name
    assert set(signing.__all__) == set(osp_host_signing.__all__)


@pytest.fixture
def client() -> TestClient:
    provider = TrustedHeaders({"host1": SECRET})
    app = FastAPI()

    @app.api_route("/api/echo/{x}", methods=["GET", "POST"])
    async def echo(request: Request) -> JSONResponse:
        ident = await provider.identify(request)
        if ident is None:
            return JSONResponse({}, status_code=401)
        return JSONResponse({"who": ident.actor.user_id, "name": ident.display_name})

    return TestClient(app)


@pytest.mark.parametrize(
    ("method", "path", "body", "name"),
    [
        ("GET", "/api/echo/x", b"", None),
        ("GET", "/api/echo/a%20b?z=1&a=%C3%A9&a=", b"", "Zoë"),
        ("POST", "/api/echo/x?target=lss", json.dumps({"k": "ü"}).encode(), "O'Neil, A."),
    ],
)
def test_package_signed_headers_verify(client, method, path, body, name) -> None:
    headers = osp_host_signing.sign_identity_headers(
        key_id="host1",
        secret=SECRET,
        method=method,
        path=path,
        body=body,
        user_id="host-user-7",
        roles={"lab-b": "viewer", "lab-a": "owner"},
        display_name=name,
    )
    if body:
        headers["Content-Type"] = "application/json"
    r = client.request(method, path, content=body or None, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"who": "host-user-7", "name": name}


def test_tampered_body_is_refused(client) -> None:
    headers = osp_host_signing.sign_identity_headers(
        key_id="host1",
        secret=SECRET,
        method="POST",
        path="/api/echo/x",
        body=b'{"a":1}',
        user_id="u",
        roles={},
    )
    r = client.post("/api/echo/x", content=b'{"a":2}', headers=headers)
    assert r.status_code == 401
