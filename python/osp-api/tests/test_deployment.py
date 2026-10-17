"""Running behind a host (planning/pages-split.md D13-D16): participant addresses from
trusted proxies, public origins for the Origin check, the shared nonce store."""

from __future__ import annotations

import ipaddress

import pytest
from fastapi.testclient import TestClient
from osp_api.app import create_app
from osp_api.client_address import (
    TrustedProxiesError,
    forwarded_client,
    parse_trusted_proxies,
    rate_limit_key,
)
from osp_api.identity import DatabaseNonces, NonceCache, TrustedHeaders
from osp_api.serve import ConfigError, Settings, build_app
from osp_api.signing import sign_identity_headers
from osp_runtime import SessionService
from osp_store import NonceLedger

from .conftest import KEY_ID, SECRET, SignAs
from .test_participant import Env

# -- D13: the participant address behind a proxy ---------------------------------------------

PROXIES = parse_trusted_proxies("10.0.0.0/8, 192.168.1.1, fd00::/8")


def _client(peer: str | None, xff: list[str] | None = None, proxies=PROXIES) -> str | None:
    return rate_limit_key(forwarded_client(peer, xff or [], proxies))


def test_xff_from_an_untrusted_peer_is_ignored():
    assert _client("203.0.113.9", ["1.1.1.1"]) == "203.0.113.9"
    assert _client("203.0.113.9", ["1.1.1.1"], proxies=()) == "203.0.113.9"
    assert _client("10.0.0.5", ["1.1.1.1"], proxies=()) == "10.0.0.5"  # nothing trusted


def test_a_trusted_proxy_chain_gives_the_rightmost_untrusted_hop():
    # The client claims 6.6.6.6; the edge proxy appended the real peer; then an inner proxy.
    chain = ["6.6.6.6, 198.51.100.7, 10.1.2.3"]
    assert _client("10.0.0.5", chain) == "198.51.100.7"
    assert _client("192.168.1.1", ["198.51.100.7"]) == "198.51.100.7"
    # Several header lines are one list, in order.
    assert _client("10.0.0.5", ["6.6.6.6", "198.51.100.7, 10.1.2.3"]) == "198.51.100.7"
    # Every hop trusted: the left-most one.
    assert _client("10.0.0.5", ["10.9.9.9, 10.1.1.1"]) == "10.9.9.9"
    # No header: the proxy itself.
    assert _client("10.0.0.5", []) == "10.0.0.5"


def test_garbage_in_the_chain_stops_at_the_last_vouched_address():
    assert _client("10.0.0.5", ["198.51.100.7, not-an-ip"]) == "10.0.0.5"
    assert _client("10.0.0.5", ["not-an-ip, 198.51.100.7"]) == "198.51.100.7"
    assert _client("10.0.0.5", ["198.51.100.7:4711"]) == "198.51.100.7"  # with a port


def test_ipv6_is_matched_and_keyed_by_64():
    assert _client("fd00::1", ["2001:db8:1:2::aa"]) == "2001:db8:1:2::/64"
    assert _client("fd00::1", ["[2001:db8:1:2::bb]:443"]) == "2001:db8:1:2::/64"
    assert _client("2001:db8::1", ["198.51.100.7"]) == "2001:db8::/64"  # untrusted v6 peer
    assert _client("::ffff:10.0.0.5", ["198.51.100.7"]) == "198.51.100.7"  # v4-mapped peer
    assert parse_trusted_proxies("::ffff:10.0.0.0/104") == (ipaddress.ip_network("10.0.0.0/8"),)


@pytest.mark.parametrize("bad", ["10.0.0.0/33", "proxy.example", "*", "10.0.0.1-10.0.0.9"])
def test_bad_trusted_proxies_are_refused(bad):
    with pytest.raises(TrustedProxiesError):
        parse_trusted_proxies(bad)
    with pytest.raises(ConfigError, match="OSP_TRUSTED_PROXIES"):
        Settings.from_env({"OSP_TRUSTED_PROXIES": bad})


def _participants(tmp_path, peer: str, proxies: tuple[str, ...]) -> TestClient:
    env = Env(tmp_path)
    env.publish("demo")
    app = create_app(env.service, trusted_proxies=proxies)
    return TestClient(app, client=(peer, 50000))


def test_participants_behind_a_trusted_proxy_get_their_own_budget(tmp_path):
    c = _participants(tmp_path, "10.0.0.5", ("10.0.0.0/8",))
    ada = {"X-Forwarded-For": "198.51.100.7"}
    codes = [c.post("/api/s/demo/sessions", headers=ada).status_code for _ in range(11)]
    assert codes == [201] * 10 + [429]  # starts: a burst of 10 per participant
    bob = {"X-Forwarded-For": "198.51.100.8"}
    assert c.post("/api/s/demo/sessions", headers=bob).status_code == 201


def test_spoofed_xff_from_an_untrusted_peer_shares_the_peers_budget(tmp_path):
    c = _participants(tmp_path, "203.0.113.9", ("10.0.0.0/8",))
    codes = [
        c.post("/api/s/demo/sessions", headers={"X-Forwarded-For": f"198.51.100.{i}"}).status_code
        for i in range(11)
    ]
    assert codes == [201] * 10 + [429]


# -- D14: public origins pass the Origin check without CORS -----------------------------------


def _signed_app(benv, **kw):
    benv.app = create_app(builder=benv.services, identity=benv.identity, **kw)
    return benv.login("editor@a.example")


def test_public_origins_pass_the_origin_check_without_cors(benv):
    c = _signed_app(benv, public_origins=("https://uni.example",))
    pub = {"Origin": "https://uni.example", "Sec-Fetch-Site": "same-origin"}
    r = c.post("/api/surveys", json={"title": "x"}, headers=pub)
    assert r.status_code == 201
    assert "access-control-allow-origin" not in r.headers  # no CORS
    pre = c.options(
        "/api/surveys",
        headers={"Origin": "https://uni.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in pre.headers
    for bad in (
        {"Origin": "https://evil.example"},
        {"Origin": "https://uni.example", "Sec-Fetch-Site": "cross-site"},  # not honest
        {"Origin": "null"},
    ):
        assert c.post("/api/surveys", json={"title": "x"}, headers=bad).status_code == 403
    # Its own address still counts (unset behaves as before).
    own = {"Origin": "https://testserver"}
    assert c.post("/api/surveys", json={"title": "x"}, headers=own).status_code == 201


def test_allowed_origins_are_cors_and_pass_even_cross_site(benv):
    c = _signed_app(benv, allowed_origins=("https://app.example",))
    h = {"Origin": "https://app.example", "Sec-Fetch-Site": "cross-site"}
    r = c.post("/api/surveys", json={"title": "x"}, headers=h)
    assert r.status_code == 201
    assert r.headers["access-control-allow-origin"] == "https://app.example"
    evil = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
    assert c.post("/api/surveys", json={"title": "x"}, headers=evil).status_code == 403


def test_without_public_origins_a_forwarded_public_origin_is_refused(benv):
    c = _signed_app(benv)
    h = {"Origin": "https://uni.example"}
    assert c.post("/api/surveys", json={"title": "x"}, headers=h).status_code == 403


def test_in_process_scheme_mismatch_is_solved_by_public_origins(benv):
    """TLS ends in front of an in-process mount: the ASGI scope says http, the browser
    says https. Listing the public origin fixes it without trusting proxy headers."""
    benv.app = create_app(
        builder=benv.services, identity=benv.identity, public_origins=("https://uni.example",)
    )
    c = TestClient(benv.app, base_url="http://uni.example")
    c.auth = SignAs(benv, "editor@a.example")
    h = {"Origin": "https://uni.example"}
    assert c.post("/api/surveys", json={"title": "x"}, headers=h).status_code == 201


@pytest.mark.parametrize("bad", ["*", "https://uni.example/path", "uni.example"])
def test_bad_public_origins_are_refused(bad):
    with pytest.raises(ConfigError, match="OSP_PUBLIC_ORIGINS"):
        Settings.from_env({"OSP_PUBLIC_ORIGINS": bad})
    with pytest.raises(ValueError):
        create_app(public_origins=(bad,))


# -- D16: nonces shared through the database ------------------------------------------------


def _signed(benv, path="/api/me") -> dict[str, str]:
    return sign_identity_headers(
        key_id=KEY_ID,
        secret=SECRET,
        method="GET",
        path=path,
        body=b"",
        user_id="editor@a.example",
        roles=benv.roles["editor@a.example"],
        timestamp=int(benv.clock.now().timestamp()),
    )


def _worker(benv, nonces) -> TestClient:
    identity = TrustedHeaders(
        {KEY_ID: SECRET}, clock=lambda: benv.clock.now().timestamp(), nonces=nonces
    )
    return TestClient(create_app(builder=benv.services, identity=identity))


def test_a_replay_across_two_workers_sharing_the_database_is_refused(benv):
    engine = benv.store.engine
    one = _worker(benv, DatabaseNonces(NonceLedger(engine)))
    two = _worker(benv, DatabaseNonces(NonceLedger(engine)))
    headers = _signed(benv)
    assert one.get("/api/me", headers=headers).status_code == 200
    assert two.get("/api/me", headers=headers).status_code == 401
    assert one.get("/api/me", headers=headers).status_code == 401
    assert two.get("/api/me", headers=_signed(benv)).status_code == 200  # a fresh nonce


def test_in_memory_nonces_are_per_worker_the_documented_limit(benv):
    one, two = _worker(benv, NonceCache()), _worker(benv, NonceCache())
    headers = _signed(benv)
    assert one.get("/api/me", headers=headers).status_code == 200
    assert two.get("/api/me", headers=headers).status_code == 200  # why D16 exists


class Broken:
    def claim(self, *_a, **_k):
        raise RuntimeError("database down")


def test_a_failing_nonce_store_refuses(benv):
    w = _worker(benv, DatabaseNonces(Broken()))  # type: ignore[arg-type]
    assert w.get("/api/me", headers=_signed(benv)).status_code == 401


def test_nonce_store_defaults(tmp_path):
    assert Settings.from_env({}).nonce_store == "memory"
    prod = {"OSP_ENV": "production", "OSP_DATABASE_URL": "sqlite:///x.db"}
    assert Settings.from_env(prod).nonce_store == "database"
    assert Settings.from_env({**prod, "OSP_NONCE_STORE": "memory"}).nonce_store == "memory"
    with pytest.raises(ConfigError, match="OSP_NONCE_STORE"):
        Settings.from_env({"OSP_NONCE_STORE": "redis"})


def test_build_app_uses_the_database_nonce_store_in_production(tmp_path):
    env = {
        "OSP_ENV": "production",
        "OSP_DATABASE_URL": f"sqlite:///{tmp_path / 'p.db'}",
        "OSP_STORE_KEYS": "k1:" + "a" * 43 + "=",
        "OSP_IDENTITY_KEYS": f"{KEY_ID}:{SECRET}",
        "OSP_TRUSTED_PROXIES": "10.0.0.0/8",
        "OSP_PUBLIC_ORIGINS": "https://uni.example",
    }
    app = build_app(Settings.from_env(env), env)
    assert isinstance(app.state.identity, TrustedHeaders)
    assert isinstance(app.state.identity.nonces, DatabaseNonces)
    assert app.state.public_origins == ("https://uni.example",)
    assert app.state.trusted_proxies == (ipaddress.ip_network("10.0.0.0/8"),)
    assert isinstance(app.state.sessions, SessionService)
    headers = sign_identity_headers(
        key_id=KEY_ID,
        secret=SECRET,
        method="GET",
        path="/api/me",
        body=b"",
        user_id="u1",
        roles={"lab": "owner"},
    )
    c = TestClient(app)
    assert c.get("/api/me", headers=headers).status_code == 200
    assert c.get("/api/me", headers=headers).status_code == 401
