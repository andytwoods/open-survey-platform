"""Builder API security: fail-closed access on every route, login + TOTP, cookies, CSRF."""

from __future__ import annotations

import pytest
from osp_app.auth import totp

from .conftest import PASSWORD

SID = "{sid}"

# Every builder route: (method, path, json body). Paths with {sid} target lab A's survey.
ROUTES: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/auth/me", None),
    ("POST", "/api/auth/logout", None),
    ("POST", "/api/auth/totp/enrol", None),
    ("POST", "/api/auth/totp/verify", {"code": "000000"}),
    ("GET", "/api/surveys", None),
    ("POST", "/api/surveys", {"title": "x"}),
    ("GET", f"/api/surveys/{SID}", None),
    ("DELETE", f"/api/surveys/{SID}", None),
    ("GET", f"/api/surveys/{SID}/history", None),
    ("POST", f"/api/surveys/{SID}/ops", {"ops": [], "baseRevision": 0}),
    ("POST", f"/api/surveys/{SID}/undo", {"transactionId": "t", "baseRevision": 0}),
    ("POST", f"/api/surveys/{SID}/redo", {"transactionId": "u:t", "baseRevision": 0}),
    ("POST", f"/api/surveys/{SID}/publish", {}),
    ("GET", f"/api/surveys/{SID}/export/xlsform", None),
    ("GET", f"/api/surveys/{SID}/export/responses", None),
    ("GET", f"/api/surveys/{SID}/export/codebook", None),
    ("DELETE", f"/api/surveys/{SID}/responses/{{response_id}}", None),
    ("GET", "/api/meta/ops", None),
    ("GET", "/api/meta/property-schemas", None),
    ("GET", "/api/meta/survey-schema", None),
    ("GET", "/api/meta/theme-schema", None),
    ("POST", "/api/meta/expressions/parse", {"text": "a > 1"}),
    ("POST", "/api/meta/expressions/print", {"ast": {"kind": "null"}}),
]
SURVEY_ROUTES = [r for r in ROUTES if SID in r[1]]
WRITE_SURVEY_ROUTES = [r for r in SURVEY_ROUTES if r[0] != "GET"]
PUBLIC = {"/api/health", "/api/version", "/api/auth/login", "/api/auth/login/totp"}


def _ids(routes):
    return [f"{m} {p}" for m, p, _ in routes]


def _call(c, method, path, body, sid="0" * 36):
    return c.request(method, path.replace(SID, sid), json=body)


@pytest.fixture
def survey_a(benv) -> str:
    c = benv.login("owner@a.example")
    r = c.post("/api/surveys", json={"title": "Lab A study"})
    assert r.status_code == 201
    return r.json()["id"]


def test_route_list_covers_every_builder_route(benv):
    """Adding a builder route without adding it here fails: no route escapes the matrix."""
    app_routes = {
        (method.upper(), path.replace("{survey_id}", SID))
        for path, item in benv.app.openapi()["paths"].items()
        for method, op in item.items()
        if set(op.get("tags", ())) & {"auth", "surveys", "ops", "meta"}
    }
    listed = {(m, p) for m, p, _ in ROUTES}
    assert {(m, p) for m, p in app_routes if p not in PUBLIC} == listed


@pytest.mark.parametrize(("method", "path", "body"), ROUTES, ids=_ids(ROUTES))
def test_anonymous_is_refused_everywhere(benv, survey_a, method, path, body):
    r = _call(benv.client(), method, path, body, survey_a)
    assert r.status_code == 401, r.text


@pytest.mark.parametrize(("method", "path", "body"), ROUTES, ids=_ids(ROUTES))
def test_forged_or_expired_session_is_refused(benv, survey_a, method, path, body):
    c = benv.client()
    c.cookies.set("__Host-osp_session", "forged-token", domain="testserver")
    assert _call(c, method, path, body, survey_a).status_code == 401
    real = benv.login("owner@a.example")
    benv.clock.advance(hours=13)  # beyond the absolute lifetime
    assert _call(real, method, path, body, survey_a).status_code == 401


@pytest.mark.parametrize(("method", "path", "body"), SURVEY_ROUTES, ids=_ids(SURVEY_ROUTES))
def test_other_tenant_gets_not_found(benv, survey_a, method, path, body):
    """Lab B's owner can't read, edit, publish, export or delete lab A's survey, and
    can't even tell it exists (404, the same as a random id)."""
    c = benv.login("owner@b.example")
    r = _call(c, method, path, body, survey_a)
    assert r.status_code == 404, r.text
    assert _call(c, method, path, body).status_code == 404  # random id: same answer
    owner = benv.login("owner@a.example")
    assert owner.get(f"/api/surveys/{survey_a}").json()["revision"] == 0  # untouched


def test_other_tenant_list_is_empty(benv, survey_a):
    assert benv.login("owner@b.example").get("/api/surveys").json() == []


@pytest.mark.parametrize(
    ("method", "path", "body"), WRITE_SURVEY_ROUTES, ids=_ids(WRITE_SURVEY_ROUTES)
)
def test_viewer_cannot_write(benv, survey_a, method, path, body):
    c = benv.login("viewer@a.example")
    assert _call(c, method, path, body, survey_a).status_code == 403
    assert c.get(f"/api/surveys/{survey_a}").status_code == 200  # but can read


def test_viewer_cannot_create_or_export(benv, survey_a):
    c = benv.login("viewer@a.example")
    assert c.post("/api/surveys", json={"title": "x"}).status_code == 403
    assert c.get(f"/api/surveys/{survey_a}/export/xlsform").status_code == 403
    assert c.get(f"/api/surveys/{survey_a}/export/responses").status_code == 403
    assert c.get(f"/api/surveys/{survey_a}/export/codebook").status_code == 403


def test_unknown_role_fails_closed(benv, survey_a):
    from osp_store import TenantContext

    uid = benv.users["editor@a.example"]
    c = benv.login("editor@a.example")
    benv.store.set_role(TenantContext(benv.tenants["A"], "system:test"), uid, "superuser")
    assert c.get(f"/api/surveys/{survey_a}").status_code == 404
    assert c.get("/api/surveys").json() == []


# -- login, cookies, TOTP ------------------------------------------------------------------


def test_login_sets_hardened_cookies(benv):
    r = benv.client().post(
        "/api/auth/login", json={"email": "owner@a.example", "password": PASSWORD}
    )
    assert r.status_code == 200
    cookies = r.headers.get_list("set-cookie")
    session = next(h for h in cookies if h.startswith("__Host-osp_session="))
    csrf = next(h for h in cookies if h.startswith("__Host-osp_csrf="))
    for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert flag.lower() in session.lower()
    assert "httponly" not in csrf.lower() and "secure" in csrf.lower()
    assert r.json()["me"]["email"] == "owner@a.example"


@pytest.mark.parametrize(
    "creds",
    [
        {"email": "owner@a.example", "password": "wrong password but long"},
        {"email": "nobody@a.example", "password": PASSWORD},
    ],
)
def test_login_failure_is_uniform(benv, creds):
    r = benv.client().post("/api/auth/login", json=creds)
    assert r.status_code == 401
    assert r.json()["message"] == "Sign-in failed. Check your details and try again."
    assert "set-cookie" not in r.headers


def test_logout_revokes_the_session(benv):
    c = benv.login("owner@a.example")
    token = c.cookies.get("__Host-osp_session")
    assert c.post("/api/auth/logout").status_code == 204
    replay = benv.client()
    replay.cookies.set("__Host-osp_session", token, domain="testserver")
    assert replay.get("/api/auth/me").status_code == 401


def test_totp_enrolment_and_login(benv):
    c = benv.login("owner@a.example")
    old_token = c.cookies.get("__Host-osp_session")
    enrol = c.post("/api/auth/totp/enrol")
    assert enrol.status_code == 200
    secret = enrol.json()["secret"]
    assert enrol.json()["provisioningUri"].startswith("otpauth://totp/")

    assert c.post("/api/auth/totp/verify", json={"code": "000000"}).status_code == 422
    ok = c.post("/api/auth/totp/verify", json={"code": totp.totp(secret, benv.clock.now())})
    assert ok.status_code == 200, ok.text
    codes = ok.json()["recoveryCodes"]
    assert len(codes) == 10
    assert c.cookies.get("__Host-osp_session") != old_token  # rotated
    c.headers["X-CSRF-Token"] = ok.json()["csrfToken"]
    me = c.get("/api/auth/me").json()
    assert me["totpEnrolled"] is True

    # Password alone is no longer enough.
    fresh = benv.client()
    r = fresh.post("/api/auth/login", json={"email": "owner@a.example", "password": PASSWORD})
    assert r.json() == {"status": "mfa_required", "me": None}
    assert fresh.get("/api/auth/me").status_code == 401
    assert fresh.post("/api/auth/login/totp", json={"code": "123456"}).status_code == 401

    benv.clock.advance(seconds=30)  # next step (the enrolment code can't be replayed)
    r = fresh.post("/api/auth/login/totp", json={"code": totp.totp(secret, benv.clock.now())})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"
    fresh.headers["X-CSRF-Token"] = r.json()["me"]["csrfToken"]
    assert fresh.get("/api/surveys").status_code == 200

    # Recovery code path, single use.
    other = benv.client()
    other.post("/api/auth/login", json={"email": "owner@a.example", "password": PASSWORD})
    r = other.post("/api/auth/login/totp", json={"code": codes[0], "recovery": True})
    assert r.status_code == 200
    again = benv.client()
    again.post("/api/auth/login", json={"email": "owner@a.example", "password": PASSWORD})
    r = again.post("/api/auth/login/totp", json={"code": codes[0], "recovery": True})
    assert r.status_code == 401


def test_totp_step_needs_the_challenge_cookie(benv):
    r = benv.client().post("/api/auth/login/totp", json={"code": "123456"})
    assert r.status_code == 401


# -- CSRF ----------------------------------------------------------------------------------


def test_csrf_header_required_for_unsafe_methods(benv):
    c = benv.login("editor@a.example")
    del c.headers["X-CSRF-Token"]
    r = c.post("/api/surveys", json={"title": "x"})
    assert r.status_code == 403 and "CSRF" in r.json()["message"]
    assert c.get("/api/surveys").status_code == 200  # safe methods don't need it


def test_csrf_token_of_another_session_is_rejected(benv):
    mine = benv.login("editor@a.example")
    theirs = benv.login("owner@a.example")
    mine.headers["X-CSRF-Token"] = theirs.headers["X-CSRF-Token"]
    assert mine.post("/api/surveys", json={"title": "x"}).status_code == 403
    mine.headers["X-CSRF-Token"] = "garbage"
    assert mine.post("/api/surveys", json={"title": "x"}).status_code == 403


def test_cross_origin_request_is_rejected_even_with_token(benv):
    c = benv.login("editor@a.example")
    r = c.post("/api/surveys", json={"title": "x"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = c.post("/api/surveys", json={"title": "x"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = c.post("/api/surveys", json={"title": "x"}, headers={"Origin": "https://testserver"})
    assert r.status_code == 201


def test_login_csrf_guards(benv):
    c = benv.client()
    creds = {"email": "owner@a.example", "password": PASSWORD}
    r = c.post("/api/auth/login", json=creds, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    import json

    r = c.post("/api/auth/login", content=json.dumps(creds), headers={"Content-Type": "text/plain"})
    assert r.status_code == 415
    assert "set-cookie" not in r.headers
