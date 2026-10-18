"""External-task handoff and return over HTTP (task EX2, planning/external-tasks.md): the
server mints a signed return token for an `externalTask` node and verifies it on return,
rejecting a tampered token (403), an expired one (410, covered at the service level) and a
token used for another node (403). The node ids reach the published runtime config."""

from __future__ import annotations

SURVEY = {
    "specVersion": "osp-survey/0.1",
    "id": "ext",
    "metadata": {"title": {"en": "Ext"}, "languages": ["en"], "defaultLanguage": "en"},
    "settings": {
        "retention": {"kind": "indefinite"},
        "redirectTemplates": {
            "task": {"url": "https://run.pavlovia.org/lab/e?pid={pid}", "params": {"pid": {}}}
        },
    },
    "variables": [{"id": "rt", "kind": "embedded", "source": "url", "param": "rt",
                   "valueType": "integer"}],
    "blocks": [{"id": "b1", "pages": [{"id": "p1", "items": [
        {"id": "q1", "type": "text", "label": {"en": "hi"}}]}]}],
    "flow": [
        {"type": "block", "id": "n1", "block": "b1"},
        {"type": "externalTask", "id": "et1", "template": "task", "params": {"pid": "p1"},
         "returns": ["rt"]},
        {"type": "externalTask", "id": "et2", "template": "task", "params": {"pid": "p1"}},
        {"type": "end", "id": "e1"},
    ],
}  # fmt: skip


def _publish_and_start(benv) -> tuple[object, str, str]:
    c = benv.login("owner@a.example")
    r = c.post("/api/surveys", json={"title": "Ext", "survey": SURVEY})
    assert r.status_code == 201, r.text
    sid_survey = r.json()["id"]
    p = c.post(f"/api/surveys/{sid_survey}/publish", json={"baseRevision": 0})
    assert p.status_code == 201, p.text
    slug = p.json()["slug"]
    participant = benv.client()
    start = participant.post(f"/api/s/{slug}/sessions")
    assert start.status_code == 201, start.text
    body = start.json()
    return participant, body["sessionId"], body["resumeToken"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_handoff_then_return_round_trip(benv):
    client, sid, token = _publish_and_start(benv)
    h = client.post(f"/api/sessions/{sid}/external/et1/handoff", headers=_auth(token))
    assert h.status_code == 200, h.text
    rt = h.json()["returnToken"]
    assert rt and "expiresAt" in h.json()
    back = client.post(
        f"/api/sessions/{sid}/external/et1/return",
        headers=_auth(token),
        json={"returnToken": rt},
    )
    assert back.status_code == 200, back.text
    assert back.json() == {"ok": True, "nodeId": "et1"}


def test_handoff_refuses_a_non_external_node(benv):
    client, sid, token = _publish_and_start(benv)
    r = client.post(f"/api/sessions/{sid}/external/n1/handoff", headers=_auth(token))
    assert r.status_code == 404, r.text


def test_return_rejects_a_tampered_token(benv):
    client, sid, token = _publish_and_start(benv)
    rt = client.post(f"/api/sessions/{sid}/external/et1/handoff", headers=_auth(token)).json()[
        "returnToken"
    ]
    body, sig = rt.split(".", 1)
    forged = f"{body}.{sig[:-1]}{'a' if sig[-1] != 'a' else 'b'}"
    r = client.post(
        f"/api/sessions/{sid}/external/et1/return",
        headers=_auth(token),
        json={"returnToken": forged},
    )
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "external.token_invalid"


def test_return_rejects_a_token_minted_for_another_node(benv):
    client, sid, token = _publish_and_start(benv)
    rt = client.post(f"/api/sessions/{sid}/external/et1/handoff", headers=_auth(token)).json()[
        "returnToken"
    ]
    r = client.post(
        f"/api/sessions/{sid}/external/et2/return",
        headers=_auth(token),
        json={"returnToken": rt},
    )
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "external.token_invalid"


def test_handoff_needs_the_session_token(benv):
    client, sid, _token = _publish_and_start(benv)
    r = client.post(f"/api/sessions/{sid}/external/et1/handoff")
    assert r.status_code == 401, r.text
