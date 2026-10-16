"""Bring up a fresh LimeSurvey, enable RemoteControl 2, import + activate the test survey. API only."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import httpx

from .rpc import BASE, RC2, RPCError, b64

HERE = Path(__file__).resolve().parent.parent
COMPOSE = ["docker", "compose", "-f", str(HERE / "docker-compose.yml")]
LSS = HERE / "survey" / "spike1.lss"
SID = 900001


def sh(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), check=check, capture_output=True, text=True)


def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return sh(*COMPOSE, *args, check=check)


def fresh_containers() -> None:
    compose("down", "-v", "--remove-orphans")
    compose("up", "-d", "--wait", "db")
    compose("up", "-d", "limesurvey")


def sql(stmt: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return compose("exec", "-T", "db", "mariadb", "-ulimesurvey", "-pspike1-local-db-pw", "limesurvey",
                   "-N", "-e", stmt, check=check)


def wait_installed(timeout: float = 240) -> None:
    """The image's entrypoint runs LimeSurvey's console installer; wait for it and for Apache."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = sql("SELECT stg_value FROM lime_settings_global WHERE stg_name='DBVersion'", check=False)
        if r.returncode == 0 and r.stdout.strip():
            try:
                if httpx.get(f"{BASE}/index.php", timeout=5).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
        time.sleep(1)
    raise TimeoutError("LimeSurvey did not finish installing")


def enable_rpc() -> None:
    """No admin clicks: seed the global settings rows the admin UI would write."""
    sql("INSERT INTO lime_settings_global (stg_name, stg_value) VALUES ('RPCInterface','json') "
        "ON DUPLICATE KEY UPDATE stg_value='json'")


def deploy(c: RC2, tokens: list[str]) -> dict:
    sid = c.call("import_survey", b64(LSS.read_bytes()), "lss", "OSP spike 1 test survey", SID)
    act = c.call("activate_survey", sid)
    tok = c.call("activate_tokens", sid, [])
    parts = c.call("add_participants", sid, [
        {"firstname": "Fake", "lastname": t.upper(), "email": f"{t}@example.invalid", "token": t} for t in tokens
    ], False)
    props = c.call("get_survey_properties", sid, ["active", "access_mode", "allowprev", "tokenanswerspersistence",
                                                 "anonymized", "alloweditaftercompletion", "format"])
    return {"sid": sid, "activate": act, "activate_tokens": tok, "participants": parts, "properties": props}


def lookup(c: RC2, sid: int) -> tuple[dict[int, str], dict[str, str], dict]:
    qs = c.call("list_questions", sid)
    codes = {int(q["qid"]): q["title"] for q in qs}
    fmap = c.call("get_fieldmap", sid)
    sgqa = {v["title"]: k for k, v in fmap.items() if v.get("title")}
    return codes, sgqa, fmap


__all__ = ["RC2", "RPCError", "fresh_containers", "wait_installed", "enable_rpc", "deploy", "lookup", "sql",
           "compose", "SID"]
