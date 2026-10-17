"""Publishing derives `metadata.instruments` from the `source` fields (question-bank.md
lead decision 1): a survey holding the bundled GAD-2 block publishes a version whose
codebook lists the instrument with its licence evidence, and stale entries are dropped."""

from __future__ import annotations

import copy

from osp_instruments import load_document
from osp_spec.bank import fragment_survey


def _survey() -> dict:
    doc = load_document("gad2")
    survey, _ = fragment_survey(doc["fragment"])
    survey["id"] = "bank_publish"
    survey["metadata"]["title"] = "Bank publish"
    survey["blocks"][0]["source"] = {"bank": "gad2", "version": 1, "library": "bundled"}
    survey["settings"] = {"retention": {"kind": "indefinite"}}
    survey["consent"] = {"text": "Invented consent text for a test."}
    # A stale entry the publish must drop (nothing carries this source any more).
    survey["metadata"]["instruments"] = [
        {"bank": "gone", "version": 1, "library": "lab", "title": "Deleted"}
    ]
    return survey


def test_publish_derives_instruments(benv):
    c = benv.login("editor@a.example")
    r = c.post("/api/surveys", json={"title": "Bank publish", "survey": copy.deepcopy(_survey())})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    pub = c.post(f"/api/surveys/{sid}/publish", json={})
    assert pub.status_code == 201, pub.text
    book = c.get(f"/api/surveys/{sid}/export/codebook?format=json&version=1")
    assert book.status_code == 200, book.text
    [entry] = book.json()["instruments"]
    doc = load_document("gad2")
    assert entry["bank"] == "gad2" and entry["library"] == "bundled"
    assert entry["title"] == doc["title"]
    assert entry["licence"]["class"] == "public-domain"
    assert entry["licence"]["url"] == doc["licence"]["url"]
    assert entry["licence"]["evidenceDate"] == "2026-10-17"
    assert entry["variables"] == ["gad2_q1", "gad2_q2"]
    assert entry["scoringVariables"] == ["gad2_total"]
