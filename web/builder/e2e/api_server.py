"""Throwaway `osp-api` for the builder's end-to-end tests (`make web-e2e`).

A fresh SQLite database in a temp directory, one lab and one researcher (no TOTP), served
by uvicorn. Test-only: never import this, never point it at real data.

    uv run --locked --with uvicorn python web/builder/e2e/api_server.py --port 4318

Env: OSP_E2E_EMAIL / OSP_E2E_PASSWORD override the account.

If the participant app is built (``web/runtime/dist``), it is served too: ``/s/{slug}`` and
``/r/*``, as in production, so a test can publish and then open the participant link (the
builder's preview server proxies those paths here).
"""

from __future__ import annotations

import argparse
import base64
import os
import secrets
import tempfile
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from osp_api.app import create_app
from osp_app import build_services
from osp_store import Keyring, Store, SystemContext, create_engine, migrate

# This server serves the participant app at /s/{slug}, so publish should link there.
os.environ.setdefault("OSP_PARTICIPANT_URL_TEMPLATE", "/s/{slug}")

EMAIL = os.environ.get("OSP_E2E_EMAIL", "researcher@lab.example")
PASSWORD = os.environ.get("OSP_E2E_PASSWORD", "plover tundra kettle 4417 orbit")
RUNTIME_DIST = Path(__file__).resolve().parents[2] / "runtime" / "dist"


def build(db_dir: Path) -> FastAPI:
    engine = create_engine(f"sqlite:///{db_dir / 'e2e.db'}")
    migrate(engine)
    key = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    store = Store(engine, Keyring({"k1": key}, active="k1"))
    services = build_services(store)
    tenant = store.create_tenant(SystemContext("system:e2e"), "E2E lab")
    services.create_account(tenant.id, EMAIL, PASSWORD, "owner")
    app = create_app(builder=services)
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
        uvicorn.run(build(Path(tmp)), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
