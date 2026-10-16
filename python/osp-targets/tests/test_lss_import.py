"""Import every exported ``.lss`` into a real LimeSurvey 6.17 over RemoteControl 2.

Optional (``make lss-import-check``), not part of ``make check``: it needs Docker and the
pinned images from ``spikes/spike-1/docker-compose.yml`` (LimeSurvey 6.17.18 + MariaDB,
local-only throwaway credentials). Runs only with ``OSP_LSS_IMPORT=1``; skips cleanly when
Docker is not available. Set ``OSP_LSS_IMPORT_KEEP=1`` to leave the containers running.

Checks per survey: the import succeeds, the survey activates (LimeSurvey builds the
response table, which fails on bad codes), and every question code we wrote is there.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from osp_targets.lss import build_lss

REPO = Path(__file__).resolve().parents[3]
COMPOSE_FILE = REPO / "spikes/spike-1/docker-compose.yml"
BASE = "http://localhost:8082"
RPC_URL = f"{BASE}/index.php?r=admin/remotecontrol"
# Local-only throwaway credentials from spikes/spike-1/docker-compose.yml.
ADMIN = ("admin", "spike1-local-admin-pw")
DB_PASSWORD = "spike1-local-db-pw"

FIXTURES = sorted((REPO / "fixtures").glob("*/survey.json"))
CASES = sorted((REPO / "python/osp-spec/tests/cases/valid").glob("*.json"))

pytestmark = pytest.mark.skipif(
    os.environ.get("OSP_LSS_IMPORT") != "1",
    reason="set OSP_LSS_IMPORT=1 (make lss-import-check) to import into a real LimeSurvey",
)


def _docker_ok() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=20, check=False)
    except OSError, subprocess.SubprocessError:
        return False
    return r.returncode == 0


def _compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],
        capture_output=True,
        text=True,
        check=check,
        timeout=600,
    )


def _sql(stmt: str) -> subprocess.CompletedProcess[str]:
    return _compose(
        "exec", "-T", "db", "mariadb", "-ulimesurvey", f"-p{DB_PASSWORD}", "limesurvey", "-N",
        "-e", stmt, check=False,
    )  # fmt: skip


def _http_ok() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE}/index.php", timeout=5) as r:
            return r.status == 200
    except urllib.error.URLError, OSError:
        return False


def _wait_installed(timeout: float = 300) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = _sql("SELECT stg_value FROM lime_settings_global WHERE stg_name='DBVersion'")
        if r.returncode == 0 and r.stdout.strip() and _http_ok():
            return
        time.sleep(2)
    raise TimeoutError("LimeSurvey did not finish installing")


class _RPC:
    def __init__(self) -> None:
        self.key: str | None = None
        self.n = 0

    def raw(self, method: str, *params: Any) -> Any:
        self.n += 1
        body = json.dumps({"method": method, "params": list(params), "id": self.n}).encode()
        req = urllib.request.Request(
            RPC_URL, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
        if data.get("error"):
            raise RuntimeError(f"{method}: {data['error']}")
        return data["result"]

    def call(self, method: str, *params: Any) -> Any:
        if self.key is None:
            self.key = self.raw("get_session_key", *ADMIN)
            assert isinstance(self.key, str), self.key
        return self.raw(method, self.key, *params)


@pytest.fixture(scope="module")
def rpc() -> Iterator[_RPC]:
    if not _docker_ok():
        pytest.skip("Docker is not available")
    started = False
    if not _http_ok():
        _compose("up", "-d", "--wait", "db")
        _compose("up", "-d", "limesurvey")
        started = True
    _wait_installed()
    _sql(
        "INSERT INTO lime_settings_global (stg_name, stg_value) VALUES ('RPCInterface','json') "
        "ON DUPLICATE KEY UPDATE stg_value='json'"
    )
    client = _RPC()
    version = client.call("get_site_settings", "versionnumber")
    assert str(version).startswith("6.17"), version
    yield client
    if started and os.environ.get("OSP_LSS_IMPORT_KEEP") != "1":
        _compose("down", "-v", "--remove-orphans", check=False)


def _survey(path: Path) -> Any:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("survey", data)


SURVEYS = [(f"fixture/{p.parent.name}", p) for p in FIXTURES] + [
    (f"case/{p.stem}", p) for p in CASES
]


@pytest.mark.parametrize(("label", "path"), SURVEYS, ids=[s[0] for s in SURVEYS])
def test_imports_into_limesurvey(rpc: _RPC, label: str, path: Path) -> None:
    result, diags = build_lss(_survey(path))
    assert result is not None, diags
    sid = rpc.call("import_survey", base64.b64encode(result.xml).decode(), "lss")
    assert isinstance(sid, int), f"{label}: import failed: {sid}"
    try:
        questions = rpc.call("list_questions", sid)
        assert isinstance(questions, list), questions
        codes = {q["title"] for q in questions if str(q.get("parent_qid")) == "0"}
        expected = {c for c in result.name_map.values()}
        # Variables in unreached blocks are not exported; everything else must be there.
        assert expected & codes, (label, codes)
        missing = {c for c in expected if c not in codes} - _unexported(result)
        assert not missing, (label, missing)
        quotas = rpc.call("list_quotas", sid)
        quota_table = ET.fromstring(result.xml).find("quota")
        n_quotas = 0 if quota_table is None else len(list(quota_table.iter("row")))
        assert (len(quotas) if isinstance(quotas, list) else 0) == n_quotas, quotas
        activated = rpc.call("activate_survey", sid)
        assert isinstance(activated, dict) and activated.get("status") == "OK", activated
    finally:
        rpc.call("delete_survey", sid)


def _unexported(result: Any) -> set[str]:
    """Codes of questions in blocks the flow never shows (not written to the .lss)."""
    text = result.xml.decode("utf-8")
    return {c for c in result.name_map.values() if f"<title><![CDATA[{c}]]></title>" not in text}
