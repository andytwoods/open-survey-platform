"""Saved results layouts API (task V5a, V-D9): CRUD, the survey default, the settings
schema at the HTTP edge, permissions and tenant isolation. The schema itself is tested in
``python/osp-app/tests/test_results_layouts.py``."""

from __future__ import annotations

import pytest
from osp_store import TenantContext

SETTINGS = {
    "query": {"split": {"condition": "arm"}, "denominator": "shown"},
    "cards": [
        {"question": "fruit", "chart": "donut", "caption": "Figure 1"},
        {"question": "age", "chart": "histogram", "bins": {"width": 5}},
        {"question": "why", "hidden": True},
    ],
}


@pytest.fixture
def survey(benv) -> str:
    c = benv.login("owner@a.example")
    r = c.post("/api/surveys", json={"title": "Results"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _save(c, sid: str, name: str, settings=None, **extra) -> dict:
    body = {"name": name, "settings": SETTINGS if settings is None else settings, **extra}
    r = c.post(f"/api/surveys/{sid}/results/layouts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_crud_and_the_survey_default(benv, survey):
    editor = benv.login("editor@a.example")
    base = f"/api/surveys/{survey}/results/layouts"
    assert editor.get(base).json() == {"surveyId": survey, "layouts": [], "defaultLayoutId": None}

    team = _save(editor, survey, "Team view", isDefault=True)
    assert team["isDefault"] is True and team["createdBy"] == "editor@a.example"
    assert team["settings"]["schemaVersion"] == "osp-results-layout/0.1"  # stored normalised
    assert team["settings"]["query"]["denominator"] == "shown"
    assert team["settings"]["query"]["status"] == "complete"  # defaults filled in
    assert [c["question"] for c in team["settings"]["cards"]] == ["fruit", "age", "why"]
    assert team["settings"]["cards"][2]["hidden"] is True

    owner = benv.login("owner@a.example")  # lab-shared: the owner sees the editor's layout
    quick = _save(owner, survey, "Quick look", {"cards": [{"question": "fruit"}]})
    lst = owner.get(base).json()
    assert [x["name"] for x in lst["layouts"]] == ["Quick look", "Team view"]
    assert lst["defaultLayoutId"] == team["id"]
    assert owner.get(f"{base}/{team['id']}").json() == team

    renamed = owner.patch(f"{base}/{quick['id']}", json={"name": "Quick"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Quick"
    changed = owner.patch(f"{base}/{quick['id']}", json={"settings": {"showNotes": True}})
    assert changed.json()["settings"]["showNotes"] is True
    assert changed.json()["settings"]["cards"] == []  # settings are replaced whole
    assert changed.json()["updatedBy"] == "owner@a.example"
    assert changed.json()["createdBy"] == "owner@a.example"

    d = owner.put(f"{base}/default", json={"layoutId": quick["id"]})
    assert d.status_code == 200, d.text
    assert d.json()["defaultLayoutId"] == quick["id"]
    assert [x["isDefault"] for x in d.json()["layouts"]] == [True, False]
    assert owner.put(f"{base}/default", json={"layoutId": None}).json()["defaultLayoutId"] is None

    owner.put(f"{base}/default", json={"layoutId": team["id"]})
    assert editor.delete(f"{base}/{team['id']}").status_code == 204
    assert editor.get(f"{base}/{team['id']}").status_code == 404
    assert editor.get(base).json()["defaultLayoutId"] is None  # deleting the default clears it

    actions = [a.action for a in benv.store.list_audit(TenantContext(benv.tenants["A"], "x"))]
    assert actions.count("results.layout.create") == 2
    assert {"results.layout.update", "results.layout.delete", "results.layout.default.set",
            "results.layout.default.clear"} <= set(actions)  # fmt: skip


def test_bad_bodies(benv, survey):
    c = benv.login("owner@a.example")
    base = f"/api/surveys/{survey}/results/layouts"
    r = c.post(base, json={"name": "x", "settings": {"rows": [[1, 2]]}})  # never data
    assert r.status_code == 422, r.text
    r = c.post(base, json={"name": "x", "settings": {"cards": [{"question": "q", "chart": "X"}]}})
    assert r.status_code == 422
    assert c.post(base, json={"name": "", "settings": {}}).status_code == 422
    assert c.post(base, json={"name": "x"}).status_code == 422  # settings required
    assert c.post(base, json={"name": "x", "settings": {}, "extra": 1}).status_code == 422
    assert c.post(base, json={"name": "x", "settings": {"query": {"split": {}}}}).status_code == 422
    one = _save(c, survey, "One")
    assert c.post(base, json={"name": "One", "settings": {}}).status_code == 409
    two = _save(c, survey, "Two")
    assert c.patch(f"{base}/{two['id']}", json={"name": "One"}).status_code == 409
    assert c.patch(f"{base}/{one['id']}", json={"settings": {"cards": 1}}).status_code == 422
    assert c.patch(f"{base}/{one['id']}", json={}).status_code == 200  # nothing to change
    assert c.put(f"{base}/default", json={"layoutId": "no-such"}).status_code == 404
    assert c.put(f"{base}/default", json={}).status_code == 422
    assert c.get(f"{base}/no-such").status_code == 404
    assert c.delete(f"{base}/no-such").status_code == 404


def test_layouts_belong_to_one_survey(benv, survey):
    c = benv.login("owner@a.example")
    other = c.post("/api/surveys", json={"title": "Other"}).json()["id"]
    lay = _save(c, survey, "L")
    assert c.get(f"/api/surveys/{other}/results/layouts").json()["layouts"] == []
    wrong = f"/api/surveys/{other}/results/layouts/{lay['id']}"
    assert c.get(wrong).status_code == 404
    assert c.patch(wrong, json={"name": "x"}).status_code == 404
    assert c.delete(wrong).status_code == 404
    r = c.put(f"/api/surveys/{other}/results/layouts/default", json={"layoutId": lay["id"]})
    assert r.status_code == 404
    _save(c, other, "L")  # the same name in another survey is fine
    assert c.get(f"/api/surveys/{survey}/results/layouts/{lay['id']}").json()["name"] == "L"


def test_viewer_gets_nothing_and_other_labs_see_not_found(benv, survey):
    owner = benv.login("owner@a.example")
    lay = _save(owner, survey, "Secret")
    base = f"/api/surveys/{survey}/results/layouts"
    for who, status in (("viewer@a.example", 403), ("owner@b.example", 404)):
        c = benv.login(who)
        assert c.get(base).status_code == status
        assert c.get(f"{base}/{lay['id']}").status_code == status
        assert c.post(base, json={"name": "x", "settings": {}}).status_code == status
        assert c.patch(f"{base}/{lay['id']}", json={"name": "Mine"}).status_code == status
        assert c.delete(f"{base}/{lay['id']}").status_code == status
        assert c.put(f"{base}/default", json={"layoutId": lay["id"]}).status_code == status
    lst = owner.get(base).json()
    assert [x["name"] for x in lst["layouts"]] == ["Secret"] and lst["defaultLayoutId"] is None
    audit_b = benv.store.list_audit(TenantContext(benv.tenants["B"], "x"))
    assert not any(a.action.startswith("results.layout") for a in audit_b)


def test_contract_documents_the_settings_schema(benv):
    schemas = benv.app.openapi()["components"]["schemas"]
    settings = schemas["LayoutSettings"]
    assert settings["additionalProperties"] is False
    assert set(settings["properties"]) == {"schemaVersion", "query", "cards", "showNotes"}
    assert schemas["CardLayout"]["additionalProperties"] is False
    assert schemas["LayoutQuery"]["additionalProperties"] is False
    assert schemas["ResultsLayoutOut"]["properties"]["settings"]["$ref"].endswith("/LayoutSettings")
