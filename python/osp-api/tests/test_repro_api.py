"""Reproducibility package endpoint (task M3): permissions, contents, determinism."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from osp_store import ParticipantStore, SystemContext, TenantContext

REPO = Path(__file__).resolve().parents[3]
FIXTURE = "13-randomiser-blocks"
SURVEY = json.loads((REPO / f"fixtures/{FIXTURE}/survey.json").read_text(encoding="utf-8"))
SURVEY["settings"] = {**SURVEY.get("settings", {}), "retention": {"kind": "indefinite"}}
RECORD = REPO / f"python/osp-targets/tests/data/records/{FIXTURE}/main.json"


def _published(benv) -> tuple[str, dict]:
    c = benv.login("editor@a.example")
    r = c.post("/api/surveys", json={"title": "Blocks", "survey": SURVEY})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    pub = c.post(f"/api/surveys/{sid}/publish", json={})
    assert pub.status_code == 201, pub.text
    return sid, pub.json()


def _submit(benv, pub: dict) -> str:
    """One engine-generated response, through the real publication (the plan now carries
    the theme, so its checksum differs from the fixture's: the record names the served
    plan, as a real browser's would; orders and seeds are unchanged)."""
    rec = json.loads(RECORD.read_text(encoding="utf-8"))
    rec["planChecksum"] = pub["planChecksum"]
    ctx = TenantContext(benv.tenants["A"], "system:test")
    ps = ParticipantStore(benv.store)
    publication = ps.find_publication(SystemContext("system:test"), pub["slug"])
    sess = ps.start(ctx, publication.id, rec["sessionSeed"], {}, "e" * 64)
    rec["sessionId"] = sess.id
    rec["events"][0]["sessionId"] = sess.id
    res = ps.submit(
        ctx,
        sess.id,
        answers=rec["answers"],
        record={"record": rec, "server": {"saveMode": "every-page"}},
        record_checksum="b" * 64,
        realised_orders=rec["orders"],
        engine_version=rec["engineVersion"],
    )
    assert res.status == "ok"
    return res.response_id


def _files(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        return {n.split("/", 1)[1]: z.read(n) for n in z.namelist()}


def test_default_package_has_no_data_and_is_deterministic(benv):
    sid, pub = _published(benv)
    _submit(benv, pub)
    c = benv.login("editor@a.example")
    r = c.get(f"/api/surveys/{sid}/versions/1/repro-package")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert f'filename="survey-{sid[:8]}-v1-repro.zip"' in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "no-store"
    files = _files(r.content)
    assert not [f for f in files if f.startswith("data/")]
    assert {"survey/survey.json", "survey/plan.json", "exports/survey.lss", "README.md"} <= set(
        files
    )
    manifest = json.loads(files["manifest.json"])
    assert manifest["includesData"] is False
    assert manifest["plan"]["checksum"] == pub["planChecksum"]
    assert manifest["plan"]["source"] == "published"  # the stored plan, theme included
    assert manifest["survey"]["checksum"] == pub["checksum"] and manifest["survey"]["checksumOk"]
    assert json.loads(files["survey/plan.json"])["theme"]
    assert c.get(f"/api/surveys/{sid}/versions/1/repro-package").content == r.content


def test_data_package_replays(benv, tmp_path):
    sid, pub = _published(benv)
    rid = _submit(benv, pub)
    c = benv.login("editor@a.example")
    r = c.get(f"/api/surveys/{sid}/versions/1/repro-package?data=true")
    assert r.status_code == 200, r.text
    files = _files(r.content)
    for f in ("data/codebook.md", "data/codebook.json", "data/responses.csv"):
        assert f in files
    doc = json.loads(files["data/responses.json"])
    (resp,) = doc["responses"]
    assert resp["responseId"] == rid and resp["events"][0]["type"] == "start"
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        z.extractall(tmp_path / "pkg")
    root = next((tmp_path / "pkg").iterdir())
    proc = subprocess.run(
        [sys.executable, "-I", "replay/replay.py", "--json"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["summary"] == {"match": 1, "mismatch": 0, "skipped": 0}


def test_permissions(benv):
    sid, pub = _published(benv)
    _submit(benv, pub)
    url = f"/api/surveys/{sid}/versions/1/repro-package"
    viewer = benv.login("viewer@a.example")
    v = viewer.get(url)
    assert v.status_code == 200  # survey.read: the package without data
    assert not [f for f in _files(v.content) if f.startswith("data/")]
    assert viewer.get(url + "?data=true").status_code == 403  # no survey.export
    owner = benv.login("owner@a.example")
    assert owner.get(url + "?data=true").status_code == 200
    other_lab = benv.login("owner@b.example")
    assert other_lab.get(url).status_code == 404
    assert other_lab.get(url + "?data=true").status_code == 404
    assert benv.client().get(url).status_code == 401


def test_errors(benv):
    c = benv.login("editor@a.example")
    draft = c.post("/api/surveys", json={"title": "Draft only"}).json()["id"]
    assert c.get(f"/api/surveys/{draft}/versions/1/repro-package").status_code == 404
    sid, _ = _published(benv)
    assert c.get(f"/api/surveys/{sid}/versions/9/repro-package").status_code == 404
    assert c.get(f"/api/surveys/{sid}/versions/0/repro-package").status_code == 422
    assert c.get(f"/api/surveys/{sid}/versions/x/repro-package").status_code == 422
    assert c.get(f"/api/surveys/{sid}/versions/1/repro-package?data=maybe").status_code == 422
