"""Shared plumbing for the builder routes: services, cookie auth, CSRF, error mapping.

Cookie auth (builder UI):
- ``__Host-osp_session``: the opaque session token. HttpOnly, Secure, SameSite=Lax,
  Path=/ (the ``__Host-`` prefix makes the browser refuse it without Secure/Path=/ and
  from any subdomain).
- ``__Host-osp_csrf``: the CSRF token, readable by the page. It is derived from the
  session token (SHA-256 with a label), so a cookie planted by another origin can't
  match a session it doesn't know.
- Every unsafe request (POST/PUT/PATCH/DELETE) on a cookie-authenticated route must
  send ``X-CSRF-Token`` equal to the derived token, and must not be cross-origin
  (``Origin`` / ``Sec-Fetch-Site``). Pre-session routes (login, TOTP step) get the
  origin check and must be ``application/json`` (which a cross-site form can't send).

Participant routes (``participant.py``) use bearer tokens and are not affected.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request, Response
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
)
from osp_app.auth import Actor, PermissionDenied
from pydantic import BaseModel, Field

SESSION_COOKIE = "__Host-osp_session"
CSRF_COOKIE = "__Host-osp_csrf"
MFA_COOKIE = "__Host-osp_mfa"
CSRF_HEADER = "X-CSRF-Token"
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
}

_MODELS: dict[int, type[BaseModel]] = {
    401: ErrorBody,
    403: ErrorBody,
    404: ErrorBody,
    409: ErrorBody,
    415: ErrorBody,
    422: RejectedBody,
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


# -- CSRF and origin -----------------------------------------------------------------


def csrf_token_for(session_token: str) -> str:
    digest = hashlib.sha256(b"osp-csrf\x00" + session_token.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _same_origin(request: Request) -> bool:
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        return False
    origin = request.headers.get("origin")
    if origin is None:
        return True  # non-browser client, or a same-origin GET-style request
    allowed: set[str] = set(getattr(request.app.state, "allowed_origins", ()) or ())
    allowed.add(f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}")
    return origin in allowed


def check_origin(request: Request) -> None:
    if request.method in UNSAFE and not _same_origin(request):
        raise Forbidden("Cross-origin request refused.")


def require_json(request: Request) -> None:
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype != "application/json":
        raise UnsupportedMediaType("Content-Type must be application/json.")


def check_csrf(request: Request, session_token: str) -> None:
    if request.method not in UNSAFE:
        return
    check_origin(request)
    sent = request.headers.get(CSRF_HEADER, "")
    if not sent or not hmac.compare_digest(sent, csrf_token_for(session_token)):
        raise Forbidden("Missing or invalid CSRF token.")


# -- authentication ------------------------------------------------------------------


@dataclass(frozen=True)
class Authed:
    actor: Actor
    token: str


def authenticated(request: Request, services: Services) -> Authed:
    token = request.cookies.get(SESSION_COOKIE)
    actor = services.auth.actor(token) if token else None
    if actor is None or token is None:
        raise Unauthenticated("Sign in first.")
    check_csrf(request, token)
    return Authed(actor, token)


Auth = Annotated[Authed, Depends(authenticated)]


def set_session_cookies(response: Response, token: str) -> str:
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=True, samesite="lax", path="/")
    csrf = csrf_token_for(token)
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, secure=True, samesite="lax", path="/")
    return csrf


def clear_session_cookies(response: Response) -> None:
    for name in (SESSION_COOKIE, CSRF_COOKIE, MFA_COOKIE):
        response.delete_cookie(name, path="/", secure=True, httponly=True, samesite="lax")
