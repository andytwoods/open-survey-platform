"""Shared plumbing for the builder routes: services, identity, origin checks, errors.

Identity (plan P, planning/pages-split.md): a host owns sign-in. Each builder request asks
the app's :class:`~osp_api.identity.IdentityProvider` who it is; ``None`` is 401. Then the
app admits the identity (principal row, labs created on first sight: ``AppServices.admit``)
and every route checks the resource's lab against the actor's roles as before.

CSRF (D4) is the host's job before it signs or calls in. As defence in depth, every unsafe
request (POST/PUT/PATCH/DELETE) must not be cross-origin (``Origin`` /
``Sec-Fetch-Site``; ``OSP_PUBLIC_ORIGINS`` names the host's public origins, which count as
same-site without enabling CORS, and ``OSP_ALLOWED_ORIGINS`` the cross-origin CORS opt-in;
D14), and one with a body must be ``application/json``.

Participant routes (``participant.py``) use bearer tokens and are not affected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from osp_app import (
    AppError,
    AppServices,
    ConflictError,
    Forbidden,
    InvalidRequest,
    NotFoundError,
    Rejected,
    RevisionConflictError,
    Unauthenticated,
    UpstreamError,
)
from osp_app.auth import Actor, PermissionDenied
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..identity import IdentityProvider, Nobody

UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})


# -- error bodies -------------------------------------------------------------------


class ErrorBody(BaseModel):
    code: str
    message: str


class RevisionConflictBody(ErrorBody):
    currentRevision: int = Field(description="Refetch the draft at this revision and replay.")


class RejectedBody(ErrorBody):
    diagnostics: list[dict[str, Any]]
    failedIndex: int | None = None


class ServiceUnavailable(AppError):
    code = "unavailable"


class UnsupportedMediaType(AppError):
    code = "request.media_type"


STATUS: dict[type[AppError], int] = {
    UnsupportedMediaType: 415,
    ServiceUnavailable: 503,
    Unauthenticated: 401,
    Forbidden: 403,
    NotFoundError: 404,
    ConflictError: 409,
    RevisionConflictError: 409,
    InvalidRequest: 422,
    Rejected: 422,
    UpstreamError: 502,
}

_MODELS: dict[int, type[BaseModel]] = {
    401: ErrorBody,
    403: ErrorBody,
    404: ErrorBody,
    409: ErrorBody,
    415: ErrorBody,
    422: RejectedBody,
    502: ErrorBody,
    503: ErrorBody,
}


def errors(*codes: int, conflict: bool = False) -> dict[int | str, dict[str, Any]]:
    out: dict[int | str, dict[str, Any]] = {c: {"model": _MODELS[c]} for c in codes}
    if conflict:
        out[409] = {"model": RevisionConflictBody, "description": "Stale baseRevision"}
    return out


def _dump(d: Any) -> Any:
    return d.model_dump(mode="json") if isinstance(d, BaseModel) else d


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_req: Request, exc: AppError) -> JSONResponse:
        status = STATUS.get(type(exc), 400)
        body: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if isinstance(exc, RevisionConflictError):
            body["currentRevision"] = exc.current_revision
        if isinstance(exc, Rejected):
            body["diagnostics"] = [_dump(d) for d in exc.diagnostics]
            body["failedIndex"] = exc.failed_index
        return JSONResponse(body, status_code=status)

    @app.exception_handler(PermissionDenied)
    async def _denied(_req: Request, _exc: PermissionDenied) -> JSONResponse:
        return JSONResponse({"code": Forbidden.code, "message": "Not permitted."}, 403)


# -- services ---------------------------------------------------------------------


def get_services(request: Request) -> AppServices:
    services = getattr(request.app.state, "builder_services", None)
    if services is None:
        raise ServiceUnavailable("Builder services are not configured.")
    return services


Services = Annotated[AppServices, Depends(get_services)]


# -- origin and content type (D4: defence in depth behind the host's own CSRF check) ------


def _same_origin(request: Request) -> bool:
    """D4/D14. ``OSP_ALLOWED_ORIGINS`` (the CORS opt-in) are accepted as they are, even
    cross-site. Otherwise the ``Origin`` must be this server's own address (as the request
    says it: scheme + ``Host``) or one of ``OSP_PUBLIC_ORIGINS`` (the host's public
    origins, so a proxy may forward ``Origin`` unchanged), and ``Sec-Fetch-Site`` must not
    say ``cross-site``. No ``Origin`` (a non-browser client, or a proxy that drops it):
    only ``Sec-Fetch-Site`` is checked."""
    site = request.headers.get("sec-fetch-site", "").lower()
    origin = request.headers.get("origin")
    if origin is not None:
        if origin in (getattr(request.app.state, "allowed_origins", ()) or ()):
            return True
        same: set[str] = set(getattr(request.app.state, "public_origins", ()) or ())
        same.add(f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}")
        if origin not in same:
            return False
    return site != "cross-site"


def check_origin(request: Request) -> None:
    if request.method in UNSAFE and not _same_origin(request):
        raise Forbidden("Cross-origin request refused.")


def _has_body(request: Request) -> bool:
    length = request.headers.get("content-length")
    if length is not None:
        return length.strip() not in ("", "0")
    return "transfer-encoding" in request.headers


def require_json(request: Request) -> None:
    """An unsafe request that carries a body must say ``application/json`` (which a
    cross-site HTML form can't send)."""
    if request.method not in UNSAFE or not _has_body(request):
        return
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype != "application/json":
        raise UnsupportedMediaType("Content-Type must be application/json.")


# -- identity (plan P: the host says who this is) -------------------------------------------


@dataclass(frozen=True)
class Authed:
    actor: Actor
    display_name: str | None = None


def get_identity_provider(request: Request) -> IdentityProvider:
    return getattr(request.app.state, "identity", None) or Nobody()


async def authenticated(request: Request, services: Services) -> Authed:
    identity = await get_identity_provider(request).identify(request)
    if identity is None:
        raise Unauthenticated("Sign in first.")
    check_origin(request)
    require_json(request)
    actor = await run_in_threadpool(services.admit, identity)
    return Authed(actor, identity.display_name)


Auth = Annotated[Authed, Depends(authenticated)]
