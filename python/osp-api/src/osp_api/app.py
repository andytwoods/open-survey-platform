"""The HTTP shell (L6). Its OpenAPI schema is the contract: `make contract` writes it to
/contract/openapi.json and generates the TS client from it.

Keep handlers thin: they translate HTTP to `osp-app` calls and nothing more.
Give every route an explicit, stable `operation_id`; the TS client is keyed by path,
but ids keep the contract diff readable.
"""

from importlib.metadata import version
from typing import Literal

from fastapi import FastAPI
from osp_runtime import SessionService
from pydantic import BaseModel

from . import participant

API_TITLE = "Open Survey Platform API"


class Health(BaseModel):
    status: Literal["ok"]


class VersionInfo(BaseModel):
    name: str
    version: str


def create_app(sessions: SessionService | None = None) -> FastAPI:
    """``sessions`` backs the participant endpoints; without it they answer 503."""
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
    return app


app = create_app()
