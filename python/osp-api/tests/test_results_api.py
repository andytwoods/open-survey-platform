"""Results viewer endpoints (task V1): the HTTP shape of ``POST .../results/query`` and
``GET .../results/text/{question}``. The aggregation itself is tested with hand-computed
expectations in ``python/osp-app/tests/test_results.py``; this reuses its fixture data."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

from osp_store import TenantContext

_spec = importlib.util.spec_from_file_location(
    "results_data", Path(__file__).resolve().parents[2] / "osp-app/tests/results_data.py"
)
data = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(data)


def _setup(benv):
    c = benv.login("editor@a.example")
    r = c.post("/api/surveys", json={"title": "Results", "survey": data.SURVEY})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    ctx = TenantContext(benv.tenants["A"], "system:test")
    v1 = data.publish(benv.store, ctx, sid, data.SURVEY)
    data.seed(benv.store, ctx, v1.id)
    return c, sid, ctx


def test_query_every_card_through_the_response_model(benv):
    c, sid, _ = _setup(benv)
    r = c.post(
        f"/api/surveys/{sid}/results/query", json={"intervals": True, "split": {"condition": "arm"}}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["responses"] == 5 and body["cached"] is False
    assert {card["type"] for card in body["cards"]} == {
        "single", "multi", "integer", "decimal", "slider", "date", "text", "matrix",
    }  # fmt: skip
    fruit = body["cards"][0]
    assert [g["key"] for g in fruit["groups"]] == ["a", "b", "_missing"]
    assert fruit["groups"][0]["cells"][0]["ci"] is not None
    again = c.post(
        f"/api/surveys/{sid}/results/query", json={"intervals": True, "split": {"condition": "arm"}}
    )
    assert again.json()["cached"] is True


def test_facets_serialise(benv):
    c, sid, ctx = _setup(benv)
    body = copy.deepcopy(data.SURVEY)
    body["choiceLists"][0]["choices"].append({"value": "date", "label": "Date"})
    v2 = data.publish(benv.store, ctx, sid, body)
    data.add_response(benv.store, ctx, v2.id, {"fruit": data.A("date")})
    r = c.post(
        f"/api/surveys/{sid}/results/query",
        json={"versions": [1, 2], "cards": [{"question": "fruit"}]},
    )
    assert r.status_code == 200, r.text
    card = r.json()["cards"][0]
    assert [f["version"] for f in card["facets"]] == [1, 2]
    assert card["warnings"][0]["code"] == "versions.incompatible"


def test_text_endpoint(benv):
    c, sid, _ = _setup(benv)
    r = c.get(f"/api/surveys/{sid}/results/text/why?limit=2")
    assert r.status_code == 200, r.text
    page = r.json()
    assert [i["value"] for i in page["items"]] == ["sunny", "rain!"] and page["total"] == 3
    nxt = c.get(f"/api/surveys/{sid}/results/text/why", params={"cursor": page["nextCursor"]})
    assert [i["value"] for i in nxt.json()["items"]] == ["ok"]
    f = c.get(f"/api/surveys/{sid}/results/text/why", params={"filter": "fruit:apple"})
    assert [i["value"] for i in f.json()["items"]] == ["sunny"]
    assert c.get(f"/api/surveys/{sid}/results/text/age").status_code == 422
    assert c.get(f"/api/surveys/{sid}/results/text/nope").status_code == 404


def test_errors(benv):
    c, sid, _ = _setup(benv)
    assert c.post(f"/api/surveys/{sid}/results/query", json={"status": "x"}).status_code == 422
    assert c.post(f"/api/surveys/{sid}/results/query", json={"versions": [7]}).status_code == 404
    bad = c.post(f"/api/surveys/{sid}/results/query", json={"split": {"question": "col"}})
    assert bad.status_code == 422
    b = benv.login("owner@b.example")
    assert b.post(f"/api/surveys/{sid}/results/query", json={}).status_code == 404
    assert b.get(f"/api/surveys/{sid}/results/text/why").status_code == 404
    v = benv.login("viewer@a.example")
    assert v.post(f"/api/surveys/{sid}/results/query", json={}).status_code == 403
    assert v.get(f"/api/surveys/{sid}/results/text/why").status_code == 403
    actions = [a.action for a in benv.store.list_audit(TenantContext(benv.tenants["A"], "x"))]
    assert "results.read" not in actions  # refused calls read nothing
