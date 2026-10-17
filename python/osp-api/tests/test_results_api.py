"""Results viewer endpoints (task V1): the HTTP shape of ``POST .../results/query`` and
``GET .../results/text/{question}``. The aggregation itself is tested with hand-computed
expectations in ``python/osp-app/tests/test_results.py``; this reuses its fixture data."""

from __future__ import annotations

import copy
import importlib.util
import json
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


def test_watermark_endpoint(benv):
    c, sid, ctx = _setup(benv)
    before = len(benv.store.list_audit(ctx))
    r = c.get(f"/api/surveys/{sid}/results/watermark")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["responses"] == 5 and body["versionsUsed"] == [1]
    assert body["pollAfterMs"] == 10_000 and set(body) == {
        "watermark", "responses", "versionsUsed", "pollAfterMs",
    }  # fmt: skip
    assert len(benv.store.list_audit(ctx)) == before  # not audited
    assert r.headers["cache-control"] == "no-store"
    q = c.post(f"/api/surveys/{sid}/results/query", json={}).json()
    assert q["watermark"] == body["watermark"]
    data.add_response(benv.store, ctx, data.publish(benv.store, ctx, sid, data.SURVEY).id, {})
    both = c.get(f"/api/surveys/{sid}/results/watermark", params={"versions": [1, 2]})
    assert both.json()["versionsUsed"] == [1, 2] and both.json()["responses"] == 6
    latest = c.get(f"/api/surveys/{sid}/results/watermark").json()
    assert latest["versionsUsed"] == [2] and latest["watermark"] != body["watermark"]
    url = f"/api/surveys/{sid}/results/watermark"
    assert c.get(url, params={"versions": [7]}).status_code == 404
    assert c.get(url, params={"versions": [0]}).status_code == 422
    assert benv.login("viewer@a.example").get(url).status_code == 403
    assert benv.login("owner@b.example").get(url).status_code == 404


def test_watermark_is_rate_limited_per_actor(benv):
    from osp_runtime import TokenBucket

    c, sid, _ = _setup(benv)
    benv.app.state.watermark_limiter = TokenBucket(5, 1, lambda: benv.clock.now())
    url = f"/api/surveys/{sid}/results/watermark"
    codes = [c.get(url).status_code for _ in range(7)]
    assert codes == [200] * 5 + [429] * 2
    refused = c.get(url)
    assert refused.json()["code"] == "rate_limited" and "pollAfterMs" in refused.json()["message"]
    assert benv.login("owner@a.example").get(url).status_code == 200  # another actor's budget
    benv.clock.advance(seconds=1)
    assert c.get(url).status_code == 200  # one a second after the burst
    assert c.get(url).status_code == 429


def test_live_query_is_audited_as_results_live(benv):
    c, sid, ctx = _setup(benv)
    url = f"/api/surveys/{sid}/results/query"
    first = c.post(url, json={"live": True, "cards": [{"question": "fruit"}]})
    assert first.status_code == 200, first.text
    again = c.post(url, json={"live": True, "cards": [{"question": "fruit"}]})
    assert again.json()["cached"] is True and again.json()["queryHash"] == first.json()["queryHash"]
    manual = c.post(url, json={"cards": [{"question": "fruit"}]})
    assert manual.json()["queryHash"] == first.json()["queryHash"]
    actions = [a.action for a in benv.store.list_audit(ctx) if a.action.startswith("results.")]
    assert actions == ["results.live", "results.read"]
    assert c.post(url, json={"live": "maybe"}).status_code == 422


def test_export_is_recorded_without_values(benv):
    c, sid, ctx = _setup(benv)
    query = {"split": {"condition": "arm"}, "denominator": "shown"}
    shown = c.post(f"/api/surveys/{sid}/results/query", json=query).json()
    body = {
        "query": query,
        "cards": ["fruit", "why"],
        "formats": ["png", "svg", "png"],
        "scope": "page",
        "suppressBelow": 5,
    }
    r = c.post(f"/api/surveys/{sid}/results/export", json=body)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "recorded": True,
        "queryHash": shown["queryHash"],
        "versions": [1],
        "formats": ["svg", "png"],
    }
    rows = [a for a in benv.store.list_audit(ctx) if a.action == "results.export"]
    assert len(rows) == 1
    detail = rows[0].detail
    assert detail["cards"] == ["fruit", "why"] and detail["scope"] == "page"
    assert detail["suppressBelow"] == 5 and detail["query"]["denominator"] == "shown"
    assert "sunny" not in json.dumps(detail) and "count" not in json.dumps(detail)


def test_export_errors(benv):
    c, sid, ctx = _setup(benv)
    ok = {"query": {}, "cards": ["fruit"], "formats": ["csv"]}
    url = f"/api/surveys/{sid}/results/export"
    assert c.post(url, json={**ok, "formats": ["pdf"]}).status_code == 422
    assert c.post(url, json={**ok, "formats": []}).status_code == 422
    assert c.post(url, json={**ok, "cards": []}).status_code == 422
    assert c.post(url, json={**ok, "suppressBelow": 0}).status_code == 422
    assert c.post(url, json={**ok, "query": {"versions": [9]}}).status_code == 404
    assert benv.login("viewer@a.example").post(url, json=ok).status_code == 403
    assert benv.login("owner@b.example").post(url, json=ok).status_code == 404
    actions = [a.action for a in benv.store.list_audit(ctx)]
    assert "results.export" not in actions
