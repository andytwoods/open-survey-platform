"""S6 acceptance: changing an endpoint without regenerating the contract fails the check."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "contract.py"
OPENAPI = REPO / "contract" / "openapi.json"
TS = REPO / "web" / "api-client" / "src" / "schema.d.ts"

STALE_APP = """
from osp_api.app import create_app


def make():
    app = create_app()

    @app.get("/api/extra", operation_id="getExtra")
    def extra() -> dict[str, str]:
        return {}

    return app
"""


def _run(*args, pythonpath: Path | None = None):
    env = dict(os.environ)
    if pythonpath:
        env["PYTHONPATH"] = str(pythonpath)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=REPO, env=env
    )


def test_committed_contract_is_fresh():
    result = _run("check")
    assert result.returncode == 0, result.stdout + result.stderr


def test_dump_is_deterministic_and_sorted(tmp_path):
    out = []
    for i in range(2):
        ts = tmp_path / f"schema{i}.d.ts"
        result = _run("generate", "--openapi", str(tmp_path / f"o{i}.json"), "--ts", str(ts))
        assert result.returncode == 0, result.stderr
        out.append(((tmp_path / f"o{i}.json").read_bytes(), ts.read_bytes()))
    assert out[0] == out[1]
    assert out[0][0] == OPENAPI.read_bytes()
    text = out[0][0].decode()
    assert text == json.dumps(json.loads(text), sort_keys=True, indent=2) + "\n"


def test_changed_endpoint_without_regenerating_fails(tmp_path):
    (tmp_path / "stale_app.py").write_text(STALE_APP)
    result = _run("check", "--app", "stale_app:make", pythonpath=tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "contract/openapi.json is STALE" in result.stderr
    assert "web/api-client/src/schema.d.ts is STALE" in result.stderr
    assert "/api/extra" in result.stderr


def test_hand_edited_ts_client_fails(tmp_path):
    openapi = tmp_path / "openapi.json"
    ts = tmp_path / "schema.d.ts"
    shutil.copy(OPENAPI, openapi)
    ts.write_text(TS.read_text() + "export type HandEdit = 1;\n")
    result = _run("check", "--openapi", str(openapi), "--ts", str(ts))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "schema.d.ts is STALE" in result.stderr
    assert "openapi.json is STALE" not in result.stderr
