"""The proxy in docs/hosting.md, without Django: a host signs in the researcher, checks
CSRF, strips the browser's headers, signs with ``sign_identity_headers`` and forwards to
osp-api. Keep ``proxy`` below in step with the Django ``osp_api_proxy`` view in the doc."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from osp_api.app import create_app
from osp_api.identity import TrustedHeaders, parse_keyring
from osp_api.signing import sign_identity_headers
from osp_app import build_services
from osp_store import Keyring, Store, create_engine, migrate

STORE_KEY = "a" * 43 + "="
OSP_IDENTITY_KEYS = "host1:test-only-identity-secret-0123456789abcdef"  # never a real key
KEY_ID, SECRET = OSP_IDENTITY_KEYS.split(":", 1)

# -- the host side (what the Django view in docs/hosting.md does) ---------------------------

PREFIX = "/osp/api/"  # where the host mounts the API; osp-api itself serves /api/
SAFE = {"GET", "HEAD", "OPTIONS"}
# An allowlist: X-OSP-*, cookies, Authorization and Origin never reach osp-api.
REQUEST_HEADERS = ("content-type", "accept")
RESPONSE_HEADERS = ("content-type", "content-disposition", "cache-control")


@dataclass
class HostUser:
    id: str
    name: str
    labs: dict[str, str] = field(default_factory=dict)  # lab id -> owner/editor/viewer


@dataclass
class HostRequest:
    method: str
    full_path: str  # path + query, as the browser sent it
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    user: HostUser | None = None  # from the host's own session
    csrf_ok: bool = True  # the host's own CSRF check passed


def proxy(
    upstream: httpx.Client, req: HostRequest, request_headers: tuple[str, ...] = REQUEST_HEADERS
) -> tuple[int, dict[str, str], bytes]:
    if req.user is None:
        return 401, {"content-type": "application/json"}, b'{"code":"unauthenticated"}'
    if req.method not in SAFE and not req.csrf_ok:
        return 403, {"content-type": "application/json"}, b'{"code":"csrf"}'
    path = "/api/" + req.full_path.removeprefix(PREFIX)
    headers = {k: v for k, v in req.headers.items() if k.lower() in request_headers}
    headers.update(
        sign_identity_headers(
            key_id=KEY_ID,
            secret=SECRET,
            method=req.method,
            path=path,
            body=req.body,
            user_id=req.user.id,
            roles=req.user.labs,
            display_name=req.user.name,
        )
    )
    r = upstream.request(req.method, path, content=req.body or None, headers=headers)
    out = {k: r.headers[k] for k in RESPONSE_HEADERS if k in r.headers}
    return r.status_code, out, r.content


# -- osp-api, as `osp-api serve` builds it ----------------------------------------------------


def _osp_api(tmp_path, allowed_origins: tuple[str, ...] = ()) -> TestClient:
    engine = create_engine(f"sqlite:///{tmp_path / 'host.db'}")
    migrate(engine)
    services = build_services(Store(engine, Keyring({"k1": STORE_KEY}, active="k1")))
    identity = TrustedHeaders(parse_keyring(OSP_IDENTITY_KEYS))  # real clock, real nonces
    app = create_app(builder=services, identity=identity, allowed_origins=allowed_origins)
    return TestClient(app, base_url="http://127.0.0.1:8000")


@pytest.fixture
def upstream(tmp_path) -> TestClient:
    return _osp_api(tmp_path)


ADA = HostUser("u-17", "Ada Lovelace", {"psych-lab": "editor"})
JSON = {"content-type": "application/json"}


def _json(resp: tuple[int, dict[str, str], bytes]):
    return json.loads(resp[2])


def test_a_researcher_creates_and_lists_a_survey_through_the_host(upstream):
    body = json.dumps({"title": "Sleep study"}).encode()
    status, headers, _ = created = proxy(
        upstream, HostRequest("POST", "/osp/api/surveys", body, JSON, ADA)
    )
    assert status == 201, created
    assert headers["content-type"] == "application/json"
    survey = _json(created)
    assert survey["tenantId"] == "psych-lab"  # the lab was created on first sight
    assert survey["createdBy"] == "u-17"

    listed = proxy(upstream, HostRequest("GET", "/osp/api/surveys", user=ADA))
    assert listed[0] == 200
    assert [s["id"] for s in _json(listed)] == [survey["id"]]

    me = _json(proxy(upstream, HostRequest("GET", "/osp/api/me", user=ADA)))
    assert me["userId"] == "u-17" and me["displayName"] == "Ada Lovelace"


def test_forged_identity_headers_from_the_browser_are_stripped(upstream):
    forged = {"X-OSP-User": "admin", "X-OSP-Roles": "psych-lab:owner", **JSON}
    me = _json(proxy(upstream, HostRequest("GET", "/osp/api/me", headers=forged, user=ADA)))
    assert me["userId"] == "u-17"
    assert [m["role"] for m in me["memberships"]] == ["editor"]


def test_unsigned_x_osp_user_sent_straight_to_osp_api_is_refused(upstream):
    forged = {"X-OSP-User": "u-17", "X-OSP-Roles": "psych-lab:owner"}
    assert upstream.get("/api/surveys", headers=forged).status_code == 401
    r = upstream.post("/api/surveys", json={"title": "x"}, headers=forged)
    assert r.status_code == 401


def test_the_host_refuses_before_forwarding(upstream):
    assert proxy(upstream, HostRequest("GET", "/osp/api/surveys"))[0] == 401  # no session
    body = json.dumps({"title": "x"}).encode()
    bad_csrf = HostRequest("POST", "/osp/api/surveys", body, JSON, ADA, csrf_ok=False)
    assert proxy(upstream, bad_csrf)[0] == 403
    assert _json(proxy(upstream, HostRequest("GET", "/osp/api/surveys", user=ADA))) == []


def test_a_query_string_is_signed_and_forwarded(upstream):
    survey = _json(
        proxy(
            upstream,
            HostRequest("POST", "/osp/api/surveys", b'{"title":"Q"}', JSON, ADA),
        )
    )
    path = f"/osp/api/surveys/{survey['id']}/export-check?target=lss"
    status, _, content = proxy(upstream, HostRequest("GET", path, user=ADA))
    assert status == 200, content


def test_forwarding_origin_keeps_osp_apis_check_with_allowed_origins(tmp_path):
    """docs/hosting.md: forward Origin too and list the public origin in OSP_ALLOWED_ORIGINS."""
    upstream = _osp_api(tmp_path, ("https://uni.example",))
    forward = (*REQUEST_HEADERS, "origin")
    body = b'{"title":"O"}'
    ok = HostRequest(
        "POST", "/osp/api/surveys", body, {**JSON, "Origin": "https://uni.example"}, ADA
    )
    assert proxy(upstream, ok, forward)[0] == 201
    evil = HostRequest(
        "POST", "/osp/api/surveys", body, {**JSON, "Origin": "https://x.example"}, ADA
    )
    assert proxy(upstream, evil, forward)[0] == 403
