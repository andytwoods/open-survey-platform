"""Optional static serving (task H2b): OSP_PARTICIPANT_DIR and OSP_BUILDER_DIR."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from osp_api.serve import ConfigError, Settings, build_app

INDEX = "<!doctype html><html><head><meta http-equiv='Content-Security-Policy'></head></html>"


def _env(tmp_path, **extra: str) -> dict[str, str]:
    return {"OSP_DATA_DIR": str(tmp_path / ".data"), "OSP_IDENTITY": "dev", **extra}


@pytest.fixture
def dirs(tmp_path):
    runtime = tmp_path / "dist"
    (runtime / "assets").mkdir(parents=True)
    (runtime / "index.html").write_text(INDEX)
    (runtime / "assets" / "index-DaZYRvCX.js").write_text("export {}")
    (runtime / "favicon.svg").write_text("<svg/>")
    builder = tmp_path / "build"
    (builder / "assets").mkdir(parents=True)
    (builder / "manifest.json").write_text(json.dumps({"version": 1, "pages": {}}))
    (builder / "assets" / "editor-etj1SxNK.js").write_text("export {}")
    return runtime, builder


def test_off_by_default(tmp_path):
    c = TestClient(build_app(Settings.from_env(_env(tmp_path)), _env(tmp_path)))
    assert c.get("/r/").status_code == 404
    assert c.get("/s/abc").status_code == 404
    assert c.get("/builder/manifest.json").status_code == 404


def test_serves_participant_app_and_builder_files(tmp_path, dirs):
    runtime, builder = dirs
    env = _env(tmp_path, OSP_PARTICIPANT_DIR=str(runtime), OSP_BUILDER_DIR=str(builder))
    c = TestClient(build_app(Settings.from_env(env), env))
    for url in ("/r/", "/s/my-survey"):
        r = c.get(url)
        assert r.status_code == 200 and r.text == INDEX, url
        assert r.headers["cache-control"] == "no-store"
        assert r.headers["content-type"].startswith("text/html")
    asset = c.get("/r/assets/index-DaZYRvCX.js")
    assert asset.status_code == 200
    assert "immutable" in asset.headers["cache-control"]
    assert c.get("/r/favicon.svg").headers["cache-control"] == "no-cache"
    assert c.get("/r/missing.js").status_code == 404
    assert c.get("/r/../index.html").status_code == 404
    assert c.get("/builder/manifest.json").json() == {"version": 1, "pages": {}}
    assert c.get("/builder/assets/editor-etj1SxNK.js").status_code == 200
    # The API is untouched.
    assert c.get("/api/health").json() == {"status": "ok"}
    assert "/s/{slug}" not in c.get("/api/openapi.json").json()["paths"]


def test_missing_build_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="OSP_PARTICIPANT_DIR: .* has no index.html"):
        Settings.from_env(_env(tmp_path, OSP_PARTICIPANT_DIR=str(tmp_path / "nope")))
    with pytest.raises(ConfigError, match="OSP_BUILDER_DIR: .* has no manifest.json"):
        Settings.from_env(_env(tmp_path, OSP_BUILDER_DIR=str(tmp_path)))


CSP_INDEX = (
    '<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="'
    "default-src 'self'; script-src 'self'; img-src 'self' data: blob:; connect-src 'self'\" />"
    '</head><body><div id="app"></div></body></html>'
)


def test_media_csp_rewrites_img_and_media_src():
    from osp_api.static_files import media_csp, media_sources, rewrite_index

    origins = ["https://cdn.example.org", "https://video.example.org"]
    policy = "default-src 'self'; img-src 'self' data: blob:; connect-src 'self'"
    got = media_csp(policy, origins)
    assert got == (
        "default-src 'self'; img-src 'self' data: blob: https://cdn.example.org "
        "https://video.example.org; connect-src 'self'; media-src 'self' blob: "
        "https://cdn.example.org https://video.example.org"
    )
    assert media_csp(got, origins) == got  # idempotent
    with_media = "img-src 'self'; media-src 'self' blob:"
    assert media_csp(with_media, ["https://a.example"]) == (
        "img-src 'self' https://a.example; media-src 'self' blob: https://a.example"
    )
    assert media_sources(["https://a.example"]) == {
        "img-src": "'self' data: blob: https://a.example",
        "media-src": "'self' blob: https://a.example",
    }
    assert rewrite_index(CSP_INDEX, []) == CSP_INDEX
    assert "media-src 'self' blob: https://cdn.example.org" in rewrite_index(CSP_INDEX, origins[:1])


def test_participant_index_gets_the_media_origins(tmp_path, dirs):
    runtime, _builder = dirs
    (runtime / "index.html").write_text(CSP_INDEX)
    env = _env(
        tmp_path, OSP_PARTICIPANT_DIR=str(runtime), OSP_MEDIA_ORIGINS="https://cdn.example.org"
    )
    c = TestClient(build_app(Settings.from_env(env), env))
    for url in ("/r/", "/s/my-survey", "/r/index.html"):
        r = c.get(url)
        assert r.status_code == 200, url
        assert "img-src 'self' data: blob: https://cdn.example.org;" in r.text
        assert "media-src 'self' blob: https://cdn.example.org" in r.text
        assert r.headers["cache-control"] == "no-store"
    assert c.get("/r/favicon.svg").status_code == 200  # other files untouched
    with pytest.raises(ConfigError, match="OSP_MEDIA_ORIGINS takes exact origins"):
        Settings.from_env(_env(tmp_path, OSP_MEDIA_ORIGINS="cdn.example.org"))
