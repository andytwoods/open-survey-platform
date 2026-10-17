"""Import endpoints (task IM1): preview, create, errors, permissions, route ordering."""

from __future__ import annotations

from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "osp-targets/tests/data/imports"
QSF = (DATA / "coffee.qsf").read_text(encoding="utf-8")
LSS = (DATA / "coffee.lss").read_text(encoding="utf-8")
SJS = (DATA / "coffee-surveyjs.json").read_text(encoding="utf-8")


def test_preview_then_import(benv):
    c = benv.login("editor@a.example")
    r = c.post("/api/surveys/import/preview", json={"filename": "coffee.lss", "content": LSS})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["format"] == "lss" and p["ok"] is True
    assert p["summary"]["questions"] == 12 and p["summary"]["languages"] == ["en", "de"]
    assert {d["severity"] for d in p["diagnostics"]} >= {"info", "warning", "loss"}
    assert all({"code", "feature", "pointer", "message"} <= set(d) for d in p["diagnostics"])
    assert c.get("/api/surveys").json() == []

    r = c.post("/api/surveys/import", json={"filename": "coffee.lss", "content": LSS})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["survey"]["title"].startswith("Coffee and sleep")
    assert body["survey"]["revision"] == 0
    assert body["survey"]["survey"]["metadata"]["languages"] == ["en", "de"]
    assert body["preview"]["summary"] == p["summary"]
    assert [s["id"] for s in c.get("/api/surveys").json()] == [body["survey"]["id"]]
    detail = c.get(f"/api/surveys/{body['survey']['id']}").json()
    assert detail["survey"] == body["survey"]["survey"]


def test_import_with_title_and_format(benv):
    c = benv.login("owner@a.example")
    r = c.post(
        "/api/surveys/import",
        json={"filename": "x.txt", "content": SJS, "format": "surveyjs", "title": "Pilot"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["survey"]["title"] == "Pilot"
    assert r.json()["preview"]["format"] == "surveyjs"


def test_unreadable_file_is_422_with_diagnostics(benv):
    c = benv.login("owner@a.example")
    r = c.post("/api/surveys/import/preview", json={"filename": "x.qsf", "content": "<nope"})
    assert r.status_code == 200 and r.json()["ok"] is False
    assert r.json()["diagnostics"][0]["severity"] == "error"
    r = c.post("/api/surveys/import", json={"filename": "x.qsf", "content": "<nope"})
    assert r.status_code == 422
    assert r.json()["diagnostics"][0]["code"].startswith("lss.")
    assert c.get("/api/surveys").json() == []


def test_bad_bodies_are_422(benv):
    c = benv.login("owner@a.example")
    for body in (
        {"content": QSF},
        {"filename": "", "content": QSF},
        {"filename": "a.qsf", "content": QSF, "format": "docx"},
        {"filename": "a.qsf", "content": QSF, "extra": 1},
        {"filename": "a.qsf", "content": QSF, "title": ""},
    ):
        assert c.post("/api/surveys/import", json=body).status_code == 422, body


def test_viewer_is_forbidden_and_anonymous_is_unauthenticated(benv):
    v = benv.login("viewer@a.example")
    assert (
        v.post(
            "/api/surveys/import/preview", json={"filename": "a.qsf", "content": QSF}
        ).status_code
        == 403
    )
    assert (
        v.post("/api/surveys/import", json={"filename": "a.qsf", "content": QSF}).status_code == 403
    )
    anon = benv.client()
    assert (
        anon.post("/api/surveys/import", json={"filename": "a.qsf", "content": QSF}).status_code
        == 401
    )


def test_import_path_is_not_a_survey_id(benv):
    c = benv.login("owner@a.example")
    r = c.post("/api/surveys/import", json={"filename": "coffee.qsf", "content": QSF})
    assert r.status_code == 201, r.text
    assert c.get(f"/api/surveys/{r.json()['survey']['id']}").status_code == 200
