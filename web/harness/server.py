"""Test-only launcher for the fixture harness (task R4). Not shipped.

    uv run --locked --with uvicorn==0.38.0 python web/harness/server.py --port 4392

Like R3's ``web/runtime/e2e/server.py`` (a fresh SQLite store, the real ``osp_api`` app,
the built participant app at ``/s/{slug}``), but it publishes **every fixture** through the
real builder path (``osp_cli.main.seed_fixture`` → ``survey.publish``) and lets a harness
session start with the fixture script's ``sessionSeed`` and ``server.conditions``:

- ``x-osp-harness-start: {"seed": n, "conditions": {...}}`` on ``POST /api/s/{slug}/sessions``
  (the harness adds it with a Playwright route; the app never sends it). The server's
  CSPRNG then returns ``seed`` for this one start, and the assignment is replaced by
  ``conditions`` (``{}`` when the script names none: the engine then draws, as in the
  engine runner). Everything else (tokens, revisions, quota, submit) is the real code path.
- ``server.quotas``: each fixture is published once per distinct quota setting found in its
  scripts. A quota marked ``full`` gets ``used = cap``; every other quota gets an unlimited
  cap, so parallel runs never fill it by accident.

Fixtures that cannot be published are listed with their error, never crash the launcher.

Test-only routes:
    GET /__harness/surveys          {fixture: {"slugs": {variantKey: slug}, "saveMode", "error"}}
    GET /__harness/sessions/{sid}   what the server stored for a session (decrypted)
"""

from __future__ import annotations

import argparse
import contextvars
import json
import secrets
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from osp_api.app import create_app
from osp_app import build_services
from osp_app.runtime_repo import StoreParticipantRepo
from osp_cli.main import DEFAULT_LAB, researcher, seed_fixture
from osp_engine.random import MAX_SEED
from osp_runtime import TokenBucket
from osp_store import Keyring, Store, TenantContext, create_engine, generate_key, migrate
from osp_store import schema as t
from sqlalchemy import func, select, update

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXTURES = ROOT / "fixtures"
DIST = ROOT / "web" / "runtime" / "dist"
HEADER = b"x-osp-harness-start"

# Fixtures whose save mode the model cannot express yet (R6-5): published as R3 does.
SAVE_MODES = {"33-end-only-save": "end-only"}

_start: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "harness_start", default=None
)


class HarnessRandom:
    """The server CSPRNG, except that a harness start gets the script's session seed."""

    def token_bytes(self, n: int) -> bytes:
        return secrets.token_bytes(n)

    def randbelow(self, n: int) -> int:
        o = _start.get()
        if o is not None and n == MAX_SEED and isinstance(o.get("seed"), int):
            return int(o["seed"]) - 1  # start() adds 1
        return secrets.randbelow(n)


class HarnessStart:
    """Pure ASGI middleware: the harness header → a context variable for this request."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            raw = dict(scope.get("headers") or []).get(HEADER)
            if raw:
                token = _start.set(json.loads(raw.decode("utf-8")))
                try:
                    await self.app(scope, receive, send)
                finally:
                    _start.reset(token)
                return
        await self.app(scope, receive, send)


def quota_variants(folder: Path) -> list[dict[str, str]]:
    """Distinct ``server.quotas`` settings over a fixture's scripts ({} always included)."""
    seen: dict[str, dict[str, str]] = {"{}": {}}
    for f in sorted((folder / "scripts").glob("*.json")):
        try:
            quotas = (json.loads(f.read_text("utf-8")).get("server") or {}).get("quotas") or {}
        except (OSError, ValueError):
            continue
        seen.setdefault(variant_key(quotas), dict(quotas))
    return list(seen.values())


def fixture_version(folder: Path) -> int:
    """The ``version`` a fixture survey was written for (1 if none)."""
    try:
        v = json.loads((folder / "survey.json").read_text("utf-8")).get("version")
    except (OSError, ValueError):
        return 1
    return v if isinstance(v, int) and v > 1 else 1


def variant_key(quotas: dict[str, str]) -> str:
    return json.dumps(quotas, sort_keys=True, separators=(",", ":"))


def build(db: Path) -> FastAPI:
    engine = create_engine(f"sqlite:///{db}", connect_args={"timeout": 30})
    migrate(engine)
    store = Store(engine, Keyring({"k1": generate_key()}, active="k1"))
    services = build_services(store)
    s = services.sessions
    # One test client starts many sessions: lift the per-link and per-client limits.
    s._start_limiter = TokenBucket(100_000, 1000)
    s._client_limiter = TokenBucket(100_000, 1000)
    s._resume_limiter = TokenBucket(100_000, 1000)
    s._rng = HarnessRandom()

    repo_start = s._repo.start

    def start(*args: Any) -> Any:
        # (tenant, publication, seed, assigned, token_hash, params, balanced, choose)
        o = _start.get()
        if o is not None:
            a = list(args)
            conditions = dict(o.get("conditions") or {})
            a[3] = conditions
            a[6] = ()  # no balanced counting: the script fixes every condition
            return repo_start(*a)
        return repo_start(*args)

    s._repo.start = start  # type: ignore[method-assign]

    surveys: dict[str, dict[str, Any]] = {}
    tenant_id = ""
    for folder in sorted(p for p in FIXTURES.iterdir() if (p / "survey.json").is_file()):
        mode = SAVE_MODES.get(folder.name, "every-page")
        entry: dict[str, Any] = {"slugs": {}, "saveMode": mode, "error": None}
        surveys[folder.name] = entry
        for quotas in quota_variants(folder):
            try:
                seeded = seed_fixture(services, folder, save_mode=mode)
            except Exception as exc:  # a fixture that can't publish is reported, not fatal
                entry["error"] = f"{type(exc).__name__}: {exc}"
                break
            tenant_id = seeded["tenantId"]
            # The plan's seed version is the published number (semantics R1-1). A fixture
            # written for version N (e.g. 20: "version": 3) is published N times, so its
            # orders and `surveyVersion` match the engine runner, which reads the file.
            want = fixture_version(folder)
            if want > seeded["versionNumber"]:
                actor = researcher(services, seeded["email"], seeded["password"], DEFAULT_LAB)
                for _ in range(want - seeded["versionNumber"]):
                    services.builder.run(
                        "survey.publish", actor, survey_id=seeded["surveyId"], save_mode=mode
                    )
            pub = s._repo.find_publication(seeded["slug"])
            qc = t.quota_counters.c
            with engine.begin() as conn:
                for row in conn.execute(
                    select(qc.quota_id, qc.cap).where(qc.publication_id == pub.id)
                ).all():
                    full = quotas.get(row.quota_id) == "full"
                    values = {"used": row.cap} if full else {"cap": 1_000_000_000, "used": 0}
                    conn.execute(
                        update(t.quota_counters)
                        .where((qc.publication_id == pub.id) & (qc.quota_id == row.quota_id))
                        .values(**values)
                    )
            entry["slugs"][variant_key(quotas)] = seeded["slug"]

    repo = StoreParticipantRepo(store)
    app = create_app(builder=services)

    def tctx(sid: str) -> TenantContext:
        return TenantContext(tenant_id, f"participant:{sid}")

    @app.get("/__harness/surveys")
    def list_surveys() -> dict[str, Any]:
        return surveys

    @app.get("/__harness/sessions/{sid}")
    def inspect(sid: str) -> dict[str, Any]:
        sess = repo.get(tenant_id, sid)
        ps = t.participant_sessions.c
        with engine.connect() as conn:
            response_id = conn.execute(select(ps.response_id).where(ps.id == sid)).scalar_one()
            responses = conn.execute(
                select(func.count())
                .select_from(t.responses)
                .where(t.responses.c.session_id == sid)
            ).scalar_one()
        stored = repo.ps.get_record(tctx(sid), response_id) if response_id else None
        return {
            "revision": sess.revision,
            "snapshot": sess.snapshot,
            "submitted": sess.submitted_at is not None,
            "responses": responses,
            "record": stored["record"] if stored else None,
            "server": stored["server"] if stored else None,
            "conflicts": len(repo.ps.list_conflicts(tctx(sid), sid)),
            "saveMode": sess.save_mode,
        }

    @app.get("/s/{slug}")
    def page(slug: str) -> FileResponse:
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-store"})

    app.mount("/r", StaticFiles(directory=DIST), name="runtime")
    return app


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4392)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="osp-r4-") as tmp:
        app = build(Path(tmp) / "harness.db")
        uvicorn.run(HarnessStart(app), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
