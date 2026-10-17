"""Throwaway `osp-api` for the builder's end-to-end tests (`make web-e2e`).

A fresh SQLite database in a temp directory, served by uvicorn. There is no sign-in (plan
P, the host owns it): every request is the dev researcher, owner of the dev lab, via
:func:`identity_provider` (the one place to change if the e2e setup needs another
identity). Test-only: never import this, never point it at real data.

    uv run --locked --with uvicorn python web/builder/e2e/api_server.py --port 4318

If the participant app is built (``web/runtime/dist``), it is served too: ``/s/{slug}`` and
``/r/*``, as in production, so a test can publish and then open the participant link (the
builder's preview server proxies those paths here).
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from osp_api.app import create_app
from osp_api.identity import Dev, IdentityProvider
from osp_app import build_services
from osp_app.identity import DEV_LAB_ID
from osp_runtime import TokenBucket
from osp_store import Keyring, ParticipantStore, Store, TenantContext, create_engine, migrate

# This server serves the participant app at /s/{slug}, so publish should link there.
os.environ.setdefault("OSP_PARTICIPANT_URL_TEMPLATE", "/s/{slug}")

RUNTIME_DIST = Path(__file__).resolve().parents[2] / "runtime" / "dist"
# The results aggregation's hand-checked fixture (task V1): a survey with every question
# type and five fake responses. The results page e2e (results.spec.ts) seeds it here.
RESULTS_DATA = Path(__file__).resolve().parents[3] / "python/osp-app/tests/results_data.py"


def _results_data() -> Any:
    spec = importlib.util.spec_from_file_location("osp_e2e_results_data", RESULTS_DATA)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def identity_provider(host: str) -> IdentityProvider:
    """Who every e2e request is: the dev researcher (``osp_app.identity.DEV_USER_ID``),
    owner of ``dev-lab``. Dev refuses anything but a loopback bind."""
    return Dev(env="dev", host=host)


def build(db_dir: Path, host: str = "127.0.0.1") -> FastAPI:
    engine = create_engine(f"sqlite:///{db_dir / 'e2e.db'}")
    migrate(engine)
    key = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    store = Store(engine, Keyring({"k1": key}, active="k1"))
    services = build_services(store)
    # Live results (task LV3): the shortest poll interval the server allows, so an e2e test
    # sees a seeded response within a second or two; and a limiter wide enough for several
    # live tests polling in parallel as the one dev user (production: a burst of 5, then 1/s).
    app = create_app(builder=services, identity=identity_provider(host), live_poll_ms=1000)
    app.state.watermark_limiter = TokenBucket(100, 50.0)
    # For callers that outlive the temp dir (results/fixtures/regenerate.py): dispose the
    # pool before removing e2e.db, or Windows refuses to delete the open file.
    app.state.engine = engine
    results_data = _results_data()

    # Test-only helpers for the results page e2e (under /api so the builder's preview
    # server proxies them): the fixture survey's JSON (the test creates the survey through
    # the real API), then publish it and record the five fixture responses straight into
    # the store, as osp-app's own tests do. Never part of a real server.
    @app.get("/api/e2e/results-fixture", include_in_schema=False)
    def results_fixture() -> dict[str, Any]:
        return results_data.SURVEY

    @app.post("/api/e2e/results-seed/{survey_id}", include_in_schema=False)
    def results_seed(survey_id: str) -> dict[str, Any]:
        ctx = TenantContext(DEV_LAB_ID, "system:e2e")
        version = results_data.publish(store, ctx, survey_id, results_data.SURVEY)
        ids = results_data.seed(store, ctx, version.id)
        return {"version": version.number, "responses": len(ids)}

    # One more fixture response (a copy of the first), recorded now, into the survey's
    # latest published version: what "a response arrives while the page is open" looks like
    # to the live results page (task LV3). Returns the stored total.
    @app.post("/api/e2e/results-seed-one/{survey_id}", include_in_schema=False)
    def results_seed_one(survey_id: str) -> dict[str, Any]:
        ctx = TenantContext(DEV_LAB_ID, "system:e2e")
        versions = store.list_versions(ctx, survey_id)
        if not versions:
            return {"error": "not published"}
        version = versions[-1]
        assigned, answers = results_data.RESPONSES[0]
        results_data.add_response(store, ctx, version.id, answers, assigned=assigned)
        count, _newest = ParticipantStore(store).response_watermark(ctx, version.id)
        return {"version": version.number, "responses": count}

    if (RUNTIME_DIST / "index.html").is_file():

        @app.get("/s/{slug}")
        def participant_page(slug: str) -> FileResponse:
            return FileResponse(RUNTIME_DIST / "index.html", headers={"Cache-Control": "no-store"})

        app.mount("/r", StaticFiles(directory=RUNTIME_DIST), name="runtime")
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4318)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="osp-e2e-") as tmp:
        uvicorn.run(build(Path(tmp), args.host), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
