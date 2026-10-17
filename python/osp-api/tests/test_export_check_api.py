"""Export targets and export checks (task B10): diagnostics without producing a file."""

from __future__ import annotations

import copy


def _create(c, title: str = "Check") -> dict:
    r = c.post("/api/surveys", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()


def _replace(c, s: dict, survey: dict) -> int:
    op = {"op": "replace_survey", "params": {"survey": survey}}
    r = c.post(f"/api/surveys/{s['id']}/ops", json={"ops": [op], "baseRevision": s["revision"]})
    return r.status_code


def _check(c, survey_id: str, target: str):
    return c.get(f"/api/surveys/{survey_id}/export-check", params={"target": target})


def test_targets_listed_with_capability_tables(benv):
    r = benv.login("viewer@a.example").get("/api/meta/targets")
    assert r.status_code == 200
    targets = {t["id"]: t for t in r.json()}
    assert set(targets) == {"xlsform", "lss"}
    assert targets["lss"]["label"] == "LimeSurvey"
    row = targets["xlsform"]["capabilities"]["Settings.backNavigation=false"]
    assert row["level"] == "unsupported" and row["note"]


def test_targets_need_sign_in(benv):
    assert benv.client().get("/api/meta/targets").status_code == 401


def test_clean_survey_has_no_losses(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    for target in ("xlsform", "lss"):
        r = _check(c, s["id"], target)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["target"] == target and body["revision"] == 0
        assert body["exportable"] is True
        assert body["counts"]["loss"] == 0 and body["counts"]["error"] == 0


def test_unsupported_feature_reported_with_pointer(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    survey = copy.deepcopy(s["survey"])
    survey.setdefault("settings", {})["backNavigation"] = False
    assert _replace(c, s, survey) == 200

    r = _check(c, s["id"], "xlsform")
    body = r.json()
    assert body["revision"] == 1
    hits = [d for d in body["diagnostics"] if d["feature"] == "Settings.backNavigation=false"]
    assert len(hits) == 1
    assert hits[0]["level"] == "unsupported" and hits[0]["severity"] == "loss"
    assert hits[0]["pointer"] == "/settings/backNavigation"
    assert body["counts"]["loss"] >= 1 and body["exportable"] is True
    # No file: a JSON body, never a download.
    assert r.headers["content-type"].startswith("application/json")
    assert "content-disposition" not in r.headers
    # The draft is untouched by a check.
    assert c.get(f"/api/surveys/{s['id']}").json()["revision"] == 1


def test_viewer_may_check_other_lab_may_not(benv):
    s = _create(benv.login("editor@a.example"))
    assert _check(benv.login("viewer@a.example"), s["id"], "lss").status_code == 200
    assert _check(benv.login("owner@b.example"), s["id"], "lss").status_code == 404
    assert _check(benv.client(), s["id"], "lss").status_code == 401


def test_bad_target_and_unknown_survey(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    assert _check(c, s["id"], "qsf").status_code == 422
    assert c.get(f"/api/surveys/{s['id']}/export-check").status_code == 422
    assert _check(c, "nope", "xlsform").status_code == 404


def test_semantically_invalid_draft_gives_error_diagnostic(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    survey = copy.deepcopy(s["survey"])
    survey["blocks"][0]["pages"][0]["items"] = [
        {"id": "q1", "type": "single", "label": {"en": "Pick"}, "choiceList": "missing"}
    ]
    assert _replace(c, s, survey) == 200
    body = _check(c, s["id"], "lss").json()
    assert body["exportable"] is False and body["counts"]["error"] >= 1
    assert all(d["severity"] == "error" for d in body["diagnostics"])
