"""Identity providers (plan P, planning/pages-split.md D2, D12): signed headers, in-process
callables, the dev identity."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from osp_api.identity import (
    Dev,
    IdentityConfigError,
    InProcess,
    NonceCache,
    TrustedHeaders,
    parse_keyring,
)
from osp_api.signing import H_NAME, H_ROLES, H_USER, canonical_query, sign_identity_headers
from osp_app import Identity
from osp_app.auth import Actor, Role

NOW = 1_800_000_000
K1 = "k1-secret-for-tests-only-0123456789abcdef"
K2 = "k2-secret-for-tests-only-0123456789abcdef"
PATH = "/api/echo/thing"


class Clock:
    def __init__(self) -> None:
        self.t = float(NOW)

    def __call__(self) -> float:
        return self.t


def _echo_app(provider) -> FastAPI:
    app = FastAPI()

    @app.api_route("/api/echo/{x}", methods=["GET", "POST", "DELETE"])
    async def echo(request: Request) -> JSONResponse:
        ident = await provider.identify(request)
        if ident is None:
            return JSONResponse({"who": None}, status_code=401)
        return JSONResponse(
            {
                "who": ident.actor.user_id,
                "roles": {k: str(v) for k, v in ident.actor.roles.items()},
                "name": ident.display_name,
            }
        )

    return app


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def th(clock) -> TrustedHeaders:
    return TrustedHeaders({"k1": K1}, clock=clock)


@pytest.fixture
def client(th) -> TestClient:
    return TestClient(_echo_app(th))


def _sign(method="GET", path=PATH, body=b"", **kw):
    args = {
        "key_id": "k1",
        "secret": K1,
        "method": method,
        "path": path,
        "body": body,
        "user_id": "u-1",
        "roles": {"lab-a": "editor"},
        "display_name": "Ada Lovelace",
        "timestamp": NOW,
    }
    args.update(kw)
    return sign_identity_headers(**args)


def _send(client, method="GET", path=PATH, body=b"", headers=None):
    hdrs = dict(headers or {})
    if body:
        hdrs.setdefault("Content-Type", "application/json")
    return client.request(method, path, content=body or None, headers=hdrs)


def test_good_signature_is_accepted(client):
    r = _send(client, headers=_sign())
    assert r.status_code == 200
    assert r.json() == {"who": "u-1", "roles": {"lab-a": "editor"}, "name": "Ada Lovelace"}


def test_post_body_and_query_are_covered(client):
    body = json.dumps({"x": 1}).encode()
    hdrs = _sign("POST", PATH + "?b=2&a=1", body)
    assert _send(client, "POST", PATH + "?a=1&b=2", body, hdrs).status_code == 200  # order-free
    hdrs = _sign("POST", PATH + "?a=1", body)
    assert _send(client, "POST", PATH + "?a=2", body, hdrs).status_code == 401


def test_unsigned_request_is_refused(client):
    assert _send(client).status_code == 401
    assert _send(client, headers={H_USER: "u-1", H_ROLES: "lab-a:owner"}).status_code == 401


@pytest.mark.parametrize("offset", [-61, 61, 3600])
def test_stale_or_future_timestamp_is_refused(client, offset):
    assert _send(client, headers=_sign(timestamp=NOW + offset)).status_code == 401


def test_within_skew_is_accepted(client):
    assert _send(client, headers=_sign(timestamp=NOW - 59)).status_code == 200


def test_replayed_nonce_is_refused(client, clock):
    hdrs = _sign(nonce="n" * 22)
    assert _send(client, headers=hdrs).status_code == 200
    assert _send(client, headers=hdrs).status_code == 401
    clock.t += 50  # still within skew, still remembered
    assert _send(client, headers=hdrs).status_code == 401


def test_nonce_cache_forgets_after_its_ttl_and_refuses_when_full():
    cache = NonceCache(ttl=120, max_size=2)
    assert cache.add("a", 0) and not cache.add("a", 119)
    assert cache.add("a", 121)  # expired, so new again (the timestamp check stops reuse)
    assert cache.add("b", 121) and not cache.add("c", 121)  # full of live nonces: refuse


def test_wrong_path_is_refused(client):
    assert _send(client, path="/api/echo/other", headers=_sign()).status_code == 401


def test_wrong_method_is_refused(client):
    assert _send(client, "DELETE", headers=_sign("GET")).status_code == 401


def test_tampered_body_is_refused(client):
    hdrs = _sign("POST", body=b'{"title": "a"}')
    assert _send(client, "POST", body=b'{"title": "b"}', headers=hdrs).status_code == 401


def test_tampered_roles_user_or_name_are_refused(client):
    for header, value in ((H_ROLES, "lab-a:owner"), (H_USER, "u-2"), (H_NAME, "Mallory")):
        hdrs = _sign()
        hdrs[header] = value
        assert _send(client, headers=hdrs).status_code == 401, header
    hdrs = _sign(display_name=None)
    hdrs[H_NAME] = "Mallory"  # adding a name that wasn't signed
    assert _send(client, headers=hdrs).status_code == 401


def test_unknown_key_id_is_refused(client):
    assert _send(client, headers=_sign(key_id="k9")).status_code == 401
    hdrs = _sign()
    hdrs["X-OSP-Key-Id"] = "k9"
    assert _send(client, headers=hdrs).status_code == 401


def test_rotated_key_is_accepted_alongside_the_old_one(clock):
    c = TestClient(_echo_app(TrustedHeaders(parse_keyring(f"k1:{K1}, k2:{K2}"), clock=clock)))
    assert _send(c, headers=_sign()).status_code == 200
    assert _send(c, headers=_sign(key_id="k2", secret=K2)).status_code == 200
    assert _send(c, headers=_sign(key_id="k2", secret=K1)).status_code == 401  # wrong pairing
    retired = TestClient(_echo_app(TrustedHeaders(parse_keyring(f"k2:{K2}"), clock=clock)))
    assert _send(retired, headers=_sign()).status_code == 401  # old key gone


@pytest.mark.parametrize(
    "roles",
    [{"lab-a": "superuser"}, {"lab-a": "Owner"}, {"lab,a": "owner"}, {"x" * 37: "owner"}],
)
def test_bad_roles_are_refused_even_when_signed(client, roles):
    assert _send(client, headers=_sign(roles=roles)).status_code == 401


@pytest.mark.parametrize("user", ["", "system:retention", "x" * 65, "a b"])
def test_bad_user_ids_are_refused_even_when_signed(client, user):
    assert _send(client, headers=_sign(user_id=user)).status_code == 401


def test_unicode_display_name_survives_and_long_ones_are_refused(client):
    r = _send(client, headers=_sign(display_name="Zoë Ångström 李"))
    assert r.json()["name"] == "Zoë Ångström 李"
    assert _send(client, headers=_sign(display_name="x" * 201)).status_code == 401


def test_no_labs_is_a_valid_identity(client):
    r = _send(client, headers=_sign(roles={}))
    assert r.status_code == 200 and r.json()["roles"] == {}


def test_duplicated_identity_header_is_refused(th, client):
    hdrs = list(_sign().items()) + [(H_USER, "u-2")]
    r = client.get(PATH, headers=hdrs)
    assert r.status_code == 401


def test_malformed_signature_and_timestamp(client):
    for header, value in (("X-OSP-Signature", "zz"), ("X-OSP-Timestamp", "soon")):
        hdrs = _sign()
        hdrs[header] = value
        assert _send(client, headers=hdrs).status_code == 401


def test_canonical_query_sorts_and_encodes():
    assert canonical_query("b=2&a=1&a=0") == "a=0&a=1&b=2"
    assert canonical_query("q=a b&x=%2F") == "q=a%20b&x=%2F"
    assert canonical_query("") == ""


@pytest.mark.parametrize("text", ["", "k1", "k1:short", "bad id:" + K1, f"k1:{K1},k1:{K2}"])
def test_bad_keyrings_are_refused(text):
    with pytest.raises(IdentityConfigError):
        parse_keyring(text)


# -- InProcess -------------------------------------------------------------------------------


def test_in_process_sync_and_async_callables():
    def sync_host(request: Request):
        if request.headers.get("x-host-session") != "ok":
            return None
        return Identity(Actor("django-7", {"lab-a": Role.OWNER}), "Grace")

    async def async_host(request: Request):
        return Actor("django-8", {"lab-b": "viewer"})

    c = TestClient(_echo_app(InProcess(sync_host)))
    assert c.get(PATH).status_code == 401
    r = c.get(PATH, headers={"x-host-session": "ok"})
    assert r.json() == {"who": "django-7", "roles": {"lab-a": "owner"}, "name": "Grace"}
    r = TestClient(_echo_app(InProcess(async_host))).get(PATH)
    assert r.json()["who"] == "django-8" and r.json()["roles"] == {"lab-b": "viewer"}


@pytest.mark.parametrize(
    "result",
    [Actor("u", {"lab": "superuser"}), Actor("system:x", {}), "u-1", {"user": "u"}],
)
def test_in_process_output_is_checked_like_any_host(result):
    c = TestClient(_echo_app(InProcess(lambda request: result)))
    assert c.get(PATH).status_code == 401


# -- Dev (D12) -----------------------------------------------------------------------------


def test_dev_identity_is_the_dev_lab_owner():
    r = TestClient(_echo_app(Dev(env="dev", host="127.0.0.1"))).get(PATH)
    assert r.json()["who"] == "dev-researcher" and r.json()["roles"] == {"dev-lab": "owner"}


@pytest.mark.parametrize(
    ("env", "host"),
    [("production", "127.0.0.1"), ("", "127.0.0.1"), ("dev", "0.0.0.0"), ("dev", "10.0.0.5")],
)
def test_dev_refuses_outside_dev_or_off_loopback(env, host):
    with pytest.raises(IdentityConfigError):
        Dev(env=env, host=host)
