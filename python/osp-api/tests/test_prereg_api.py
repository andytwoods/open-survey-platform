"""Preregistration export endpoints (task OS1): bundle, summary, OSF upload with a fake
transport (no network), token hygiene, permissions."""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from osp_app.errors import InvalidRequest, UpstreamError
from osp_app.osf import OsfClient, check_token, node_id_of
from osp_store import TenantContext

REPO = Path(__file__).resolve().parents[3]
FIXTURE = "20-worked-example"
SURVEY = json.loads((REPO / f"fixtures/{FIXTURE}/survey.json").read_text(encoding="utf-8"))
SURVEY["settings"] = {**SURVEY.get("settings", {}), "retention": {"kind": "indefinite"}}
TOKEN = "osf-test-token-0123456789abcdefABCDEF"  # never a real token
NODE = "ab3de"


def _published(benv) -> tuple[str, dict]:
    c = benv.login("editor@a.example")
    r = c.post("/api/surveys", json={"title": "Framing", "survey": SURVEY})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    pub = c.post(f"/api/surveys/{sid}/publish", json={})
    assert pub.status_code == 201, pub.text
    return sid, pub.json()


def _files(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        return {n.split("/", 1)[1]: z.read(n) for n in z.namelist()}


# -- bundle and summary ----------------------------------------------------------------------


def test_bundle_download(benv):
    sid, pub = _published(benv)
    c = benv.login("editor@a.example")
    r = c.get(f"/api/surveys/{sid}/versions/1/prereg-bundle")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert f'filename="survey-{sid[:8]}-v1-prereg.zip"' in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "no-store"
    files = _files(r.content)
    assert not [f for f in files if f.startswith("data/")]
    manifest = json.loads(files["manifest.json"])
    assert manifest["survey"]["checksum"] == pub["checksum"] and manifest["survey"]["checksumOk"]
    assert manifest["plan"]["checksum"] == pub["planChecksum"]
    assert manifest["includesReproPackage"] is True
    assert manifest["design"]["retention"] == {"kind": "indefinite"}
    nested = _files(files["reproducibility-package.zip"])
    inner = json.loads(nested["manifest.json"])
    assert inner["plan"]["checksum"] == pub["planChecksum"] and inner["includesData"] is False
    assert not [f for f in nested if f.startswith("data/")]
    assert c.get(f"/api/surveys/{sid}/versions/1/prereg-bundle").content == r.content
    lean = c.get(f"/api/surveys/{sid}/versions/1/prereg-bundle?repro=false")
    assert lean.status_code == 200 and "reproducibility-package.zip" not in _files(lean.content)


def test_summary_page(benv):
    sid, pub = _published(benv)
    c = benv.login("viewer@a.example")
    r = c.get(f"/api/surveys/{sid}/versions/1/prereg-summary")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["content-security-policy"].startswith("default-src 'none'")
    assert r.headers["content-disposition"].startswith("inline;")
    html = r.text
    assert "<h1>Preregistration summary: Framing and incentive study</h1>" in html
    assert pub["checksum"] in html and pub["planChecksum"] in html
    assert "<code>framing</code>" in html and "<code>q_old</code>" in html


def test_permissions_and_errors(benv):
    sid, _ = _published(benv)
    url = f"/api/surveys/{sid}/versions/1/prereg-bundle"
    assert benv.login("viewer@a.example").get(url).status_code == 200  # survey.read is enough
    assert benv.login("owner@b.example").get(url).status_code == 404
    assert benv.login("owner@b.example").get(url.replace("bundle", "summary")).status_code == 404
    assert benv.client().get(url).status_code == 401
    c = benv.login("editor@a.example")
    assert c.get(f"/api/surveys/{sid}/versions/9/prereg-bundle").status_code == 404
    assert c.get(f"/api/surveys/{sid}/versions/0/prereg-bundle").status_code == 422
    draft = c.post("/api/surveys", json={"title": "Draft only"}).json()["id"]
    assert c.get(f"/api/surveys/{draft}/versions/1/prereg-summary").status_code == 404


# -- OSF upload ----------------------------------------------------------------------------------


@dataclass
class FakeOsf:
    """Answers like OSF's API v2 and file service; records every request."""

    calls: list[tuple[str, str, dict[str, str], bytes | None]] = field(default_factory=list)
    me_status: int = 200
    node_status: int = 200
    upload_status: int = 201
    raise_network: bool = False

    def __call__(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float
    ):
        self.calls.append((method, url, dict(headers), body))
        if self.raise_network:
            raise UpstreamError("OSF could not be reached (timed out).")
        if url.endswith("/users/me/"):
            return self.me_status, json.dumps(
                {"data": {"id": "u1", "attributes": {"full_name": "Ada Example"}}}
            ).encode()
        if "/nodes/" in url:
            return self.node_status, json.dumps(
                {
                    "data": {
                        "id": NODE,
                        "attributes": {"title": "Framing study", "public": False},
                        "links": {"html": f"https://osf.io/{NODE}/"},
                    }
                }
            ).encode()
        if method == "PUT":
            name = url.split("name=")[1].split("&")[0].replace("%20", " ")
            return self.upload_status, json.dumps(
                {
                    "data": {
                        "id": f"osfstorage/{len(self.calls)}",
                        "attributes": {"name": name, "size": len(body or b"")},
                        "links": {
                            "html": f"https://osf.io/{NODE}/files/osfstorage/{len(self.calls)}"
                        },
                    }
                }
            ).encode()
        raise AssertionError(f"unexpected call {method} {url}")


def _post(benv, user: str, sid: str, version: int = 1, **body: Any):
    c = benv.login(user)
    return c.post(
        f"/api/surveys/{sid}/versions/{version}/prereg-bundle/osf",
        json={"token": TOKEN, "node": NODE, **body},
    )


def test_osf_upload_sends_the_bundle_with_the_token_and_never_stores_it(benv):
    sid, pub = _published(benv)
    fake = FakeOsf()
    benv.services.osf_transport = fake
    r = _post(benv, "editor@a.example", sid)
    assert r.status_code == 200, r.text
    out = r.json()
    assert (
        out["nodeId"] == NODE and out["nodeTitle"] == "Framing study" and out["nodePublic"] is False
    )
    assert out["nodeUrl"] == f"https://osf.io/{NODE}/" and out["user"] == "Ada Example"
    assert out["checksum"] == pub["checksum"]
    assert [f["name"] for f in out["files"]] == [
        f"survey-{sid[:8]}-v1-prereg.zip",
        f"survey-{sid[:8]}-v1-prereg-summary.html",
    ]
    assert all(f["url"].startswith("https://osf.io/") and f["size"] > 0 for f in out["files"])
    assert TOKEN not in r.text

    methods = [(m, u.split("?")[0]) for m, u, _, _ in fake.calls]
    assert methods == [
        ("GET", "https://api.osf.io/v2/users/me/"),
        ("GET", f"https://api.osf.io/v2/nodes/{NODE}/"),
        ("PUT", f"https://files.osf.io/v1/resources/{NODE}/providers/osfstorage/"),
        ("PUT", f"https://files.osf.io/v1/resources/{NODE}/providers/osfstorage/"),
    ]
    for _, url, headers, _ in fake.calls:
        assert headers["Authorization"] == f"Bearer {TOKEN}"
        assert TOKEN not in url
    put_zip = fake.calls[2]
    assert "kind=file" in put_zip[1] and "conflict=replace" in put_zip[1]
    assert f"name=survey-{sid[:8]}-v1-prereg.zip" in put_zip[1]
    # what went up is exactly what the download gives
    c = benv.login("editor@a.example")
    assert put_zip[3] == c.get(f"/api/surveys/{sid}/versions/1/prereg-bundle").content
    assert fake.calls[3][3] == c.get(f"/api/surveys/{sid}/versions/1/prereg-summary").content

    # audited: project and files, never the token
    ctx = TenantContext(benv.tenants["A"], "system:test")
    entries = [e for e in benv.store.list_audit(ctx) if e.action == "prereg.osf_upload"]
    assert len(entries) == 1
    detail = entries[0].detail
    assert detail["node"] == NODE and detail["version"] == 1 and detail["osfUser"] == "u1"
    assert detail["files"] == [f["name"] for f in out["files"]]
    assert TOKEN not in json.dumps(detail)
    assert TOKEN not in repr(benv.store.list_audit(ctx))


def test_osf_upload_permissions_and_validation(benv):
    sid, _ = _published(benv)
    fake = FakeOsf()
    benv.services.osf_transport = fake
    assert _post(benv, "viewer@a.example", sid).status_code == 403  # needs survey.publish
    assert _post(benv, "owner@b.example", sid).status_code == 404
    assert (
        benv.client()
        .post(
            f"/api/surveys/{sid}/versions/1/prereg-bundle/osf", json={"token": TOKEN, "node": NODE}
        )
        .status_code
        == 401
    )
    assert _post(benv, "editor@a.example", sid, version=9).status_code == 404
    c = benv.login("editor@a.example")
    url = f"/api/surveys/{sid}/versions/1/prereg-bundle/osf"
    assert c.post(url, json={"node": NODE}).status_code == 422  # token missing
    assert c.post(url, json={"token": "short", "node": NODE}).status_code == 422
    assert c.post(url, json={"token": TOKEN, "node": "not a node id!"}).status_code == 422
    assert c.post(url, json={"token": TOKEN, "node": NODE, "extra": 1}).status_code == 422
    bad = c.post(url, json={"token": "has space in it 123", "node": NODE})
    assert bad.status_code == 422 and "has space" not in bad.text
    assert fake.calls == []  # nothing above reached the network
    # cross-origin POST is refused before anything happens
    r = c.post(url, json={"token": TOKEN, "node": NODE}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and fake.calls == []
    # a project URL is accepted and resolved to its id
    ok = c.post(url, json={"token": TOKEN, "node": f"https://osf.io/{NODE}/"})
    assert ok.status_code == 200 and ok.json()["nodeId"] == NODE


def test_osf_failures_are_502_without_the_token(benv):
    sid, _ = _published(benv)
    c = benv.login("editor@a.example")
    url = f"/api/surveys/{sid}/versions/1/prereg-bundle/osf"
    body = {"token": TOKEN, "node": NODE}

    benv.services.osf_transport = FakeOsf(me_status=401)
    r = c.post(url, json=body)
    assert r.status_code == 502 and r.json()["code"] == "upstream"
    assert "refused the token" in r.json()["message"] and TOKEN not in r.text

    benv.services.osf_transport = FakeOsf(node_status=404)
    r = c.post(url, json=body)
    assert r.status_code == 502 and f"no project '{NODE}'" in r.json()["message"]

    benv.services.osf_transport = FakeOsf(upload_status=507)
    r = c.post(url, json=body)
    assert r.status_code == 502 and "507" in r.json()["message"]

    benv.services.osf_transport = FakeOsf(raise_network=True)
    r = c.post(url, json=body)
    assert r.status_code == 502 and "could not be reached" in r.json()["message"]

    ctx = TenantContext(benv.tenants["A"], "system:test")
    assert not [e for e in benv.store.list_audit(ctx) if e.action == "prereg.osf_upload"]


def test_osf_test_servers_from_the_environment(benv, monkeypatch):
    monkeypatch.setenv("OSP_OSF_API_URL", "https://api.test.osf.io/v2/")
    monkeypatch.setenv("OSP_OSF_FILES_URL", "https://files.test.osf.io/v1")
    sid, _ = _published(benv)
    fake = FakeOsf()
    benv.services.osf_transport = fake
    assert _post(benv, "owner@a.example", sid).status_code == 200
    assert fake.calls[0][1] == "https://api.test.osf.io/v2/users/me/"
    assert fake.calls[2][1].startswith("https://files.test.osf.io/v1/resources/")


# -- the client on its own -------------------------------------------------------------------


def test_node_id_and_token_checks():
    assert node_id_of("ab3de") == "ab3de"
    assert node_id_of("  https://osf.io/ab3de/ ") == "ab3de"
    assert node_id_of("https://osf.io/ab3de/files/") == "ab3de"
    for bad in ("", "a", "ab 3de", "../x", None, 5, "https://osf.io/"):
        with pytest.raises(InvalidRequest):
            node_id_of(bad)
    assert check_token(TOKEN) == TOKEN
    for bad in ("short", "has space 1234567", "tab\t0123456789", "x" * 513, None, "é" * 10):
        with pytest.raises(InvalidRequest) as exc:
            check_token(bad)
        assert str(bad) not in exc.value.message


def test_client_parses_osf_answers_and_rejects_non_json():
    fake = FakeOsf()
    client = OsfClient(TOKEN, transport=fake)
    assert client.me().name == "Ada Example"
    node = client.node(f"https://osf.io/{NODE}/")
    assert node.title == "Framing study" and node.url == f"https://osf.io/{NODE}/"
    f = client.upload(NODE, "a b.zip", b"123")
    assert f.name == "a b.zip" and f.size == 3 and f.url
    assert "name=a%20b.zip" in fake.calls[-1][1]

    def garbage(*_: Any) -> tuple[int, bytes]:
        return 200, b"<html>"

    with pytest.raises(UpstreamError, match="not JSON"):
        OsfClient(TOKEN, transport=garbage).me()
