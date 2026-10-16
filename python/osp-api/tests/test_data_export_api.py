"""Response data export endpoints (task M2): CSV / JSON responses and the codebook."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path

from osp_store import ParticipantStore, TenantContext

REPO = Path(__file__).resolve().parents[3]
SURVEY = json.loads((REPO / "fixtures/01-all-types/survey.json").read_text(encoding="utf-8"))
RECORDS = REPO / "python/osp-targets/tests/data/records/01-all-types"


def _published(benv) -> tuple[str, TenantContext, str]:
    c = benv.login("editor@a.example")
    r = c.post("/api/surveys", json={"title": "All types", "survey": SURVEY})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    pub = c.post(f"/api/surveys/{sid}/publish", json={})
    assert pub.status_code == 201, pub.text
    return sid, TenantContext(benv.tenants["A"], "system:test"), pub.json()["versionId"]


def _submit(benv, ctx: TenantContext, version_id: str) -> str:
    """One response through the participant store (with its full engine record)."""
    rec = json.loads((RECORDS / "answered.json").read_text(encoding="utf-8"))
    ps = ParticipantStore(benv.store)
    pub = ps.create_publication(
        ctx, version_id, "all-types", {}, rec["planChecksum"], "end-only", {}
    )
    sess = ps.start(ctx, pub.id, rec["sessionSeed"], {}, "f" * 64)
    rec["sessionId"] = sess.id
    res = ps.submit(
        ctx,
        sess.id,
        answers=rec["answers"],
        record={"record": rec, "server": {"saveMode": "end-only"}},
        record_checksum="a" * 64,
        realised_orders=rec["orders"],
        engine_version=rec["engineVersion"],
    )
    assert res.status == "ok"
    return res.response_id


def _rows(content: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline="")))


def test_export_csv_json_and_codebook(benv):
    sid, ctx, vid = _published(benv)
    rid = _submit(benv, ctx, vid)
    # a second response stored without a runtime record: exported from the row alone
    empty = json.loads((RECORDS / "empty.json").read_text(encoding="utf-8"))
    benv.store.record_response(ctx, vid, empty["answers"], session_seed=7)
    c = benv.login("editor@a.example")

    r = c.get(f"/api/surveys/{sid}/export/responses")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "no-store"
    rows = {row["_response_id"]: row for row in _rows(r.content)}
    assert len(rows) == 2
    full = rows[rid]
    assert full["_save_mode"] == "end-only" and full["_version"] == "1"
    assert full["m_multi_red"] == "1" and full["m_multi__state"] == "answered"
    assert full["_late"] == "false" and full["_submitted_at"].endswith("Z")
    other = next(row for k, row in rows.items() if k != rid)
    assert other["n_int"] == "" and other["n_int__state"] == "unanswered"
    # no cell is a -99 style missing code (substring checks are flaky: ids can contain "-99")
    assert all(v != "-99" for row in rows.values() for v in row.values())

    excel = c.get(f"/api/surveys/{sid}/export/responses?version=1&excel=true&multi=codes")
    assert excel.content.startswith(b"\xef\xbb\xbf")
    assert _rows(excel.content)[0].get("m_multi") is not None

    no_state = c.get(f"/api/surveys/{sid}/export/responses?stateColumns=false")
    assert "__state" not in no_state.text

    j = c.get(f"/api/surveys/{sid}/export/responses?format=json&events=true")
    assert j.status_code == 200 and j.headers["content-type"] == "application/json"
    doc = j.json()
    by = {x["responseId"]: x for x in doc["responses"]}
    assert by[rid]["answers"]["d_date"] == {"state": "answered", "value": "2026-03-14"}
    assert by[rid]["events"][0]["type"] == "start"

    md = c.get(f"/api/surveys/{sid}/export/codebook")
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert md.text.startswith("# Codebook: All question types")
    assert "Mode: **end-only**" in md.text
    cj = c.get(f"/api/surveys/{sid}/export/codebook?format=json&version=1").json()
    assert cj["saveMode"]["mode"] == "end-only"
    assert [v["name"] for v in cj["variables"]][:2] == ["n_int", "n_dec"]

    # closing the survey before a submission marks it late (provisional, M2-1)
    benv.store.close_survey(ctx, sid, datetime(2000, 1, 1, tzinfo=UTC))
    late = _rows(c.get(f"/api/surveys/{sid}/export/responses").content)
    assert {row["_late"] for row in late} == {"true"}


def test_export_errors(benv):
    c = benv.login("editor@a.example")
    sid = c.post("/api/surveys", json={"title": "Draft only"}).json()["id"]
    assert c.get(f"/api/surveys/{sid}/export/responses").status_code == 404  # unpublished
    assert c.get(f"/api/surveys/{sid}/export/codebook").status_code == 404
    sid2, _, _ = _published(benv)
    assert c.get(f"/api/surveys/{sid2}/export/responses?version=9").status_code == 404
    assert c.get(f"/api/surveys/{sid2}/export/responses?format=xml").status_code == 422
    assert c.get(f"/api/surveys/{sid2}/export/codebook?version=0").status_code == 422
    viewer = benv.login("viewer@a.example")
    assert viewer.get(f"/api/surveys/{sid2}/export/responses").status_code == 403
    assert viewer.get(f"/api/surveys/{sid2}/export/codebook").status_code == 403
