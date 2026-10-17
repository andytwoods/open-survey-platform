"""Builder routes (task C10): identity, surveys, ops, meta. ``install`` wires them in."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import FastAPI
from osp_app import AppServices
from osp_ops import openapi_components

from ..identity import IdentityProvider
from . import (
    data_export,
    export_check,
    expressions,
    me,
    meta,
    ops,
    preview,
    repro,
    simulate,
    surveys,
    themes,
)
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
    app: FastAPI,
    services: AppServices | None,
    allowed_origins: Iterable[str] = (),
    identity: IdentityProvider | None = None,
) -> None:
    """``services`` backs the builder routes; without it they answer 503. ``identity``
    says who each request is; without it every builder request is 401."""
    app.state.builder_services = services
    app.state.identity = identity
    app.state.allowed_origins = tuple(allowed_origins)
    install_error_handlers(app)
    for module in (
        me,
        surveys,
        data_export,
        repro,
        export_check,
        simulate,
        preview,
        ops,
        meta,
        expressions,
        themes,
    ):
        app.include_router(module.router)
    _with_op_schemas(app)
