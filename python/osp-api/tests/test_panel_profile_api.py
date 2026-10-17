"""Lab property panel profile API (task B21): get/set/clear, owner-only changes, the
effective schemas, custom values through ops, the check endpoint, tenant isolation."""

from __future__ import annotations

import pytest

PROFILE = {
    "hidden": ["*.constraintMessage"],
    "order": {"*": ["required", "label"]},
    "groups": {"Logic": {"en": "Conditions"}},
    "defaults": {"single": {"required": True}},
    "custom": [
        {"key": "construct", "kind": "text", "label": {"en": "Construct"}, "required": True},
        {"key": "weight", "kind": "number", "label": {"en": "Weight"}, "default": 1},
    ],
}


def _schema(doc: dict, type_: str) -> dict:
    return next(s for s in doc["schemas"] if s["type"] == type_)


def test_stock_panel_until_a_profile_is_set(benv):
    c = benv.login("owner@a.example")
    r = c.get("/api/panel-profile")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "tenantId": benv.tenants["A"],
        "profile": None,
        "diagnostics": [],
        "canManage": True,
        "updatedBy": None,
        "updatedAt": None,
    }
    doc = c.get("/api/panel-profile/schemas").json()
    stock = c.get("/api/meta/property-schemas").json()
    assert doc["schemas"] == stock["schemas"]
    assert doc["profileApplied"] is False and doc["defaults"] == {}


def test_set_get_effective_schemas_and_clear(benv):
    c = benv.login("owner@a.example")
    r = c.put("/api/panel-profile", json={"profile": PROFILE})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile"]["custom"][0]["key"] == "construct"
    assert body["profile"]["profileVersion"] == "osp-panel-profile/0.1"  # normalised
    assert body["diagnostics"] == [] and body["updatedBy"] == "owner@a.example"
    assert c.get("/api/panel-profile").json()["profile"] == body["profile"]

    doc = c.get("/api/panel-profile/schemas").json()
    assert doc["profileApplied"] is True
    assert doc["groupLabels"] == {"Logic": {"en": "Conditions"}}
    assert doc["defaults"]["single"] == {"required": True, "custom.weight": 1}
    single = _schema(doc, "single")
    assert list(single["properties"])[:2] == ["required", "label"]
    assert "constraintMessage" not in single["properties"]
    assert single["properties"]["custom.construct"]["kind"] == "text"
    assert single["properties"]["required"]["default"] is True
    assert "custom.construct" not in _schema(doc, "page")["properties"]

    assert c.delete("/api/panel-profile").status_code == 204
    assert c.get("/api/panel-profile").json()["profile"] is None
    assert c.delete("/api/panel-profile").status_code == 204  # idempotent


def test_invalid_profile_is_rejected_and_problems_are_warnings(benv):
    c = benv.login("owner@a.example")
    bad = {"custom": [{"key": "Bad Key", "kind": "text", "label": "x"}]}
    r = c.put("/api/panel-profile", json={"profile": bad})
    assert r.status_code == 422, r.text
    assert all(d["code"] == "profile.schema" for d in r.json()["diagnostics"])
    assert c.get("/api/panel-profile").json()["profile"] is None
    assert c.put("/api/panel-profile", json={"profile": "nope"}).status_code == 422
    assert c.put("/api/panel-profile", json={"nope": {}}).status_code == 422

    odd = {"hidden": ["*.label", "single.nope"], "defaults": {"single": {"required": "yes"}}}
    r = c.put("/api/panel-profile", json={"profile": odd})
    assert r.status_code == 200, r.text
    codes = {d["code"] for d in r.json()["diagnostics"]}
    assert codes == {"profile.bad_default", "profile.required_hidden", "profile.unknown_key"}
    assert all(d["severity"] == "warning" for d in r.json()["diagnostics"])
    doc = c.get("/api/panel-profile/schemas").json()
    assert "label" in _schema(doc, "single")["properties"]  # the stock schema stands in
    assert _schema(doc, "single")["properties"]["required"]["default"] is False


def test_only_owners_change_the_profile(benv):
    owner = benv.login("owner@a.example")
    assert owner.put("/api/panel-profile", json={"profile": PROFILE}).status_code == 200
    for who in ("editor@a.example", "viewer@a.example"):
        c = benv.login(who)
        r = c.get("/api/panel-profile")
        assert r.status_code == 200 and r.json()["canManage"] is False
        assert r.json()["profile"]["custom"][0]["key"] == "construct"
        assert c.get("/api/panel-profile/schemas").json()["profileApplied"] is True
        assert c.put("/api/panel-profile", json={"profile": {}}).status_code == 403
        assert c.delete("/api/panel-profile").status_code == 403
    assert owner.get("/api/panel-profile").json()["profile"]["custom"][0]["key"] == "construct"


def test_other_labs_profile_is_invisible(benv):
    a = benv.login("owner@a.example")
    a.put("/api/panel-profile", json={"profile": PROFILE})
    b = benv.login("owner@b.example")
    assert b.get("/api/panel-profile").json()["profile"] is None
    assert b.get("/api/panel-profile/schemas").json()["profileApplied"] is False
    assert b.get("/api/panel-profile", params={"tenantId": benv.tenants["A"]}).status_code == 403
    assert b.get("/api/panel-profile", params={"tenantId": "no-such-lab"}).status_code == 403
    r = b.put("/api/panel-profile", json={"profile": {}, "tenantId": benv.tenants["A"]})
    assert r.status_code == 403
    assert a.get("/api/panel-profile").json()["profile"]["custom"][0]["key"] == "construct"


def test_custom_values_through_ops_and_the_check(benv):
    c = benv.login("owner@a.example")
    c.put("/api/panel-profile", json={"profile": PROFILE})
    s = c.post("/api/surveys", json={"title": "Annotated"}).json()
    sid = s["id"]
    survey = c.get(f"/api/surveys/{sid}").json()["survey"]
    qid = survey["blocks"][0]["pages"][0]["items"][0]["id"]
    # Before any value: the required `construct` is missing (a warning, not an error).
    check = c.get(f"/api/panel-profile/check/{sid}").json()
    assert [d["code"] for d in check] == ["profile.custom_missing"]
    ops = [
        {"op": "set_custom_property", "params": {"target": qid, "key": "construct", "value": "x"}},
        {"op": "set_custom_property", "params": {"target": qid, "key": "weight", "value": "no"}},
        {"op": "set_custom_property", "params": {"target": qid, "key": "other", "value": True}},
    ]
    r = c.post(f"/api/surveys/{sid}/ops", json={"ops": ops, "baseRevision": 0})
    assert r.status_code == 200, r.text
    survey = c.get(f"/api/surveys/{sid}").json()["survey"]
    q = survey["blocks"][0]["pages"][0]["items"][0]
    assert q["custom"] == {"construct": "x", "weight": "no", "other": True}
    check = c.get(f"/api/panel-profile/check/{sid}").json()
    assert {(d["code"], d["pointer"].rsplit("/", 1)[1]) for d in check} == {
        ("profile.custom_kind", "weight"),
        ("profile.custom_unknown", "other"),
    }
    assert all(d["severity"] in ("warning", "info") for d in check)
    # `set_property` never takes the `custom` object as a whole.
    bad = [{"op": "set_property", "params": {"target": qid, "property": "custom", "value": {}}}]
    r = c.post(f"/api/surveys/{sid}/ops", json={"ops": bad, "baseRevision": 1})
    assert r.status_code == 422
    # No profile: nothing to check against.
    c.delete("/api/panel-profile")
    assert c.get(f"/api/panel-profile/check/{sid}").json() == []
    # Another lab's survey is not found; a viewer may read the check.
    b = benv.login("owner@b.example")
    assert b.get(f"/api/panel-profile/check/{sid}").status_code == 404
    assert benv.login("viewer@a.example").get(f"/api/panel-profile/check/{sid}").status_code == 200


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_profile_needs_identity_and_same_origin(benv, method):
    anon = benv.client()
    assert getattr(anon, method)("/api/panel-profile").status_code == 401
    assert anon.get("/api/panel-profile/schemas").status_code == 401
    if method != "get":
        c = benv.login("owner@a.example")
        c.headers["Origin"] = "https://evil.example"
        kwargs = {"json": {"profile": {}}} if method == "put" else {}
        assert getattr(c, method)("/api/panel-profile", **kwargs).status_code == 403
