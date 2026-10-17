"""Builder API security: fail-closed access on every route under the host's identity
(plan P), origin and content-type guards."""

from __future__ import annotations

import json

import pytest

from .conftest import SignAs

SID = "{sid}"

# Every builder route: (method, path, json body). Paths with {sid} target lab A's survey.
ROUTES: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/me", None),
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
    ("GET", f"/api/surveys/{SID}/export/lss", None),
    ("GET", f"/api/surveys/{SID}/export/responses", None),
    ("GET", f"/api/surveys/{SID}/export/codebook", None),
    ("GET", f"/api/surveys/{SID}/versions/{{version}}/repro-package", None),
    ("DELETE", f"/api/surveys/{SID}/responses/{{response_id}}", None),
    ("POST", f"/api/surveys/{SID}/simulate", {"n": 1}),
    ("POST", f"/api/surveys/{SID}/preview-plan", None),
    ("GET", f"/api/surveys/{SID}/export-check?target=lss", None),
    ("POST", f"/api/surveys/{SID}/results/query", {"cards": [{"question": "q1"}]}),
    ("GET", f"/api/surveys/{SID}/results/text/{{question}}", None),
    (
        "POST",
        f"/api/surveys/{SID}/results/export",
        {"query": {}, "cards": ["q1"], "formats": ["svg"]},
    ),
    ("GET", "/api/themes", None),
    ("POST", "/api/themes", {"name": "x", "theme": {}}),
    ("PUT", "/api/themes/default", {"themeId": None}),
    ("GET", "/api/themes/{theme_id}", None),
    ("PATCH", "/api/themes/{theme_id}", {"name": "x"}),
    ("DELETE", "/api/themes/{theme_id}", None),
    ("GET", "/api/meta/ops", None),
    ("GET", "/api/meta/property-schemas", None),
    ("GET", "/api/meta/survey-schema", None),
    ("GET", "/api/meta/theme-schema", None),
    ("GET", "/api/meta/retention", None),
    ("GET", "/api/meta/targets", None),
    ("POST", "/api/meta/expressions/parse", {"text": "a > 1"}),
    ("POST", "/api/meta/expressions/print", {"ast": {"kind": "null"}}),
]
SURVEY_ROUTES = [r for r in ROUTES if SID in r[1]]
WRITE_SURVEY_ROUTES = [r for r in SURVEY_ROUTES if r[0] != "GET"]
PUBLIC = {"/api/health", "/api/version"}


def _ids(routes):
    return [f"{m} {p}" for m, p, _ in routes]


def _call(c, method, path, body, sid="0" * 36):
    # `{version}` is an integer path parameter: a real number, so auth is what answers.
    return c.request(method, path.replace(SID, sid).replace("{version}", "1"), json=body)


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
        if set(op.get("tags", ())) & {"me", "surveys", "ops", "meta", "themes", "results"}
    }
    listed = {(m, p.split("?")[0]) for m, p, _ in ROUTES}
    assert {(m, p) for m, p in app_routes if p not in PUBLIC} == listed


@pytest.mark.parametrize(("method", "path", "body"), ROUTES, ids=_ids(ROUTES))
def test_anonymous_is_refused_everywhere(benv, survey_a, method, path, body):
    r = _call(benv.client(), method, path, body, survey_a)
    assert r.status_code == 401, r.text


@pytest.mark.parametrize(("method", "path", "body"), ROUTES, ids=_ids(ROUTES))
def test_forged_or_stale_identity_is_refused(benv, survey_a, method, path, body):
    forged = benv.client()
    forged.auth = SignAs(benv, "owner@a.example", secret="not-the-shared-secret-at-all-0123")
    assert _call(forged, method, path, body, survey_a).status_code == 401
    unsigned = benv.client()
    unsigned.headers.update({"X-OSP-User": "owner@a.example", "X-OSP-Roles": "lab-a:owner"})
    assert _call(unsigned, method, path, body, survey_a).status_code == 401
    real = benv.login("owner@a.example")
    identity_clock = benv.identity.clock
    benv.identity.clock = lambda: identity_clock() + 61  # the request is now stale
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
    assert c.post(f"/api/surveys/{survey_a}/results/query", json={}).status_code == 403
    assert c.get(f"/api/surveys/{survey_a}/results/text/q1").status_code == 403
    export = {"query": {}, "cards": ["q1"], "formats": ["png"]}
    assert c.post(f"/api/surveys/{survey_a}/results/export", json=export).status_code == 403


def test_unknown_role_fails_closed(benv, survey_a):
    c = benv.login("editor@a.example")
    benv.roles["editor@a.example"] = {benv.tenants["A"]: "superuser"}
    assert c.get(f"/api/surveys/{survey_a}").status_code == 401  # strict role names
    assert c.get("/api/surveys").status_code == 401


def test_roles_come_from_the_host_on_every_request(benv, survey_a):
    c = benv.login("editor@a.example")
    assert c.get(f"/api/surveys/{survey_a}").status_code == 200
    benv.roles["editor@a.example"] = {}  # the host removed them from the lab
    assert c.get(f"/api/surveys/{survey_a}").status_code == 404
    assert c.get("/api/surveys").json() == []
    benv.roles["editor@a.example"] = {benv.tenants["B"]: "owner"}  # moved to lab B
    assert c.get(f"/api/surveys/{survey_a}").status_code == 404


def test_a_lab_is_created_on_first_sight(benv):
    benv.roles["new@c.example"] = {"lab-c": "owner"}
    c = benv.login("new@c.example")
    assert c.post("/api/surveys", json={"title": "First in lab C"}).status_code == 201
    assert [s["title"] for s in c.get("/api/surveys").json()] == ["First in lab C"]
    assert benv.login("owner@a.example").get("/api/surveys").json() == []


def test_without_auto_create_an_unknown_lab_confers_nothing(benv):
    benv.services.auto_create_labs = False
    benv.roles["new@d.example"] = {"lab-d": "owner"}
    c = benv.login("new@d.example")
    assert c.post("/api/surveys", json={"title": "x"}).status_code == 403
    me = c.get("/api/me").json()
    assert me["memberships"] == []
    benv.services.create_lab("lab-d")  # `osp-cli lab create`
    assert c.post("/api/surveys", json={"title": "x"}).status_code == 201


# -- origin and content type (D4) ------------------------------------------------------------


def test_cross_origin_request_is_rejected_even_when_signed(benv):
    c = benv.login("editor@a.example")
    r = c.post("/api/surveys", json={"title": "x"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = c.post("/api/surveys", json={"title": "x"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = c.post("/api/surveys", json={"title": "x"}, headers={"Origin": "https://testserver"})
    assert r.status_code == 201


def test_unsafe_bodies_must_be_json(benv):
    c = benv.login("editor@a.example")
    body = json.dumps({"title": "x"})
    r = c.post("/api/surveys", content=body, headers={"Content-Type": "text/plain"})
    assert r.status_code == 415
    r = c.post("/api/surveys", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 201
