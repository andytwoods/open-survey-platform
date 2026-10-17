"""Media (planning/media.md §2.3) over HTTP: the media policy route, the live
`media.origin_not_allowed` diagnostics after an edit, and the publish refusal."""

from __future__ import annotations

RETENTION = {
    "op": "set_property",
    "params": {"target": "/settings", "property": "retention", "value": {"kind": "indefinite"}},
}
CONSENT = {"op": "set_consent", "params": {"consent": {"text": "Agree?"}}}


def _media_op(target: str, url: str) -> dict:
    return {
        "op": "set_property",
        "params": {
            "target": target,
            "property": "media",
            "value": [{"kind": "image", "url": url, "alt": "A picture"}],
        },
    }


def _first_question(c, survey_id: str) -> str:
    body = c.get(f"/api/surveys/{survey_id}").json()["survey"]
    return body["blocks"][0]["pages"][0]["items"][0]["id"]


def test_media_policy_route(benv):
    c = benv.login("viewer@a.example")
    unchecked = c.get("/api/meta/media-policy")
    assert unchecked.status_code == 200
    assert unchecked.json() == {
        "checked": False,
        "allowedOrigins": [],
        "csp": {"imgSrc": "'self' data: blob:", "mediaSrc": "'self' blob:"},
    }
    benv.services.builder.media_origins = ("https://cdn.example.org",)
    checked = c.get("/api/meta/media-policy").json()
    assert checked["checked"] is True and checked["allowedOrigins"] == ["https://cdn.example.org"]
    assert checked["csp"]["mediaSrc"] == "'self' blob: https://cdn.example.org"
    assert benv.client().get("/api/meta/media-policy").status_code == 401


def test_disallowed_origin_is_a_live_diagnostic_and_blocks_publish(benv):
    benv.services.builder.media_origins = ("https://cdn.example.org",)
    c = benv.login("editor@a.example")
    s = c.post("/api/surveys", json={"title": "Pictures"}).json()
    qid = _first_question(c, s["id"])
    bad = c.post(
        f"/api/surveys/{s['id']}/ops",
        json={
            "ops": [RETENTION, CONSENT, _media_op(qid, "https://elsewhere.example/a.png")],
            "baseRevision": 0,
        },
    )
    assert bad.status_code == 200, (
        bad.text
    )  # the edit lands: it is valid, just not publishable here
    codes = {(d["code"], d["pointer"]) for d in bad.json()["diagnostics"]}
    assert ("media.origin_not_allowed", "/blocks/0/pages/0/items/0/media/0/url") in codes
    loaded = c.get(f"/api/surveys/{s['id']}").json()["diagnostics"]  # on load, too
    assert any(d["code"] == "media.origin_not_allowed" for d in loaded)
    pub = c.post(f"/api/surveys/{s['id']}/publish", json={"baseRevision": bad.json()["revision"]})
    assert pub.status_code == 422
    assert any(d["code"] == "media.origin_not_allowed" for d in pub.json()["diagnostics"])
    # An allowed origin, and a same-origin path, publish.
    ok = c.post(
        f"/api/surveys/{s['id']}/ops",
        json={
            "ops": [_media_op(qid, "https://cdn.example.org/a.png")],
            "baseRevision": bad.json()["revision"],
        },
    )
    assert ok.status_code == 200
    assert not any(d["code"].startswith("media.") for d in ok.json()["diagnostics"])
    pub = c.post(f"/api/surveys/{s['id']}/publish", json={"baseRevision": ok.json()["revision"]})
    assert pub.status_code == 201, pub.text
