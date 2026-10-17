"""Lab theme library API (task B12): CRUD, lab default, permissions, tenant isolation, and
the publish resolution order survey theme -> lab default -> clean."""

from __future__ import annotations

import pytest
from osp_spec.theme import PRESETS

RETENTION = {
    "op": "set_property",
    "params": {"target": "/settings", "property": "retention", "value": {"kind": "indefinite"}},
}


def _preset(name: str) -> dict:
    return PRESETS[name].model_dump(mode="json", by_alias=True)


def _pale() -> dict:
    bad = _preset("clean")
    bad["colours"]["light"]["text"] = "#f0f0f0"  # light grey on white
    return bad


def _save(c, name: str, theme: dict) -> dict:
    r = c.post("/api/themes", json={"name": name, "theme": theme})
    assert r.status_code == 201, r.text
    return r.json()


def test_crud_and_lab_default(benv):
    c = benv.login("editor@a.example")
    lib = c.get("/api/themes").json()
    assert lib == {
        "tenantId": benv.tenants["A"],
        "themes": [],
        "defaultThemeId": None,
        "canManage": True,
    }
    warm = _save(c, "Warm lab", {"colours": _preset("warm")["colours"], "preset": "warm"})
    assert warm["theme"]["themeVersion"] == "osp-theme/0.1"  # stored normalised
    assert warm["isDefault"] is False and warm["diagnostics"] == []

    renamed = c.patch(f"/api/themes/{warm['id']}", json={"name": "Warm"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Warm"
    changed = c.patch(f"/api/themes/{warm['id']}", json={"theme": {**warm["theme"], "radius": 0}})
    assert changed.json()["theme"]["radius"] == 0

    d = c.put("/api/themes/default", json={"themeId": warm["id"]})
    assert d.status_code == 200, d.text
    assert d.json()["defaultThemeId"] == warm["id"]
    assert c.get(f"/api/themes/{warm['id']}").json()["isDefault"] is True

    assert c.put("/api/themes/default", json={"themeId": None}).json()["defaultThemeId"] is None
    assert c.delete(f"/api/themes/{warm['id']}").status_code == 204
    assert c.get(f"/api/themes/{warm['id']}").status_code == 404


def test_bad_theme_and_duplicate_name_are_refused(benv):
    c = benv.login("owner@a.example")
    r = c.post("/api/themes", json={"name": "Broken", "theme": {"colours": {}}})
    assert r.status_code == 422
    assert all(d["code"] == "theme.schema" for d in r.json()["diagnostics"])
    _save(c, "One", _preset("clean"))
    assert c.post("/api/themes", json={"name": "One", "theme": _preset("warm")}).status_code == 409


def test_a_failing_theme_can_be_saved_but_not_made_the_lab_default(benv):
    c = benv.login("editor@a.example")
    pale = _save(c, "Pale", _pale())
    assert {d["code"] for d in pale["diagnostics"]} == {"theme.contrast"}
    r = c.put("/api/themes/default", json={"themeId": pale["id"]})
    assert r.status_code == 422 and "accessibility" in r.json()["message"]


def test_viewer_may_read_but_not_change(benv):
    owner = benv.login("owner@a.example")
    t = _save(owner, "Lab", _preset("clean"))
    v = benv.login("viewer@a.example")
    lib = v.get("/api/themes")
    assert lib.status_code == 200
    assert lib.json()["canManage"] is False and [x["id"] for x in lib.json()["themes"]] == [t["id"]]
    assert v.get(f"/api/themes/{t['id']}").status_code == 200
    assert v.post("/api/themes", json={"name": "X", "theme": _preset("warm")}).status_code == 403
    assert v.patch(f"/api/themes/{t['id']}", json={"name": "Y"}).status_code == 403
    assert v.delete(f"/api/themes/{t['id']}").status_code == 403
    assert v.put("/api/themes/default", json={"themeId": t["id"]}).status_code == 403


def test_other_labs_themes_are_invisible(benv):
    a = benv.login("owner@a.example")
    t = _save(a, "Secret", _preset("warm"))
    b = benv.login("owner@b.example")
    assert b.get("/api/themes").json()["themes"] == []
    for call in (
        lambda: b.get(f"/api/themes/{t['id']}"),
        lambda: b.patch(f"/api/themes/{t['id']}", json={"name": "Mine"}),
        lambda: b.delete(f"/api/themes/{t['id']}"),
        lambda: b.put("/api/themes/default", json={"themeId": t["id"]}),
    ):
        assert call().status_code == 404
    # Naming lab A explicitly is "not permitted", the same for any lab B can't see.
    assert b.get("/api/themes", params={"tenantId": benv.tenants["A"]}).status_code == 403
    assert b.get("/api/themes", params={"tenantId": "no-such-lab"}).status_code == 403
    assert a.get(f"/api/themes/{t['id']}").json()["name"] == "Secret"


@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete"])
def test_themes_need_sign_in_and_csrf(benv, method):
    anon = benv.client()
    path = "/api/themes/default" if method == "put" else "/api/themes"
    if method in ("patch", "delete"):
        path = "/api/themes/x"
    assert getattr(anon, method)(path).status_code == 401
    if method != "get":
        c = benv.login("owner@a.example")
        del c.headers["X-CSRF-Token"]
        kwargs = {"json": {"themeId": None}} if method in ("post", "put", "patch") else {}
        assert getattr(c, method)(path, **kwargs).status_code == 403


def test_publish_prefers_the_survey_theme_over_the_lab_default(benv):
    c = benv.login("editor@a.example")
    lab = _save(c, "Warm", _preset("warm"))
    c.put("/api/themes/default", json={"themeId": lab["id"]})
    s = c.post("/api/surveys", json={"title": "Own theme"}).json()
    dark = _preset("dark")
    ops = [RETENTION, {"op": "set_theme", "params": {"theme": dark}}]
    r = c.post(f"/api/surveys/{s['id']}/ops", json={"ops": ops, "baseRevision": 0})
    assert r.status_code == 200, r.text
    pub = c.post(f"/api/surveys/{s['id']}/publish").json()
    plan = benv.client().get(pub["planUrl"]).json()
    assert plan["theme"] == dark

    # Clearing the survey theme falls back to the lab default.
    clear = {"ops": [{"op": "set_theme", "params": {"theme": None}}], "baseRevision": 1}
    assert c.post(f"/api/surveys/{s['id']}/ops", json=clear).status_code == 200
    pub = c.post(f"/api/surveys/{s['id']}/publish").json()
    assert benv.client().get(pub["planUrl"]).json()["theme"] == _preset("warm")


def test_a_failing_survey_theme_blocks_publish_with_a_survey_pointer(benv):
    c = benv.login("editor@a.example")
    s = c.post("/api/surveys", json={"title": "Pale"}).json()
    ops = [RETENTION, {"op": "set_theme", "params": {"theme": _pale()}}]
    assert c.post(f"/api/surveys/{s['id']}/ops", json={"ops": ops, "baseRevision": 0}).is_success
    r = c.post(f"/api/surveys/{s['id']}/publish")
    assert r.status_code == 422
    assert r.json()["diagnostics"][0]["pointer"].startswith("/settings/theme/colours/light/")


def test_set_theme_needs_edit_rights(benv):
    owner = benv.login("owner@a.example")
    s = owner.post("/api/surveys", json={"title": "T"}).json()
    v = benv.login("viewer@a.example")
    body = {"ops": [{"op": "set_theme", "params": {"theme": _preset("warm")}}], "baseRevision": 0}
    assert v.post(f"/api/surveys/{s['id']}/ops", json=body).status_code == 403


def test_lss_export(benv):
    c = benv.login("editor@a.example")
    s = c.post("/api/surveys", json={"title": "Export me"}).json()
    r = c.get(f"/api/surveys/{s['id']}/export/lss")
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"<?xml") and ".lss" in r.headers["content-disposition"]
    viewer = benv.login("viewer@a.example")
    assert viewer.get(f"/api/surveys/{s['id']}/export/lss").status_code == 403
