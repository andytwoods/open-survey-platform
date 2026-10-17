from __future__ import annotations


def test_me_lists_the_actor_and_their_labs(benv):
    c = benv.login("owner@a.example")
    me = c.get("/api/me")
    assert me.status_code == 200
    body = me.json()
    assert body["displayName"] == "owner@a.example"
    assert [m["role"] for m in body["memberships"]] == ["owner"]
    assert "csrfToken" not in body


def test_me_needs_an_identity(benv):
    assert benv.client().get("/api/me").status_code == 401
