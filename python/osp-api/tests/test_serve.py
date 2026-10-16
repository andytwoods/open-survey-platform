"""``osp-api serve`` settings: dev defaults, dev keys (dev only), production refusals."""

from __future__ import annotations

import stat

import pytest
from fastapi.testclient import TestClient
from osp_api import serve
from osp_api.serve import ConfigError, Settings, build_app, keyring_env


def _dev(tmp_path, **extra: str) -> dict[str, str]:
    return {"OSP_DATA_DIR": str(tmp_path / ".data"), **extra}


def test_dev_defaults(tmp_path):
    s = Settings.from_env(_dev(tmp_path))
    assert s.env == "dev" and not s.production
    assert s.database_url == f"sqlite:///{tmp_path / '.data' / 'osp.db'}"
    assert (s.host, s.port) == ("127.0.0.1", 8000)


@pytest.mark.parametrize(
    "env",
    [{"OSP_ENV": "staging"}, {"OSP_PORT": "eighty"}, {"OSP_PORT": "70000"}],
)
def test_bad_settings_are_refused(tmp_path, env):
    with pytest.raises(ConfigError):
        Settings.from_env(_dev(tmp_path, **env))


def test_dev_keys_generated_once_private_and_reused(tmp_path):
    env = _dev(tmp_path)
    s = Settings.from_env(env)
    first = keyring_env(s, env)
    path = tmp_path / ".data" / "dev-keys.env"
    assert first["OSP_STORE_KEYS"].startswith("k1:")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert keyring_env(s, env) == first


def test_explicit_keys_win_and_no_file_is_written(tmp_path):
    env = _dev(tmp_path, OSP_STORE_KEYS="k9:" + "a" * 43 + "=")
    assert keyring_env(Settings.from_env(env), env)["OSP_STORE_KEYS"].startswith("k9:")
    assert not (tmp_path / ".data" / "dev-keys.env").exists()


def test_production_never_generates_or_reads_dev_keys(tmp_path):
    data = tmp_path / ".data"
    data.mkdir()
    (data / "dev-keys.env").write_text("OSP_STORE_KEYS=k1:" + "a" * 43 + "=\n")
    with pytest.raises(ConfigError, match="OSP_DATABASE_URL"):
        Settings.from_env(_dev(tmp_path, OSP_ENV="production"))
    env = _dev(tmp_path, OSP_ENV="production", OSP_DATABASE_URL="sqlite:///x.db")
    with pytest.raises(ConfigError, match="OSP_STORE_KEYS"):
        keyring_env(Settings.from_env(env), env)


def test_build_app_serves_health_and_builder_routes(tmp_path):
    env = _dev(tmp_path)
    c = TestClient(build_app(Settings.from_env(env), env), base_url="https://testserver")
    assert c.get("/api/health").json() == {"status": "ok"}
    assert c.get("/api/surveys").status_code == 401  # wired, not 503
    assert (tmp_path / ".data" / "osp.db").exists()


def test_main_serve_and_init(tmp_path, monkeypatch, capsys):
    for k, v in _dev(tmp_path).items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("OSP_STORE_KEYS", raising=False)
    monkeypatch.delenv("OSP_ENV", raising=False)
    assert serve.main(["init"]) == 0
    assert "dev-keys.env" in capsys.readouterr().out
    calls = []
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append(kw))
    assert serve.main(["serve", "--port", "8123"]) == 0
    assert calls[0]["port"] == 8123 and calls[0]["host"] == "127.0.0.1"
    monkeypatch.setenv("OSP_ENV", "production")
    assert serve.main(["serve"]) == 2
    assert "OSP_DATABASE_URL" in capsys.readouterr().err
