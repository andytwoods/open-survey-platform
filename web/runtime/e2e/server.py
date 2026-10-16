"""Test-only launcher for the runtime's Playwright tests (task R3). Not shipped.

    uv run --locked --with uvicorn==0.38.0 python web/runtime/e2e/server.py --port 4391

A fresh SQLite store in a temp dir. Each test survey is imported and published through
the real builder path (``osp_cli.main.seed_fixture`` → ``survey.publish``), which compiles
the runtime plan and gives the survey its public slug:

    flow      web/runtime/e2e/surveys/flow           every-page
    alltypes  fixtures/01-all-types                  every-page
    quota     fixtures/24-quota-pending-retry        every-page (quotaCheck node)
    assign    fixtures/16-assign                     every-page (server assignment)
    endonly   fixtures/33-end-only-save              end-only

It serves ``osp_api.app.create_app`` (the real participant API under ``/api``), the built
app (``web/runtime/dist``) at ``/s/{slug}`` and ``/r/*``, and test-only routes under
``/__test``: the name → slug map, what the server stored for a session (decrypted), and
which participant requests it received.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from osp_api.app import create_app
from osp_app import build_services
from osp_app.runtime_repo import StoreParticipantRepo
from osp_cli.main import seed_fixture
from osp_runtime import TokenBucket
from osp_store import Keyring, Store, TenantContext, create_engine, generate_key, migrate
from osp_store import schema as t
from sqlalchemy import func, select

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DIST = HERE.parent / "dist"

SURVEYS: dict[str, tuple[Path, str]] = {
    "flow": (HERE / "surveys" / "flow", "every-page"),
    "alltypes": (ROOT / "fixtures" / "01-all-types", "every-page"),
    "quota": (ROOT / "fixtures" / "24-quota-pending-retry", "every-page"),
    "assign": (ROOT / "fixtures" / "16-assign", "every-page"),
    "endonly": (ROOT / "fixtures" / "33-end-only-save", "end-only"),
}


def _events(snapshot: Any) -> list[Any]:
    try:
        return list(snapshot["data"]["events"])
    except (KeyError, TypeError):
        return []


def _prefix(a: list[Any], b: list[Any] | None) -> bool:
    if b is None or len(a) > len(b):
        return False
    return json.dumps(a, sort_keys=True) == json.dumps(b[: len(a)], sort_keys=True)


def build(db: Path) -> FastAPI:
    # Concurrent test workers: wait for the SQLite write lock instead of failing.
    engine = create_engine(f"sqlite:///{db}", connect_args={"timeout": 30})
    migrate(engine)
    store = Store(engine, Keyring({"k1": generate_key()}, active="k1"))
    services = build_services(store)
    # One test client starts many sessions: lift the per-link and per-client limits.
    s = services.sessions
    s._start_limiter = TokenBucket(10_000, 100)
    s._client_limiter = TokenBucket(10_000, 100)
    s._resume_limiter = TokenBucket(10_000, 100)

    slugs: dict[str, str] = {}
    tenant_id = ""
    for name, (folder, mode) in SURVEYS.items():
        seeded = seed_fixture(services, folder, save_mode=mode)
        slugs[name] = seeded["slug"]
        tenant_id = seeded["tenantId"]

    repo = StoreParticipantRepo(store)
    app = create_app(builder=services)
    requests: list[dict[str, str]] = []

    @app.middleware("http")
    async def log_requests(request: Request, call_next: Any) -> Any:
        if request.url.path.startswith("/api/"):
            requests.append({"method": request.method, "path": request.url.path})
        return await call_next(request)

    def tctx(sid: str) -> TenantContext:
        return TenantContext(tenant_id, f"participant:{sid}")

    @app.get("/__test/surveys")
    def surveys() -> dict[str, str]:
        return slugs

    @app.get("/__test/sessions/{sid}")
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
            "record": stored["record"] if stored else None,  # {"record", "server"}
            "conflicts": len(repo.ps.list_conflicts(tctx(sid), sid)),
            # A conflict row loses data only if its snapshot is not a prefix of what was
            # finally submitted. Stale late writes of older copies are harmless.
            "conflictsLosingData": sum(
                1
                for c in repo.ps.list_conflicts(tctx(sid), sid)
                if not _prefix(_events(c.snapshot), (stored or {}).get("record", {}).get("events"))
            ),
            "saveMode": sess.save_mode,
        }

    @app.get("/__test/requests")
    def get_requests() -> list[dict[str, str]]:
        return requests

    @app.get("/s/{slug}")
    def page(slug: str) -> FileResponse:
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-store"})

    app.mount("/r", StaticFiles(directory=DIST), name="runtime")
    return app


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4391)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="osp-r3-") as tmp:
        app = build(Path(tmp) / "e2e.db")
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
