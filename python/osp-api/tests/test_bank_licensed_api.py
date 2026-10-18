"""QB5's bank routes: the save preview, the instrument stubs and the licensed-copy
wizard's save (owner only, attestation required, stub item count enforced, the result a
private `licensed-to-lab` item with the recipe as computed variables)."""

from __future__ import annotations

from typing import Any

import pytest
from osp_instruments import stub_ids

from .test_bank_api import _survey


@pytest.fixture
def survey(benv):
    c = benv.login("editor@a.example")
    r = c.post("/api/surveys", json={"title": "Bank QB5", "survey": _survey()})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _lines(n: int, options: int = 0) -> list[str]:
    opts = "" if not options else " | " + " | ".join(f"opt {k}" for k in range(options))
    return [f"Item {i}{opts}" for i in range(1, n + 1)]


# --- preview ----------------------------------------------------------------------------


def test_preview_says_what_travels_and_what_is_cut(benv, survey):
    c = benv.login("viewer@a.example")  # a viewer may preview (bank.view + survey.read)
    r = c.post("/api/bank/preview", json={"surveyId": survey, "targetId": "demo"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert (p["kind"], p["itemCount"], sorted(p["languages"])) == ("block", 2, ["de", "en"])
    assert p["choiceLists"] == ["agree4"] and p["variables"] == ["demo_total"]
    assert [d["code"] for d in p["diagnostics"]] == ["bank.external_ref"]
    assert all(d["severity"] == "warning" for d in p["diagnostics"])
    q = c.post("/api/bank/preview", json={"surveyId": survey, "targetId": "demo_q1"}).json()
    assert (q["kind"], q["itemCount"], q["variables"]) == ("question", 1, [])
    r = c.post("/api/bank/preview", json={"surveyId": survey, "targetId": "nope"})
    assert r.status_code == 422 and r.json()["diagnostics"][0]["code"] == "bank.target_not_found"
    # Nothing was saved.
    assert (
        benv.login("editor@a.example").get("/api/bank", params={"source": "lab"}).json()["items"]
        == []
    )
    # Another lab's member sees no such survey.
    r = benv.login("owner@b.example").post(
        "/api/bank/preview", json={"surveyId": survey, "targetId": "demo"}
    )
    assert r.status_code == 404


# --- stubs -------------------------------------------------------------------------------


def test_stubs_are_listed_without_item_text(benv):
    c = benv.login("viewer@a.example")
    r = c.get("/api/bank/stubs")
    assert r.status_code == 200
    stubs = r.json()
    assert [s["id"] for s in stubs] == stub_ids()
    bdi = next(s for s in stubs if s["id"] == "bdi-ii")
    assert bdi["terms"] == "licensed" and bdi["itemCount"] == 21
    assert bdi["response"] == {"kind": "per-item", "min": 0, "max": 3}
    assert bdi["holder"]["name"].startswith("Pearson") and bdi["citation"]["text"]
    assert set(bdi) == {
        "stubVersion", "id", "title", "abbreviation", "description", "tags", "terms", "holder",
        "citation", "itemCount", "response", "scoring", "note",
    }  # fmt: skip
    assert "fragment" not in bdi


# --- licensed copies ---------------------------------------------------------------------


def _compose(c, **extra: Any):
    body = {"stubId": "pss-10", "items": _lines(10), "attest": True, **extra}
    return c.post("/api/bank/licensed", json=body)


def test_licensed_copy_from_a_stub(benv):
    owner, editor = benv.login("owner@a.example"), benv.login("editor@a.example")
    r = _compose(owner, labels=["Never", "Almost never", "Sometimes", "Fairly often", "Very often"])
    assert r.status_code == 201, r.text
    item = r.json()
    s, doc = item["summary"], item["document"]
    assert s["licenceClass"] == "licensed-to-lab" and s["kind"] == "block"
    assert s["abbreviation"] == "PSS-10" and s["title"].startswith("Perceived Stress Scale")
    assert s["itemCount"] == 10 and s["visibility"] == "lab" and "licensed" in s["tags"]
    assert doc["licence"]["holder"].startswith("Sheldon Cohen")
    assert "attested by owner@a.example" in doc["licence"]["statement"]
    assert doc["citation"]["doi"] == "10.2307/2136404"
    assert "reversing" in doc["scoring"]["text"]
    frag = doc["fragment"]
    [matrix] = frag["block"]["pages"][0]["items"]
    assert matrix["type"] == "matrix" and len(matrix["rows"]) == 10
    assert matrix["rows"][0] == {"id": "q1", "label": "Item 1"}
    assert [c_["label"] for c_ in frag["choiceLists"][0]["choices"]][:2] == [
        "Never",
        "Almost never",
    ]
    [total] = frag["variables"]
    assert total["id"] == "pss_10_total" and total["expr"]["kind"] == "arith"

    # Private like every licensed item: the lab reads it, nobody shares it.
    assert editor.get(f"/api/bank/{s['id']}").status_code == 200
    r = owner.post(f"/api/bank/{s['id']}/share", json={"visibility": "host"})
    assert r.status_code == 422 and r.json()["diagnostics"][0]["code"] == "bank.not_shareable"
    assert editor.get(f"/api/bank/{s['id']}/export").status_code == 403
    # The store's audit row records the class (the attestation record).
    rows = benv.store.audit_rows(benv.tenants["A"]) if hasattr(benv.store, "audit_rows") else None
    if rows is not None:
        assert any(r_.get("action") == "bank.save" for r_ in rows)


def test_licensed_copy_rules(benv):
    owner, editor = benv.login("owner@a.example"), benv.login("editor@a.example")
    # Owner only.
    assert _compose(editor).status_code == 403
    # Attestation required.
    r = _compose(owner, attest=False)
    assert (
        r.status_code == 422 and r.json()["diagnostics"][0]["code"] == "bank.licensed_attestation"
    )
    # The item count must match the stub.
    r = _compose(owner, items=_lines(9))
    assert r.status_code == 422 and r.json()["diagnostics"][0]["code"] == "bank.stub_items"
    # Unknown stub.
    assert _compose(owner, stubId="nope").status_code == 422
    # Per-item stubs need options on every line.
    r = _compose(owner, stubId="bdi-ii", items=_lines(21))
    assert r.status_code == 422 and r.json()["diagnostics"][0]["code"] == "bank.compose_items"
    r = _compose(owner, stubId="bdi-ii", items=_lines(21, options=4), layout="single")
    assert r.status_code == 201, r.text
    frag = r.json()["document"]["fragment"]
    qs = frag["block"]["pages"][0]["items"]
    assert len(qs) == 21 and all(q["type"] == "single" and len(q["choices"]) == 4 for q in qs)
    assert frag["choiceLists"] == []
    # Lines too long / unknown keys are 422s from the request model.
    assert _compose(owner, bogus=1).status_code == 422
    assert _compose(owner, items=[]).status_code == 422


def test_blank_licensed_copy_without_a_stub(benv):
    owner = benv.login("owner@a.example")
    body = {
        "items": ["One", "Two", "Three"],
        "attest": True,
        "title": "Our licensed scale",
        "abbreviation": "OLS",
        "layout": "single",
        "stem": "Rate each statement.",
        "scale": {"min": 1, "max": 3},
        "labels": ["Low", "Mid", "High"],
        "scoring": {"aggregate": "mean", "reversed": [2], "subscales": {"first two": [1, 2]}},
        "language": "en",
        "tags": ["own"],
    }
    r = owner.post("/api/bank/licensed", json=body)
    assert r.status_code == 201, r.text
    doc = r.json()["document"]
    assert doc["title"] == "Our licensed scale" and doc.get("citation") is None
    assert sorted(doc["tags"]) == ["licensed", "own"]
    frag = doc["fragment"]
    assert [v["id"] for v in frag["variables"]] == ["ols_total", "ols_first_two"]
    assert frag["block"]["pages"][0]["items"][0] == {
        "id": "ols_stem",
        "type": "note",
        "label": {"en": "Rate each statement."},
    }
    assert doc["languages"] == ["en"]
    # Without a scale or title it is refused.
    assert (
        owner.post("/api/bank/licensed", json={"items": ["a"], "attest": True}).status_code == 422
    )
    assert (
        owner.post(
            "/api/bank/licensed", json={"items": ["a"], "attest": True, "title": "t"}
        ).status_code
        == 422
    )
    # A bad prefix is a compose diagnostic.
    r = owner.post(
        "/api/bank/licensed",
        json={
            "items": ["a"],
            "attest": True,
            "title": "t",
            "scale": {"min": 0, "max": 1},
            "prefix": "1x",
        },
    )
    assert r.status_code == 422 and r.json()["diagnostics"][0]["code"] == "bank.compose_prefix"
