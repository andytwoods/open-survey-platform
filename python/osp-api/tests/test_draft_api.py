"""PUT /api/surveys/{id}/draft (task CE5): the builder saves a patch it made in the browser;
the server applies it, validates the whole document and stores it, or refuses it whole."""

from __future__ import annotations

from typing import Any

import pytest
from osp_ops import diff_patch, run
from osp_store import TenantContext

INTRO = "/blocks/0/pages/0/items/0"
TITLE = {"op": "replace", "path": "/metadata/title/en", "value": "Mood study"}
SET_TITLE = {"op": "set_title", "params": {"title": {"en": "Mood study"}}}


def _create(c, title: str = "First") -> dict:
    r = c.post("/api/surveys", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()


def _put(c, sid: str, patch: list, base: int = 0, ops: list | None = None, txn: str = "t1"):
    body: dict[str, Any] = {"baseRevision": base, "patch": patch, "transactionId": txn}
    if ops is not None:
        body["ops"] = ops
    return c.put(f"/api/surveys/{sid}/draft", json=body)


def _draft(c, sid: str) -> dict:
    return c.get(f"/api/surveys/{sid}").json()


def test_save_applies_the_patch_and_answers_revision_and_diagnostics(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    r = _put(c, s["id"], [TITLE], ops=[SET_TITLE])
    assert r.status_code == 200, r.text
    assert r.json() == {
        "revision": 1,
        "diagnostics": [],
        "transactionId": "t1",
        "replayed": False,
    }
    got = _draft(c, s["id"])
    assert got["revision"] == 1 and got["survey"]["metadata"]["title"]["en"] == "Mood study"
    assert c.get("/api/surveys").json()[0]["title"] == "Mood study"  # listing kept in step


def test_diagnostics_are_the_validators_for_the_saved_document(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    # An unknown name in a condition is a diagnostic, as with set_condition, not a refusal.
    added = run("add_question", s["survey"], {"page": "p1", "type": "integer"})
    qid = added.survey["blocks"][0]["pages"][0]["items"][1]["id"]
    cond = run("set_condition", added.survey, {"target": qid, "condition": "nope == 1"})
    assert cond.ok
    r = _put(c, s["id"], diff_patch(s["survey"], cond.survey))
    assert r.status_code == 200, r.text
    assert "ref.unknown" in [d["code"] for d in r.json()["diagnostics"]]


def test_a_stale_base_revision_is_409_and_saves_nothing(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    assert _put(c, s["id"], [TITLE]).status_code == 200
    other = {"op": "replace", "path": "/metadata/title/en", "value": "Other"}
    stale = _put(c, s["id"], [other], base=0, txn="t2")
    assert stale.status_code == 409
    assert stale.json()["code"] == "op.conflict" and stale.json()["currentRevision"] == 1
    assert _draft(c, s["id"])["survey"]["metadata"]["title"]["en"] == "Mood study"


def _refused(c, sid: str, patch: list, code: str, ops: list | None = None) -> dict:
    r = _put(c, sid, patch, ops=ops)
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["diagnostics"][0]["code"] == code, body
    got = _draft(c, sid)
    assert got["revision"] == 0  # nothing saved
    assert c.get(f"/api/surveys/{sid}/history").json() == []  # nothing logged
    return body


def test_rich_text_with_a_javascript_link_is_refused(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    rich = {
        "type": "rich",
        "blocks": [{"type": "p", "content": [{"text": "x", "href": "javascript:alert(1)"}]}],
    }
    body = _refused(
        c, s["id"], [{"op": "replace", "path": f"{INTRO}/label", "value": rich}], "op.invalid_text"
    )
    assert "link.scheme" in [d["code"] for d in body["diagnostics"]]


def test_too_long_text_is_refused(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    long = {"op": "replace", "path": f"{INTRO}/label", "value": {"en": "x" * 20_001}}
    body = _refused(c, s["id"], [long], "op.invalid_text")
    assert "text.too_long" in [d["code"] for d in body["diagnostics"]]


def test_a_broken_reference_is_refused(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    flow = {"op": "replace", "path": "/flow/0/block", "value": "no_such_block"}
    body = _refused(c, s["id"], [flow], "op.dangling_ref")
    assert "ref.unknown_block" in [d["code"] for d in body["diagnostics"]]


def test_a_forced_delete_may_leave_a_dangling_reference(benv):
    """`force` is the researcher's "delete anyway": the op registry lets the reference
    dangle (a diagnostic), so the save does too."""
    c = benv.login("editor@a.example")
    s = _create(c)
    flow = {"op": "replace", "path": "/flow/0/block", "value": "no_such_block"}
    forced = [{"op": "delete_block", "params": {"id": "b1", "force": True}}]
    r = _put(c, s["id"], [flow], ops=forced)
    assert r.status_code == 200, r.text
    assert "ref.unknown_block" in [d["code"] for d in r.json()["diagnostics"]]


def test_a_duplicate_id_is_refused_unless_a_whole_document_op_made_it(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    dup = {"id": "intro", "type": "note", "label": {"en": "again"}}
    add = [{"op": "add", "path": "/blocks/0/pages/0/items/-", "value": dup}]
    _refused(c, s["id"], add, "op.duplicate_id")
    whole = [{"op": "replace_survey", "params": {"survey": {}}}]  # the JSON view's Apply
    assert _put(c, s["id"], add, ops=whole).status_code == 200


def test_a_structurally_invalid_result_is_refused(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    body = _refused(
        c, s["id"], [{"op": "replace", "path": "/blocks", "value": "x"}], "op.invalid_result"
    )
    assert len(body["diagnostics"]) > 1


@pytest.mark.parametrize(
    "patch",
    [
        [{"op": "replace", "path": "/nope/deeper", "value": 1}],
        [{"op": "remove", "path": "/blocks/7"}],
        [{"op": "test", "path": "/metadata/title/en", "value": "not the title"}],
        [{"op": "frobnicate", "path": ""}],
    ],
)
def test_a_patch_that_does_not_apply_is_refused(benv, patch):
    c = benv.login("editor@a.example")
    s = _create(c)
    _refused(c, s["id"], patch, "op.patch")


def test_an_unknown_op_name_is_refused(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    _refused(c, s["id"], [TITLE], "op.unknown", ops=[{"op": "nope", "params": {}}])


def test_bad_requests_are_422(benv):
    c = benv.login("editor@a.example")
    sid = _create(c)["id"]
    url = f"/api/surveys/{sid}/draft"
    for body in (
        {"baseRevision": 0, "patch": [TITLE]},  # no transactionId
        {"baseRevision": 0, "patch": [TITLE], "transactionId": "has:colon"},
        {"baseRevision": -1, "patch": [TITLE], "transactionId": "t"},
        {"baseRevision": 0, "patch": {"op": "add"}, "transactionId": "t"},
        {"baseRevision": 0, "patch": [TITLE], "transactionId": "t", "extra": 1},
    ):
        assert c.put(url, json=body).status_code == 422, body
    assert _draft(c, sid)["revision"] == 0


def test_a_retry_with_the_same_transaction_id_is_not_applied_twice(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    first = _put(c, s["id"], [TITLE], ops=[SET_TITLE], txn="client-1").json()
    again = _put(c, s["id"], [TITLE], ops=[SET_TITLE], txn="client-1")
    assert again.status_code == 200
    assert again.json() == {
        "revision": first["revision"],
        "diagnostics": [],
        "transactionId": "client-1",
        "replayed": True,
    }
    assert _draft(c, s["id"])["revision"] == 1


def test_a_patch_that_changes_nothing_keeps_the_revision(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    same = {"op": "replace", "path": "/metadata/title/en", "value": "First"}
    r = _put(c, s["id"], [same])
    assert r.status_code == 200
    assert r.json()["revision"] == 0 and r.json()["transactionId"] is None
    assert c.get(f"/api/surveys/{s['id']}/history").json() == []


def test_the_op_names_are_logged_and_the_save_can_be_undone_by_other_clients(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    q = {"id": "q1", "type": "text", "label": {"en": "Name?"}}
    ops = [
        SET_TITLE,
        {"op": "add_question", "params": {"page": "p1", "type": "text"}},
    ]
    patch = [TITLE, {"op": "add", "path": "/blocks/0/pages/0/items/-", "value": q}]
    assert _put(c, s["id"], patch, ops=ops, txn="audit-1").status_code == 200
    history = c.get(f"/api/surveys/{s['id']}/history").json()
    assert [(h["transactionId"], h["kind"], h["ops"]) for h in history] == [
        ("audit-1", "edit", ["set_title", "add_question"])
    ]
    # POST /undo (MCP, another client) reverses the whole save.
    undo = c.post(
        f"/api/surveys/{s['id']}/undo", json={"transactionId": "audit-1", "baseRevision": 1}
    )
    assert undo.status_code == 200, undo.text
    got = _draft(c, s["id"])
    assert got["survey"] == s["survey"] and got["revision"] == 2


def test_a_save_without_ops_logs_one_apply_patch(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    assert _put(c, s["id"], [TITLE]).status_code == 200
    assert [h["ops"] for h in c.get(f"/api/surveys/{s['id']}/history").json()] == [["apply_patch"]]


def test_a_hooks_change_is_audited_as_for_ops(benv):
    c = benv.login("editor@a.example")
    s = _create(c)
    hooks = {
        "format": "osp-hooks/1",
        "source": "osp.on('onStart', function () {});",
        "handlers": {"onStart": {"reads": [], "writes": []}},
    }
    r = _put(
        c,
        s["id"],
        [{"op": "add", "path": "/hooks", "value": hooks}],
        ops=[{"op": "set_hooks", "params": {"hooks": hooks}}],
        txn="hooks-1",
    )
    assert r.status_code == 200, r.text
    audit = benv.store.list_audit(TenantContext(benv.tenants["A"], "test"))
    changed = [a for a in audit if a.action == "survey.hooks_changed"]
    assert len(changed) == 1
    assert changed[0].detail["transaction"] == "hooks-1"
    assert changed[0].detail["ops"] == ["set_hooks"]


def test_permissions(benv):
    owner = benv.login("owner@a.example")
    sid = _create(owner)["id"]
    viewer = benv.login("viewer@a.example")
    assert _put(viewer, sid, [TITLE]).status_code == 403
    editor = benv.login("editor@a.example")
    assert _put(editor, sid, [TITLE], txn="e1").status_code == 200
    assert _put(owner, sid, [], base=1, txn="o1").status_code == 200


def test_another_lab_gets_not_found_and_changes_nothing(benv):
    sid = _create(benv.login("owner@a.example"))["id"]
    other = benv.login("owner@b.example")
    assert _put(other, sid, [TITLE]).status_code == 404
    assert _put(other, "0" * 36, [TITLE]).status_code == 404  # the same as a random id
    assert _draft(benv.login("owner@a.example"), sid)["revision"] == 0
