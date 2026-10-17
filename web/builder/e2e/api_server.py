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
import os
import secrets
import tempfile
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from osp_api.app import create_app
from osp_api.identity import Dev, IdentityProvider
from osp_app import build_services
from osp_store import Keyring, Store, create_engine, migrate

# This server serves the participant app at /s/{slug}, so publish should link there.
os.environ.setdefault("OSP_PARTICIPANT_URL_TEMPLATE", "/s/{slug}")

RUNTIME_DIST = Path(__file__).resolve().parents[2] / "runtime" / "dist"


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
    app = create_app(builder=services, identity=identity_provider(host))
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
