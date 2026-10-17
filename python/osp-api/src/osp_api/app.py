"""The HTTP shell (L6). Its OpenAPI schema is the contract: `make contract` writes it to
/contract/openapi.json and generates the TS client from it.

Keep handlers thin: they translate HTTP to `osp-app` calls and nothing more.
Give every route an explicit, stable `operation_id`; the TS client is keyed by path,
but ids keep the contract diff readable.
"""

from collections.abc import Sequence
from importlib.metadata import version
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from osp_app import AppServices
from osp_runtime import SessionService
from pydantic import BaseModel

from . import participant, routes
from .identity import IdentityProvider

API_TITLE = "Open Survey Platform API"


class Health(BaseModel):
    status: Literal["ok"]


class VersionInfo(BaseModel):
    name: str
    version: str


def create_app(
    sessions: SessionService | None = None,
    builder: AppServices | None = None,
    *,
    identity: IdentityProvider | None = None,
    allowed_origins: Sequence[str] = (),
) -> FastAPI:
    """``sessions`` backs the participant endpoints and ``builder`` the builder ones
    (surveys, ops, meta, me); without them they answer 503. Given only ``builder``,
    the participant endpoints use its ``sessions``, so a publish is servable at once.

    ``identity`` says who a builder request is (``osp_api.identity``: TrustedHeaders,
    InProcess, Dev); without one every builder request is 401. ``allowed_origins``
    (exact origins, D11) may make unsafe requests cross-origin, with credentials."""
    if sessions is None and builder is not None:
        sessions = builder.sessions
    pkg_version = version("osp-api")
    app = FastAPI(
        title=API_TITLE,
        version=pkg_version,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )

    @app.get("/api/health", operation_id="getHealth", tags=["meta"])
    def health() -> Health:
        return Health(status="ok")

    @app.get("/api/version", operation_id="getVersion", tags=["meta"])
    def get_version() -> VersionInfo:
        return VersionInfo(name="osp-api", version=pkg_version)

    participant.install(app, sessions)
    routes.install(app, builder, allowed_origins, identity)
    if allowed_origins:
        if any(o == "*" or not o.startswith(("https://", "http://")) for o in allowed_origins):
            raise ValueError("allowed_origins must be exact http(s) origins, no wildcard")
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(allowed_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["*"],  # the host's own CSRF header, whatever it is called,
        )
    return app


app = create_app()
