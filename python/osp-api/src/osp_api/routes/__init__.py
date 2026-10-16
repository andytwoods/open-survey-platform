"""Builder routes (task C10): auth, surveys, ops, meta. ``install`` wires them in."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import FastAPI
from osp_app import AppServices
from osp_ops import openapi_components

from . import auth, data_export, expressions, meta, ops, surveys
from .common import install_error_handlers


def _with_op_schemas(app: FastAPI) -> None:
    """Add each op's params schema (``<OpId>Params``) to the OpenAPI components, so the
    TS client gets typed op params. Schemas FastAPI already emits win."""
    base = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        spec = base()
        schemas = spec.setdefault("components", {}).setdefault("schemas", {})
        for name, schema in openapi_components().items():
            schemas.setdefault(name, schema)
        app.openapi_schema = spec
        return spec

    app.openapi = openapi  # type: ignore[method-assign]


def install(
    app: FastAPI, services: AppServices | None, allowed_origins: Iterable[str] = ()
) -> None:
    """``services`` backs the builder routes; without it they answer 503."""
    app.state.builder_services = services
    app.state.allowed_origins = tuple(allowed_origins)
    install_error_handlers(app)
    for module in (auth, surveys, data_export, ops, meta, expressions):
        app.include_router(module.router)
    _with_op_schemas(app)
