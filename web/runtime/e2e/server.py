"""Test-only backend for the runtime's Playwright tests (task R3). Not shipped.

    uv run --locked --with uvicorn==0.38.0 python web/runtime/e2e/server.py --port 4391

A fresh SQLite store in a temp dir, one lab, and these surveys published as participant
links (compiled with ``osp_runtime.plan``, the same path a real publish takes):

    /s/flow      web/runtime/e2e/surveys/flow.json         every-page
    /s/alltypes  fixtures/01-all-types                     every-page
    /s/quota     fixtures/24-quota-pending-retry           every-page (quotaCheck node)
    /s/assign    fixtures/16-assign                        every-page (server assignment)
    /s/endonly   fixtures/33-end-only-save                 end-only

It serves the built app (``web/runtime/dist``) at ``/s/{slug}`` and ``/r/*``, the real
participant API under ``/api``, and test-only inspection routes under ``/__test`` that
read what the server stored (decrypted) and which participant requests it received.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from osp_api.app import create_app
from osp_api.runtime_repo import StoreParticipantRepo
from osp_runtime import SessionService, TokenBucket
from osp_runtime.plan import compile_survey, runtime_config
from osp_store import Keyring, Store, SystemContext, TenantContext, create_engine, migrate
from osp_store import schema as t
from sqlalchemy import func, select

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DIST = HERE.parent / "dist"
KEY = "b" * 43 + "="

SURVEYS: dict[str, tuple[Path, str]] = {
    "flow": (HERE / "surveys" / "flow.json", "every-page"),
    "alltypes": (ROOT / "fixtures" / "01-all-types" / "survey.json", "every-page"),
    "quota": (ROOT / "fixtures" / "24-quota-pending-retry" / "survey.json", "every-page"),
    "assign": (ROOT / "fixtures" / "16-assign" / "survey.json", "every-page"),
    "endonly": (ROOT / "fixtures" / "33-end-only-save" / "survey.json", "end-only"),
}


def build(db: Path) -> FastAPI:
    engine = create_engine(f"sqlite:///{db}")
    migrate(engine)
    store = Store(engine, Keyring({"k1": KEY}, active="k1"))
    repo = StoreParticipantRepo(store)
    service = SessionService(
        repo, start_limiter=TokenBucket(10_000, 100), resume_limiter=TokenBucket(10_000, 100)
    )
    service._client_limiter = TokenBucket(10_000, 100)  # one test client starts many sessions
    tenant = store.create_tenant(SystemContext("system:e2e"), "E2E lab")
    ctx = TenantContext(tenant.id, "researcher:e2e")
    for slug, (path, mode) in SURVEYS.items():
        plan, diags = compile_survey(json.loads(path.read_text()))
        if plan is None:
            raise SystemExit(f"{slug}: {[d.message for d in diags]}")
        survey, _ = store.create_survey(ctx, slug, {"blocks": []})
        version = store.publish_version(ctx, survey.id, b"", meta={})
        service.publish(
            ctx.tenant_id,
            ctx.actor,
            version.id,
            slug,
            plan,
            runtime_config(plan, save_mode=mode),
        )

    app = create_app(service)
    requests: list[dict[str, str]] = []

    @app.middleware("http")
    async def log_requests(request: Request, call_next: Any) -> Any:
        if request.url.path.startswith("/api/"):
            requests.append({"method": request.method, "path": request.url.path})
        return await call_next(request)

    def tctx(sid: str) -> TenantContext:
        return TenantContext(tenant.id, f"participant:{sid}")

    @app.get("/__test/sessions/{sid}")
    def inspect(sid: str) -> dict[str, Any]:
        sess = repo.get(tenant.id, sid)
        with engine.connect() as conn:
            ps = t.participant_sessions.c
            response_id = conn.execute(
                select(ps.response_id).where(ps.id == sid)
            ).scalar_one_or_none()
            responses = conn.execute(
                select(func.count())
                .select_from(t.responses)
                .where(t.responses.c.session_id == sid)
            ).scalar_one()
        stored = repo.ps.get_record(tctx(sid), response_id) if response_id else None
        record = stored["record"] if stored else None  # {"record": ResponseRecord, "server": ...}
        return {
            "revision": sess.revision,
            "snapshot": sess.snapshot,
            "submitted": sess.submitted_at is not None,
            "responses": responses,
            "record": record,
            "conflicts": len(repo.ps.list_conflicts(tctx(sid), sid)),
            "saveMode": sess.save_mode,
        }

    @app.get("/__test/requests")
    def get_requests() -> list[dict[str, str]]:
        return requests

    @app.get("/s/{slug}")
    def page(slug: str) -> FileResponse:
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/")
    def root() -> JSONResponse:
        return JSONResponse({"surveys": sorted(SURVEYS)})

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
