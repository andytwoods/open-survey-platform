"""Builder API end to end: ops round trip, 409, undo/redo, publish, export."""

from __future__ import annotations

SET_TITLE = {"op": "set_title", "params": {"title": {"en": "Mood study"}}}


def _create(c, title: str = "First") -> dict:
    r = c.post("/api/surveys", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()


def test_create_list_get(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    assert s["revision"] == 0 and s["survey"]["metadata"]["title"] == {"en": "First"}
    assert s["tenantId"] == benv.tenants["A"]
    listed = c.get("/api/surveys").json()
    assert [x["id"] for x in listed] == [s["id"]]
    got = c.get(f"/api/surveys/{s['id']}").json()
    assert got["survey"] == s["survey"] and got["revision"] == 0
    assert got["diagnostics"] == [] and s["diagnostics"] == []


def test_create_rejects_invalid_survey(benv):
    c = benv.login("editor@a.example")
    r = c.post("/api/surveys", json={"title": "x", "survey": {"specVersion": "nope"}})
    assert r.status_code == 422
    assert r.json()["diagnostics"]


def test_op_round_trip_and_stale_revision(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    r = c.post(f"/api/surveys/{s['id']}/ops", json={"ops": [SET_TITLE], "baseRevision": 0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["revision"] == 1
    assert body["patch"] == [{"op": "replace", "path": "/metadata/title/en", "value": "Mood study"}]
    assert body["transactionId"] and body["diagnostics"] == []
    got = c.get(f"/api/surveys/{s['id']}").json()
    assert got["revision"] == 1 and got["survey"]["metadata"]["title"]["en"] == "Mood study"
    assert c.get("/api/surveys").json()[0]["title"] == "Mood study"  # listing kept in step

    stale = c.post(f"/api/surveys/{s['id']}/ops", json={"ops": [SET_TITLE], "baseRevision": 0})
    assert stale.status_code == 409
    assert stale.json()["currentRevision"] == 1
    assert stale.json()["code"] == "op.conflict"


def test_rejected_transaction_applies_nothing(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    ops = [SET_TITLE, {"op": "delete_question", "params": {"id": "nope"}}]
    r = c.post(f"/api/surveys/{s['id']}/ops", json={"ops": ops, "baseRevision": 0})
    assert r.status_code == 422
    assert r.json()["failedIndex"] == 1 and r.json()["diagnostics"]
    assert c.get(f"/api/surveys/{s['id']}").json()["revision"] == 0
    unknown = c.post(
        f"/api/surveys/{s['id']}/ops", json={"ops": [{"op": "nope"}], "baseRevision": 0}
    )
    assert unknown.status_code == 422
    assert unknown.json()["diagnostics"][0]["code"] == "op.unknown"


def test_noop_transaction_keeps_revision(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    same = {"op": "set_title", "params": {"title": {"en": "First"}}}
    r = c.post(f"/api/surveys/{s['id']}/ops", json={"ops": [same], "baseRevision": 0})
    assert r.status_code == 200
    assert r.json()["revision"] == 0 and r.json()["transactionId"] is None


def test_retry_with_same_transaction_id_is_not_applied_twice(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    req = {"ops": [SET_TITLE], "baseRevision": 0, "transactionId": "client-1"}
    first = c.post(f"/api/surveys/{s['id']}/ops", json=req).json()
    again = c.post(f"/api/surveys/{s['id']}/ops", json=req).json()
    assert first["revision"] == 1 and first["transactionId"] == "client-1"
    assert again == {**again, "revision": 1, "replayed": True, "transactionId": "client-1"}
    assert c.get(f"/api/surveys/{s['id']}").json()["revision"] == 1


def test_undo_redo(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    url = f"/api/surveys/{s['id']}"
    edit = c.post(f"{url}/ops", json={"ops": [SET_TITLE], "baseRevision": 0}).json()

    undo = c.post(f"{url}/undo", json={"transactionId": edit["transactionId"], "baseRevision": 1})
    assert undo.status_code == 200, undo.text
    u = undo.json()
    assert u["revision"] == 2 and u["transactionId"].startswith("u:")
    assert u["patch"] == [{"op": "replace", "path": "/metadata/title/en", "value": "First"}]
    assert c.get(url).json()["survey"]["metadata"]["title"]["en"] == "First"

    redo = c.post(f"{url}/redo", json={"transactionId": u["transactionId"], "baseRevision": 2})
    assert redo.status_code == 200, redo.text
    assert redo.json()["revision"] == 3 and redo.json()["transactionId"].startswith("r:")
    assert c.get(url).json()["survey"]["metadata"]["title"]["en"] == "Mood study"

    kinds = [(h["kind"], h["revision"]) for h in c.get(f"{url}/history").json()]
    assert kinds == [("edit", 1), ("undo", 2), ("redo", 3)]

    # Guard rails: stale base, wrong kind, unknown transaction.
    stale = c.post(f"{url}/undo", json={"transactionId": edit["transactionId"], "baseRevision": 1})
    assert stale.status_code == 409 and stale.json()["currentRevision"] == 3
    bad = c.post(f"{url}/redo", json={"transactionId": edit["transactionId"], "baseRevision": 3})
    assert bad.status_code == 422
    bad = c.post(f"{url}/undo", json={"transactionId": u["transactionId"], "baseRevision": 3})
    assert bad.status_code == 422
    missing = c.post(f"{url}/undo", json={"transactionId": "nope", "baseRevision": 3})
    assert missing.status_code == 404


RETENTION = {
    "op": "set_property",
    "params": {
        "target": "/settings",
        "property": "retention",
        "value": {"kind": "days-after-close", "days": 365},
    },
}


def test_publish_freezes_a_version(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    assert s["publishedVersions"] == 0
    # A retention policy is required before publishing (no silent default).
    r = c.post(f"/api/surveys/{s['id']}/publish", json={"baseRevision": 0})
    assert r.status_code == 422 and "publish.retention_required" in r.text
    c.post(f"/api/surveys/{s['id']}/ops", json={"ops": [RETENTION], "baseRevision": 0})
    stale = c.post(f"/api/surveys/{s['id']}/publish", json={"baseRevision": 5})
    assert stale.status_code == 409
    r = c.post(f"/api/surveys/{s['id']}/publish", json={"baseRevision": 1})
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["number"] == 1 and len(v["checksum"]) == 64
    assert v["planUrl"] == f"/api/s/{v['slug']}/plan/{v['planChecksum']}"
    again = c.post(f"/api/surveys/{s['id']}/publish").json()
    # The frozen body records its number (the plan's seed version), so both checksums move.
    assert again["number"] == 2 and again["slug"] == v["slug"]
    assert again["checksum"] != v["checksum"] and again["planChecksum"] != v["planChecksum"]
    assert c.get(f"/api/surveys/{s['id']}").json()["publishedVersions"] == 2
    owner = benv.login("owner@a.example")
    assert owner.delete(f"/api/surveys/{s['id']}").status_code == 409  # research record


def test_publish_refuses_a_survey_with_errors(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    # An unknown reference is a semantic error: allowed in a draft, not in a version.
    body = s["survey"]
    body["blocks"][0]["pages"][0]["items"][0]["showIf"] = {
        "kind": "answered",
        "ref": {"kind": "ref", "id": "ghost"},
    }
    op = {"op": "replace_survey", "params": {"survey": body}}
    r = c.post(f"/api/surveys/{s['id']}/ops", json={"ops": [op], "baseRevision": 0})
    assert r.status_code == 200, r.text
    assert [d["code"] for d in r.json()["diagnostics"]] == ["ref.unknown"]
    got = c.get(f"/api/surveys/{s['id']}").json()  # a reload sees the same diagnostics
    assert [d["code"] for d in got["diagnostics"]] == ["ref.unknown"]
    pub = c.post(f"/api/surveys/{s['id']}/publish")
    assert pub.status_code == 422
    assert pub.json()["diagnostics"][0]["code"] == "ref.unknown"


def test_delete_unpublished_survey(benv):
    editor = benv.login("editor@a.example")
    s = _create(editor)
    assert editor.delete(f"/api/surveys/{s['id']}").status_code == 403  # owners only
    owner = benv.login("owner@a.example")
    assert owner.delete(f"/api/surveys/{s['id']}").status_code == 204
    assert owner.get(f"/api/surveys/{s['id']}").status_code == 404


def test_export_xlsform(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    r = c.get(f"/api/surveys/{s['id']}/export/xlsform")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert "attachment" in r.headers["content-disposition"]
    assert r.content[:2] == b"PK"


def test_meta_endpoints(benv):
    c = benv.login("viewer@a.example")
    ops = c.get("/api/meta/ops").json()
    assert {"set_title", "add_question", "replace_survey"} <= {o["id"] for o in ops}
    assert all("paramsSchema" in o for o in ops)
    assert "schemas" in c.get("/api/meta/property-schemas").json()
    assert "$schema" in c.get("/api/meta/survey-schema").json()
    assert "$schema" in c.get("/api/meta/theme-schema").json()


def test_openapi_has_typed_op_params(benv):
    schemas = benv.app.openapi()["components"]["schemas"]
    assert "SetTitleParams" in schemas and "OpId" in schemas


def test_builder_routes_answer_503_without_services():
    from fastapi.testclient import TestClient
    from osp_api.app import create_app

    r = TestClient(create_app(), base_url="https://testserver").get("/api/surveys")
    assert r.status_code == 503
