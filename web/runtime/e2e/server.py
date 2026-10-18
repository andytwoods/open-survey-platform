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
    hooks     web/runtime/e2e/surveys/flow           every-page, plus HOOKS (researcher code)
    redirect  web/runtime/e2e/surveys/redirect       every-page (end redirects, EN2)
    external  web/runtime/e2e/surveys/external       every-page (external task step, EX2)

It serves ``osp_api.app.create_app`` (the real participant API under ``/api``), the built
app (``web/runtime/dist``) at ``/s/{slug}`` and ``/r/*``, and test-only routes under
``/__test``: the name → slug map, what the server stored for a session (decrypted), and
which participant requests it received.

``/hosted/?s={slug}`` is the same page as a host would serve it with the API under another
prefix (D15): ``data-api-base="/osp/api"`` on the mount, and ``/osp/api/*`` forwarded to
osp-api's ``/api/*`` (a path rewrite standing in for the host's proxy).
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from osp_api.app import create_app
from osp_app import build_services
from osp_app.runtime_repo import StoreParticipantRepo
from osp_cli.main import seed_fixture
from osp_runtime import TokenBucket
from osp_runtime.plan import checksum, hooks_problem
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
    "hooks": (HERE / "surveys" / "flow", "every-page"),
    "redirect": (HERE / "surveys" / "redirect", "every-page"),
    "external": (HERE / "surveys" / "external", "every-page"),
}

# The `hooks` survey's manifest (runtime-design §7a). osp-survey/0.1 has no hooks field, so
# the publish is intercepted and the manifest goes into the plan (and its checksum), as the
# plan compiler's `hooks=` does. onPageNext rejects age 99 with a hook message;
# onBeforeSubmit records paradata, which must be in the stored response.
HOOKS: dict[str, Any] = {
    "format": "osp-hooks/1",
    "source": (
        "osp.on('onPageNext', function (ctx, data, act) {"
        " var a = ctx.results.age;"
        " if (a && a.value === 99) act.rejectPage({ itemId: 'age', message: 'Hook says: not 99.' });"
        " });\n"
        "osp.on('onBeforeSubmit', function (ctx, data, act) { act.addParadata('hooked', true); });"
    ),
    "handlers": {
        "onPageNext": {"reads": ["age"], "writes": []},
        "onBeforeSubmit": {"reads": [], "writes": []},
    },
}


def _events(snapshot: Any) -> list[Any]:
    try:
        return list(snapshot["data"]["events"])
    except KeyError, TypeError:
        return []


def _prefix(a: list[Any], b: list[Any] | None) -> bool:
    if b is None or len(a) > len(b):
        return False
    return json.dumps(a, sort_keys=True) == json.dumps(b[: len(a)], sort_keys=True)


def build(db: Path) -> FastAPI:
    engine = create_engine(f"sqlite:///{db}")  # osp-store sets WAL + busy timeout
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
    publish = s.publish
    with_hooks = {"on": False}

    def publish_hooked(
        tenant: str, actor: str, version: str, slug: str, plan: Any, config: Any
    ) -> Any:
        if with_hooks["on"]:
            assert hooks_problem(HOOKS) is None, hooks_problem(HOOKS)
            plan = {**plan, "hooks": HOOKS}
            plan["checksum"] = checksum(plan)
        return publish(tenant, actor, version, slug, plan, config)

    s.publish = publish_hooked  # type: ignore[method-assign]
    for name, (folder, mode) in SURVEYS.items():
        with_hooks["on"] = name == "hooks"
        seeded = seed_fixture(services, folder, save_mode=mode)
        slugs[name] = seeded["slug"]
        tenant_id = seeded["tenantId"]

    repo = StoreParticipantRepo(store)
    app = create_app(builder=services)
    requests: list[dict[str, str]] = []

    @app.middleware("http")
    async def log_requests(request: Request, call_next: Any) -> Any:
        path = request.scope.get("osp_public_path", request.url.path)
        if request.url.path.startswith("/api/"):
            requests.append({"method": request.method, "path": path})
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
                select(func.count()).select_from(t.responses).where(t.responses.c.session_id == sid)
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

    @app.get("/hosted/")
    def hosted_page() -> HTMLResponse:
        html = (DIST / "index.html").read_text(encoding="utf-8")
        html = html.replace('<div id="app">', '<div id="app" data-api-base="/osp/api">', 1)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    app.mount("/r", StaticFiles(directory=DIST), name="runtime")
    return app


class HostPrefix:
    """The host's proxy, in miniature: ``/osp/api/*`` reaches osp-api as ``/api/*``."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope["path"].startswith("/osp/api/"):
            path = "/api/" + scope["path"].removeprefix("/osp/api/")
            scope = {
                **scope,
                "path": path,
                "raw_path": path.encode(),
                "osp_public_path": scope["path"],
            }
        await self.app(scope, receive, send)


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4391)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="osp-r3-") as tmp:
        app = HostPrefix(build(Path(tmp) / "e2e.db"))
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
