"""Question bank API (task QB4): save from a survey, versions, metadata, host sharing and
the host switch, soft delete, export/import, the bundled library, copies, permissions per
role, tenant isolation, audit, identity and origin."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from osp_instruments import library_ids, load_document
from osp_store import TenantContext


def ref(qid: str) -> dict[str, Any]:
    return {"kind": "ref", "id": qid}


def _survey() -> dict[str, Any]:
    """`demo` is a two-item invented instrument with a total; its second item depends on
    `age` in the other block (cut at save with a warning)."""
    return {
        "specVersion": "osp-survey/0.1",
        "id": "bank_api",
        "metadata": {"title": "Bank API", "languages": ["en", "de"]},
        "choiceLists": [
            {"id": "agree4", "choices": [
                {"value": 0, "label": {"en": "Never", "de": "Nie"}},
                {"value": 1, "label": {"en": "Often", "de": "Oft"}},
            ]},
        ],
        "variables": [
            {"id": "demo_total", "kind": "computed",
             "expr": {"kind": "arith", "op": "+", "left": ref("demo_q1"), "right": ref("demo_q2")}},
        ],
        "blocks": [
            {"id": "other", "pages": [{"id": "p_other", "items": [
                {"id": "age", "type": "integer", "label": "Age"},
            ]}]},
            {"id": "demo", "title": "Demo scale", "pages": [{"id": "p_demo", "items": [
                {"id": "demo_q1", "type": "single", "label": {"en": "Item one", "de": "Eins"},
                 "choiceList": "agree4"},
                {"id": "demo_q2", "type": "single", "choiceList": "agree4",
                 "label": {"en": "Item two", "de": "Zwei"},
                 "showIf": {"kind": "answered", "ref": ref("age")}},
            ]}]},
        ],
        "flow": [
            {"type": "block", "id": "f1", "block": "other"},
            {"type": "block", "id": "f2", "block": "demo"},
        ],
    }  # fmt: skip


@pytest.fixture
def survey(benv):
    c = benv.login("editor@a.example")
    r = c.post("/api/surveys", json={"title": "Bank API", "survey": _survey()})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _save(c, sid: str, target: str = "demo", **extra) -> dict:
    body = {"surveyId": sid, "targetId": target, "title": "Demo scale", **extra}
    r = c.post("/api/bank", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _ids(items: list[dict]) -> list[str]:
    return [i["id"] for i in items]


# --- save, list, get --------------------------------------------------------------------


def test_save_from_a_survey_and_find_it_again(benv, survey):
    c = benv.login("editor@a.example")
    saved = _save(c, survey, tags=["demo", "invented"], abbreviation="DEMO")
    assert [d["code"] for d in saved["diagnostics"]] == ["bank.external_ref"]  # showIf cut
    item, doc = saved["item"], saved["item"]["document"]
    assert item["version"] == 1 and item["checksum"].startswith("sha256:")
    s = item["summary"]
    assert (s["source"], s["kind"], s["version"], s["visibility"]) == ("lab", "block", 1, "lab")
    assert s["licenceClass"] == "unknown"  # lead decision 3: a lab's own words
    assert s["itemCount"] == 2 and sorted(s["languages"]) == ["de", "en"] and s["canEdit"] is True
    assert s["labId"] == benv.tenants["A"] and s["createdBy"] == "editor@a.example"
    assert doc["bankVersion"] == "osp-bank-item/0.1" and doc["id"] == s["id"]
    assert doc["version"] == 1 and doc["licence"] == {"class": "unknown"}
    assert [v["id"] for v in doc["fragment"]["variables"]] == ["demo_total"]
    assert "showIf" not in doc["fragment"]["block"]["pages"][0]["items"][1]
    assert doc["fragment"]["choiceLists"][0]["id"] == "agree4"

    got = c.get(f"/api/bank/{s['id']}")
    assert got.status_code == 200 and got.json() == item
    assert c.get(f"/api/bank/{s['id']}", params={"version": 1}).json() == item
    assert c.get(f"/api/bank/{s['id']}", params={"version": 2}).status_code == 404
    assert c.get(f"/api/bank/{s['id']}", params={"version": 0}).status_code == 422

    lst = c.get("/api/bank").json()
    assert lst["tenantId"] == benv.tenants["A"] and lst["hostSharing"] is True
    assert lst["canManage"] is True and lst["canShare"] is False  # an editor
    assert lst["total"] == 1 + len(library_ids()) == len(lst["items"])
    assert s["id"] in _ids(lst["items"]) and "gad2" in _ids(lst["items"])
    assert [i["title"] for i in lst["items"]] == sorted(
        (i["title"] for i in lst["items"]), key=str.lower
    )
    assert _ids(c.get("/api/bank", params={"source": "lab"}).json()["items"]) == [s["id"]]
    assert _ids(c.get("/api/bank", params={"source": "host"}).json()["items"]) == []
    assert s["id"] not in _ids(c.get("/api/bank", params={"source": "bundled"}).json()["items"])
    assert _ids(c.get("/api/bank", params={"q": "EINS"}).json()["items"]) == [s["id"]]  # a label
    assert s["id"] in _ids(c.get("/api/bank", params={"q": "item two"}).json()["items"])
    assert _ids(c.get("/api/bank", params={"q": "zwei demo"}).json()["items"]) == [s["id"]]
    assert _ids(c.get("/api/bank", params={"q": "demo nothing"}).json()["items"]) == []
    assert _ids(c.get("/api/bank", params={"tag": ["invented"]}).json()["items"]) == [s["id"]]
    assert _ids(c.get("/api/bank", params={"lang": "de"}).json()["items"]) == [s["id"]]
    assert _ids(c.get("/api/bank", params={"licence": "unknown"}).json()["items"]) == [s["id"]]
    assert _ids(c.get("/api/bank", params={"kind": "question"}).json()["items"]) == []
    anxiety = c.get("/api/bank", params={"q": "anxious", "kind": "block"}).json()
    assert {"gad2", "gad7"} <= set(_ids(anxiety["items"]))
    page = c.get("/api/bank", params={"page": 2, "pageSize": 2}).json()
    assert (page["page"], page["pageSize"], len(page["items"])) == (2, 2, 2)
    assert page["items"] == lst["items"][2:4]
    assert c.get("/api/bank", params={"page": 0}).status_code == 422
    assert c.get("/api/bank", params={"pageSize": 201}).status_code == 422
    assert c.get("/api/bank", params={"source": "public"}).status_code == 422


def test_save_refusals(benv, survey):
    c = benv.login("editor@a.example")
    r = c.post("/api/bank", json={"surveyId": survey, "targetId": "nope", "title": "x"})
    assert r.status_code == 422 and r.json()["diagnostics"][0]["code"] == "bank.target_not_found"
    r = c.post("/api/bank", json={"surveyId": "0" * 36, "targetId": "demo", "title": "x"})
    assert r.status_code == 404
    r = c.post("/api/bank", json={"surveyId": survey, "targetId": "demo", "title": ""})
    assert r.status_code == 422
    r = c.post(
        "/api/bank", json={"surveyId": survey, "targetId": "demo", "title": "x", "tags": ["x" * 41]}
    )
    assert r.status_code == 422 and r.json()["diagnostics"][0]["pointer"] == "/tags/0"
    r = c.post(
        "/api/bank",
        json={"surveyId": survey, "targetId": "demo", "title": "x", "licence": {"class": "gpl"}},
    )
    assert r.status_code == 422 and r.json()["diagnostics"][0]["pointer"] == "/licence/class"
    assert c.get("/api/bank", params={"source": "lab"}).json()["items"] == []
    # A viewer reads the bank but can't save; another lab's owner can't see the survey.
    v = benv.login("viewer@a.example")
    assert v.get("/api/bank").status_code == 200
    assert (
        v.post("/api/bank", json={"surveyId": survey, "targetId": "demo", "title": "x"}).status_code
        == 403
    )
    b = benv.login("owner@b.example")
    assert (
        b.post("/api/bank", json={"surveyId": survey, "targetId": "demo", "title": "x"}).status_code
        == 404
    )


def test_save_a_single_question(benv, survey):
    c = benv.login("editor@a.example")
    saved = _save(c, survey, "age", title="Age in years")
    assert saved["diagnostics"] == []
    s = saved["item"]["summary"]
    assert s["kind"] == "question" and s["itemCount"] == 1 and s["languages"] == []
    assert saved["item"]["document"]["fragment"]["question"]["id"] == "age"
    assert _ids(c.get("/api/bank", params={"kind": "question"}).json()["items"]) == [s["id"]]


# --- versions and metadata ----------------------------------------------------------------


def test_versions_are_immutable_and_metadata_edits_touch_the_current_one(benv, survey):
    c = benv.login("editor@a.example")
    item_id = _save(c, survey, description="v1 text")["item"]["summary"]["id"]
    ops = [
        {
            "op": "set_property",
            "params": {"target": "demo", "property": "title", "value": "Demo v2"},
        }
    ]
    assert (
        c.post(f"/api/surveys/{survey}/ops", json={"ops": ops, "baseRevision": 0}).status_code
        == 200
    )
    r = c.post(
        f"/api/bank/{item_id}/versions",
        json={"surveyId": survey, "targetId": "demo", "title": "Demo scale v2"},
    )
    assert r.status_code == 201, r.text
    v2 = r.json()["item"]
    assert v2["version"] == 2 and v2["summary"]["version"] == 2
    assert v2["document"]["title"] == "Demo scale v2"
    assert v2["document"]["description"] == "v1 text"  # metadata not given is kept
    assert v2["document"]["fragment"]["block"]["title"] == "Demo v2"
    assert c.get(f"/api/bank/{item_id}").json()["version"] == 2
    v1 = c.get(f"/api/bank/{item_id}", params={"version": 1}).json()
    assert v1["document"]["title"] == "Demo scale"
    assert v1["document"]["fragment"]["block"]["title"] == "Demo scale"
    versions = c.get(f"/api/bank/{item_id}/versions").json()
    assert [(v["version"], v["title"]) for v in versions] == [
        (1, "Demo scale"),
        (2, "Demo scale v2"),
    ]
    assert versions[0]["checksum"] != versions[1]["checksum"]
    # A different kind can't become a new version of this item.
    r = c.post(f"/api/bank/{item_id}/versions", json={"surveyId": survey, "targetId": "age"})
    assert r.status_code == 422 and r.json()["diagnostics"][0]["code"] == "bank.kind_mismatch"

    r = c.patch(
        f"/api/bank/{item_id}",
        json={"title": "Demo (renamed)", "tags": ["renamed"], "abbreviation": None},
    )
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 2 and r.json()["document"]["title"] == "Demo (renamed)"
    assert (
        r.json()["document"]["tags"] == ["renamed"] and "abbreviation" not in r.json()["document"]
    )
    assert r.json()["document"]["description"] == "v1 text"  # not sent: kept
    assert r.json()["document"]["fragment"] == v2["document"]["fragment"]
    assert (
        c.get(f"/api/bank/{item_id}", params={"version": 1}).json()["document"]["title"]
        == "Demo scale"
    )
    assert _ids(c.get("/api/bank", params={"q": "renamed"}).json()["items"]) == [item_id]
    assert c.patch(f"/api/bank/{item_id}", json={"title": ""}).status_code == 422
    assert c.patch(f"/api/bank/{item_id}", json={"fragment": {}}).status_code == 422
    assert c.patch(f"/api/bank/{item_id}", json={"tags": ["x" * 41]}).status_code == 422
    assert c.patch(f"/api/bank/{item_id}", json={}).status_code == 200  # nothing to change
    assert c.patch("/api/bank/gad2", json={"title": "x"}).status_code == 404  # bundled: read-only
    v = benv.login("viewer@a.example")
    assert v.patch(f"/api/bank/{item_id}", json={"title": "x"}).status_code == 403
    assert v.get(f"/api/bank/{item_id}/versions").status_code == 200


# --- sharing ----------------------------------------------------------------------------


def test_share_with_the_host(benv, survey):
    editor, owner = benv.login("editor@a.example"), benv.login("owner@a.example")
    item_id = _save(editor, survey)["item"]["summary"]["id"]
    assert editor.post(f"/api/bank/{item_id}/share", json={"visibility": "host"}).status_code == 403
    r = owner.post(f"/api/bank/{item_id}/share", json={"visibility": "host"})
    assert r.status_code == 422 and r.json()["diagnostics"][0]["code"] == "bank.not_shareable"
    r = owner.post(
        f"/api/bank/{item_id}/share", json={"visibility": "host", "licenceClass": "licensed-to-lab"}
    )
    assert r.status_code == 422 and r.json()["diagnostics"][0]["code"] == "bank.not_shareable"
    assert (
        owner.post(
            f"/api/bank/{item_id}/share", json={"visibility": "host", "licenceClass": "gpl"}
        ).status_code
        == 422
    )
    assert (
        owner.post(f"/api/bank/{item_id}/share", json={"visibility": "public"}).status_code == 422
    )
    assert owner.get(f"/api/bank/{item_id}").json()["summary"]["visibility"] == "lab"
    # "These are our own words, CC BY 4.0", in one click.
    r = owner.post(
        f"/api/bank/{item_id}/share", json={"visibility": "host", "licenceClass": "cc-by-4.0"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["visibility"] == "host"
    assert r.json()["summary"]["licenceClass"] == "cc-by-4.0"
    assert r.json()["document"]["licence"] == {"class": "cc-by-4.0"}
    assert owner.get("/api/bank").json()["canShare"] is True

    b = benv.login("owner@b.example")
    seen = b.get("/api/bank", params={"source": "host"}).json()["items"]
    assert _ids(seen) == [item_id]
    assert seen[0]["source"] == "host" and seen[0]["canEdit"] is False
    assert seen[0]["labId"] == benv.tenants["A"]
    assert b.get(f"/api/bank/{item_id}").json()["document"]["title"] == "Demo scale"
    assert b.get(f"/api/bank/{item_id}/versions").status_code == 200
    assert b.get(f"/api/bank/{item_id}/export").status_code == 200
    # Read-only for the other lab: every write is "not found".
    assert b.patch(f"/api/bank/{item_id}", json={"title": "Mine"}).status_code == 404
    assert b.delete(f"/api/bank/{item_id}").status_code == 404
    assert b.post(f"/api/bank/{item_id}/share", json={"visibility": "lab"}).status_code == 404
    assert (
        b.post(
            f"/api/bank/{item_id}/versions", json={"surveyId": survey, "targetId": "demo"}
        ).status_code
        == 404
    )
    # A copy is the other lab's own, with provenance.
    r = b.post(f"/api/bank/{item_id}/copy", json={})
    assert r.status_code == 201, r.text
    cp = r.json()
    assert cp["summary"]["source"] == "lab" and cp["summary"]["labId"] == benv.tenants["B"]
    assert cp["summary"]["id"] != item_id and cp["version"] == 1
    assert cp["document"]["provenance"] == {
        "from": {"library": "host", "id": item_id, "version": 1}
    }
    assert (
        cp["document"]["fragment"] == b.get(f"/api/bank/{item_id}").json()["document"]["fragment"]
    )
    assert cp["summary"]["licenceClass"] == "cc-by-4.0"
    # Taking it back hides it again (the copy stays B's).
    assert owner.post(f"/api/bank/{item_id}/share", json={"visibility": "lab"}).status_code == 200
    assert _ids(b.get("/api/bank", params={"source": "host"}).json()["items"]) == []
    assert b.get(f"/api/bank/{item_id}").status_code == 404
    assert b.post(f"/api/bank/{item_id}/copy", json={}).status_code == 404
    assert _ids(b.get("/api/bank", params={"source": "lab"}).json()["items"]) == [
        cp["summary"]["id"]
    ]
    # The audit trail names the item, the visibility and the licence, never the text.
    audit = benv.store.list_audit(TenantContext(benv.tenants["A"], "owner@a.example"))
    shares = [e for e in audit if e.action == "bank.share"]
    assert [e.detail for e in shares] == [
        {"visibility": "host", "licence_class": "cc-by-4.0"},
        {"visibility": "lab", "licence_class": "cc-by-4.0"},
    ]
    relicensed = [e for e in audit if e.action == "bank.update"]
    assert relicensed[0].detail == {"fields": ["licence"], "licence_class": "cc-by-4.0"}
    assert all("Demo" not in str(e.detail) for e in audit)


def test_host_sharing_switched_off(benv, survey):
    owner = benv.login("owner@a.example")
    item_id = _save(owner, survey, licence={"class": "cc0"})["item"]["summary"]["id"]
    assert owner.post(f"/api/bank/{item_id}/share", json={"visibility": "host"}).status_code == 200
    b = benv.login("owner@b.example")
    assert _ids(b.get("/api/bank", params={"source": "host"}).json()["items"]) == [item_id]

    benv.services.builder.bank_host_sharing = False  # OSP_BANK_HOST_SHARING=off
    assert b.get("/api/bank").json()["hostSharing"] is False
    assert _ids(b.get("/api/bank", params={"source": "host"}).json()["items"]) == []
    assert item_id not in _ids(b.get("/api/bank").json()["items"])
    assert b.get(f"/api/bank/{item_id}").status_code == 404
    assert b.post(f"/api/bank/{item_id}/copy", json={}).status_code == 404
    # The owning lab still has it, and can't share anything new.
    assert owner.get(f"/api/bank/{item_id}").json()["summary"]["visibility"] == "host"
    other = _save(owner, survey, licence={"class": "cc0"})["item"]["summary"]["id"]
    r = owner.post(f"/api/bank/{other}/share", json={"visibility": "host"})
    assert r.status_code == 422 and "switched off" in r.json()["message"]
    assert owner.post(f"/api/bank/{item_id}/share", json={"visibility": "lab"}).status_code == 200


# --- delete -----------------------------------------------------------------------------


def test_soft_delete(benv, survey):
    editor, owner = benv.login("editor@a.example"), benv.login("owner@a.example")
    item_id = _save(editor, survey, licence={"class": "cc0"})["item"]["summary"]["id"]
    owner.post(f"/api/bank/{item_id}/share", json={"visibility": "host"})
    b = benv.login("owner@b.example")
    assert b.get(f"/api/bank/{item_id}").status_code == 200
    assert benv.login("viewer@a.example").delete(f"/api/bank/{item_id}").status_code == 403
    assert editor.delete(f"/api/bank/{item_id}").status_code == 204
    assert editor.delete(f"/api/bank/{item_id}").status_code == 409
    assert _ids(editor.get("/api/bank", params={"source": "lab"}).json()["items"]) == []
    gone = editor.get(f"/api/bank/{item_id}")  # the owning lab still reads it (provenance)
    assert gone.status_code == 200 and gone.json()["summary"]["deletedAt"] is not None
    assert gone.json()["summary"]["canEdit"] is False
    assert b.get(f"/api/bank/{item_id}").status_code == 404  # other labs don't
    assert _ids(b.get("/api/bank").json()["items"]) == _ids(
        b.get("/api/bank", params={"source": "bundled"}).json()["items"]
    )
    assert editor.patch(f"/api/bank/{item_id}", json={"title": "x"}).status_code == 409
    assert owner.post(f"/api/bank/{item_id}/share", json={"visibility": "lab"}).status_code == 409
    r = editor.post(f"/api/bank/{item_id}/versions", json={"surveyId": survey, "targetId": "demo"})
    assert r.status_code == 409
    assert editor.get(f"/api/bank/{item_id}/export").status_code == 200  # the backup still works
    assert editor.delete("/api/bank/gad2").status_code == 404  # bundled: not a lab item
    audit = benv.store.list_audit(TenantContext(benv.tenants["A"], "editor@a.example"))
    assert [e.action for e in audit if e.target_id == item_id] == [
        "bank.save",
        "bank.share",
        "bank.delete",
    ]


# --- export and import --------------------------------------------------------------------


def test_export_and_import(benv, survey):
    a = benv.login("editor@a.example")
    item_id = _save(a, survey, tags=["demo"], citation={"text": "Invented (2026)."})["item"][
        "summary"
    ]["id"]
    r = a.get(f"/api/bank/{item_id}/export")
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"] == f'attachment; filename="{item_id}.osp-bank.json"'
    file = r.json()
    assert file["bankFile"] == "osp-bank-file/0.1" and file["private"] is False
    assert file["exportedAt"].startswith("2026-")
    [exported] = file["items"]
    assert exported == a.get(f"/api/bank/{item_id}").json()["document"]
    assert a.get(f"/api/bank/{item_id}/export", params={"version": 2}).status_code == 404
    assert a.get("/api/bank/gad2/export").json()["items"][0]["id"] == "gad2"
    assert benv.login("viewer@a.example").get(f"/api/bank/{item_id}/export").status_code == 403

    b = benv.login("owner@b.example")
    r = b.post("/api/bank/import", json={"file": file})
    assert r.status_code == 201, r.text
    [imported] = r.json()["items"]
    assert r.json()["diagnostics"] == []
    assert imported["source"] == "lab" and imported["labId"] == benv.tenants["B"]
    assert imported["id"] != item_id and imported["version"] == 1
    assert imported["title"] == "Demo scale" and imported["tags"] == ["demo"]
    assert imported["licenceClass"] == "unknown"  # kept, never upgraded
    doc = b.get(f"/api/bank/{imported['id']}").json()["document"]
    assert doc["provenance"] == {"from": {"library": "file", "id": item_id, "version": 1}}
    assert doc["citation"] == {"text": "Invented (2026)."}
    assert doc["fragment"] == exported["fragment"]
    audit = benv.store.list_audit(TenantContext(benv.tenants["B"], "owner@b.example"))
    assert [e.action for e in audit if e.target_id == imported["id"]] == ["bank.import"]

    # A bad file, a bad item (all or nothing), too many items.
    r = b.post("/api/bank/import", json={"file": {"items": [exported]}})
    assert r.status_code == 422 and r.json()["diagnostics"][0]["code"] == "bank.file"
    r = b.post("/api/bank/import", json={"file": {**file, "items": []}})
    assert r.status_code == 422
    broken = copy.deepcopy(exported)
    broken["fragment"]["block"]["pages"][0]["items"][0]["type"] = "nope"
    r = b.post("/api/bank/import", json={"file": {**file, "items": [exported, broken]}})
    assert r.status_code == 422
    assert r.json()["diagnostics"][0]["pointer"].startswith("/items/1/fragment/")
    r = b.post("/api/bank/import", json={"file": {**file, "items": [{"x": 1}]}})
    assert r.status_code == 422 and r.json()["diagnostics"][0]["pointer"].startswith("/items/0")
    r = b.post("/api/bank/import", json={"file": {**file, "items": [exported] * 201}})
    assert r.status_code == 422 and r.json()["diagnostics"][0]["code"] == "bank.too_large"
    assert (
        len(b.get("/api/bank", params={"source": "lab"}).json()["items"]) == 1
    )  # nothing else landed
    assert (
        benv.login("viewer@a.example").post("/api/bank/import", json={"file": file}).status_code
        == 403
    )


def test_licensed_to_lab_items_stay_private(benv, survey):
    editor, owner = benv.login("editor@a.example"), benv.login("owner@a.example")
    licence = {"class": "licensed-to-lab", "holder": "Rights Holder Ltd"}
    body = {"surveyId": survey, "targetId": "demo", "title": "Licensed scale", "licence": licence}
    assert editor.post("/api/bank", json=body).status_code == 403  # owner only (§1.7)
    r = owner.post("/api/bank", json=body)
    assert r.status_code == 201, r.text
    item_id = r.json()["item"]["summary"]["id"]
    assert editor.get(f"/api/bank/{item_id}").status_code == 200  # the lab reads it
    r = owner.post(f"/api/bank/{item_id}/share", json={"visibility": "host"})
    assert r.status_code == 422 and r.json()["diagnostics"][0]["code"] == "bank.not_shareable"
    assert editor.get(f"/api/bank/{item_id}/export").status_code == 403  # the owner's backup only
    r = owner.get(f"/api/bank/{item_id}/export")
    assert r.status_code == 200 and r.json()["private"] is True
    file = r.json()
    # A new version from an editor can't relicense it out of the private class either way.
    r = editor.post(
        f"/api/bank/{item_id}/versions",
        json={"surveyId": survey, "targetId": "demo", "licence": {"class": "cc0"}},
    )
    assert r.status_code == 201  # relicensing to an open class is an ordinary edit
    assert editor.get(f"/api/bank/{item_id}").json()["summary"]["licenceClass"] == "cc0"
    r = editor.post(
        f"/api/bank/{item_id}/versions",
        json={"surveyId": survey, "targetId": "demo", "licence": licence},
    )
    assert r.status_code == 403  # but back to licensed-to-lab needs an owner

    b_owner = benv.login("owner@b.example")
    r = b_owner.post("/api/bank/import", json={"file": file})
    assert (
        r.status_code == 422 and r.json()["diagnostics"][0]["code"] == "bank.licensed_attestation"
    )
    assert r.json()["diagnostics"][0]["pointer"] == "/items/0/licence"
    r = b_owner.post("/api/bank/import", json={"file": file, "attestLicensed": True})
    assert r.status_code == 201, r.text
    assert r.json()["items"][0]["licenceClass"] == "licensed-to-lab"
    # An editor's attestation doesn't count.
    benv.roles["editor@b.example"] = {benv.tenants["B"]: "editor"}
    b_editor = benv.login("editor@b.example")
    r = b_editor.post("/api/bank/import", json={"file": file, "attestLicensed": True})
    assert (
        r.status_code == 422 and r.json()["diagnostics"][0]["code"] == "bank.licensed_attestation"
    )


# --- the bundled library ------------------------------------------------------------------


def test_bundled_library(benv):
    c = benv.login("viewer@a.example")
    lib = c.get("/api/bank/library")
    assert lib.status_code == 200, lib.text
    assert _ids(lib.json()) == library_ids()
    gad2 = next(i for i in lib.json() if i["id"] == "gad2")
    assert gad2["source"] == "bundled" and gad2["licenceClass"] == "public-domain"
    assert gad2["visibility"] is None and gad2["labId"] is None and gad2["canEdit"] is False
    assert gad2["itemCount"] == 2 and gad2["kind"] == "block" and gad2["createdAt"] is None
    got = c.get("/api/bank/gad2")
    assert got.status_code == 200
    assert got.json()["document"] == load_document("gad2") and got.json()["checksum"] is None
    assert got.json()["summary"] == gad2
    assert c.get("/api/bank/gad2", params={"version": 1}).status_code == 200
    assert c.get("/api/bank/gad2", params={"version": 2}).status_code == 404
    assert c.get("/api/bank/no-such-instrument").status_code == 404
    assert c.get("/api/bank/" + "x" * 65).status_code == 404
    versions = c.get("/api/bank/gad2/versions").json()
    assert [v["version"] for v in versions] == [1] and versions[0]["createdBy"] == "bundled"
    assert c.post("/api/bank/gad2/copy", json={}).status_code == 403  # a viewer

    e = benv.login("editor@a.example")
    r = e.post("/api/bank/gad2/copy", json={})
    assert r.status_code == 201, r.text
    cp = r.json()
    assert cp["summary"]["source"] == "lab" and cp["summary"]["title"] == gad2["title"]
    assert cp["document"]["provenance"] == {
        "from": {"library": "bundled", "id": "gad2", "version": 1}
    }
    assert cp["document"]["licence"] == load_document("gad2")["licence"]
    assert cp["document"]["fragment"] == load_document("gad2")["fragment"]
    assert cp["summary"]["id"] != "gad2" and cp["version"] == 1
    assert e.post("/api/bank/gad2/copy", json={"version": 2}).status_code == 404
    assert (
        e.patch(f"/api/bank/{cp['summary']['id']}", json={"title": "Our GAD-2"}).status_code == 200
    )


# --- tenants, identity, origin -----------------------------------------------------------


def test_naming_another_lab_is_not_permitted(benv, survey):
    a = benv.login("owner@a.example")
    item_id = _save(a, survey)["item"]["summary"]["id"]
    b = benv.login("owner@b.example")
    for call in (
        lambda: b.get("/api/bank", params={"tenantId": benv.tenants["A"]}),
        lambda: b.get("/api/bank", params={"tenantId": "no-such-lab"}),
        lambda: b.get(f"/api/bank/{item_id}", params={"tenantId": benv.tenants["A"]}),
        lambda: b.patch(f"/api/bank/{item_id}", json={"title": "x", "tenantId": benv.tenants["A"]}),
        lambda: b.delete(f"/api/bank/{item_id}", params={"tenantId": benv.tenants["A"]}),
        lambda: b.post(
            f"/api/bank/{item_id}/share", json={"visibility": "lab", "tenantId": benv.tenants["A"]}
        ),
        lambda: b.post("/api/bank/import", json={"file": {}, "tenantId": benv.tenants["A"]}),
    ):
        assert call().status_code == 403
    # A member of two labs must say which.
    benv.roles["both@example"] = {benv.tenants["A"]: "editor", benv.tenants["B"]: "editor"}
    both = benv.login("both@example")
    assert both.get("/api/bank").status_code == 422
    assert both.get("/api/bank", params={"tenantId": benv.tenants["A"]}).status_code == 200
    assert both.get("/api/bank/library").status_code == 200  # the same for every lab


@pytest.mark.parametrize("method", ["get", "post", "patch", "delete"])
def test_bank_needs_identity_and_same_origin(benv, method):
    anon = benv.client()
    path = "/api/bank" if method in ("get", "post") else "/api/bank/x"
    assert getattr(anon, method)(path).status_code == 401
    assert anon.get("/api/bank/library").status_code == 401
    if method != "get":
        c = benv.login("owner@a.example")
        c.headers["Origin"] = "https://evil.example"
        kwargs = {"json": {"title": "x"}} if method in ("post", "patch") else {}
        assert getattr(c, method)(path, **kwargs).status_code == 403


def test_serve_reads_the_host_sharing_switch():
    from osp_api.serve import ConfigError, Settings

    assert Settings.from_env({}).bank_host_sharing is True
    assert Settings.from_env({"OSP_BANK_HOST_SHARING": "off"}).bank_host_sharing is False
    assert Settings.from_env({"OSP_BANK_HOST_SHARING": "ON"}).bank_host_sharing is True
    with pytest.raises(ConfigError, match="OSP_BANK_HOST_SHARING"):
        Settings.from_env({"OSP_BANK_HOST_SHARING": "maybe"})
