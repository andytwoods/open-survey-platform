"""Researcher sign-in: password, then TOTP if enrolled. Thin: HTTP <-> AuthService.

Failures are one uniform 401 (``GENERIC_FAILURE``): no hint whether the email exists,
the password or code was wrong, or the account is locked.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from osp_app import InvalidRequest, Unauthenticated
from osp_app.auth import GENERIC_FAILURE, AuthError, LoginOk, MfaRequired
from pydantic import BaseModel, ConfigDict, Field

from .common import (
    MFA_COOKIE,
    Auth,
    Services,
    check_origin,
    clear_session_cookies,
    csrf_token_for,
    errors,
    require_json,
    set_session_cookies,
)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)


class TotpLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=64)
    recovery: bool = Field(False, description="`code` is a single-use recovery code")


class TotpCode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=64)


class MembershipOut(BaseModel):
    tenantId: str
    role: str


class Me(BaseModel):
    userId: str
    email: str
    totpEnrolled: bool
    memberships: list[MembershipOut]
    csrfToken: str = Field(description="Send as `X-CSRF-Token` on every unsafe request.")


class LoginResponse(BaseModel):
    status: Literal["ok", "mfa_required"]
    me: Me | None = None


class TotpEnrolmentOut(BaseModel):
    secret: str
    provisioningUri: str


class TotpConfirmed(BaseModel):
    recoveryCodes: list[str] = Field(description="Shown once. Stored hashed.")
    csrfToken: str


def _me(services: Services, user_id: str, token: str) -> Me:
    user = services.auth.users.get(user_id)
    if user is None:
        raise Unauthenticated("Sign in first.")
    return Me(
        userId=user.id,
        email=user.email,
        totpEnrolled=user.totp_enrolled,
        memberships=[
            MembershipOut(tenantId=m.tenant_id, role=str(m.role))
            for m in services.auth.memberships.memberships_for_user(user.id)
        ],
        csrfToken=csrf_token_for(token),
    )


def _pre_session(request: Request) -> None:
    check_origin(request)
    require_json(request)


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post(
    "/login",
    operation_id="login",
    dependencies=[Depends(_pre_session)],
    responses=errors(401, 403, 415),
)
def login(body: LoginRequest, services: Services, response: Response) -> LoginResponse:
    result = services.auth.login(body.email, body.password)
    if isinstance(result, LoginOk):
        set_session_cookies(response, result.token)
        return LoginResponse(status="ok", me=_me(services, result.user_id, result.token))
    if isinstance(result, MfaRequired):
        response.set_cookie(
            MFA_COOKIE,
            result.challenge,
            httponly=True,
            secure=True,
            samesite="strict",
            path="/",
            max_age=int(services.auth.sessions.config.mfa_pending_lifetime.total_seconds()),
        )
        return LoginResponse(status="mfa_required")
    raise Unauthenticated(GENERIC_FAILURE)


@router.post(
    "/login/totp",
    operation_id="loginTotp",
    dependencies=[Depends(_pre_session)],
    responses=errors(401, 403, 415),
)
def login_totp(
    body: TotpLoginRequest, request: Request, services: Services, response: Response
) -> LoginResponse:
    challenge = request.cookies.get(MFA_COOKIE)
    step = services.auth.login_recovery if body.recovery else services.auth.login_totp
    result = step(challenge, body.code)
    if not isinstance(result, LoginOk):
        raise Unauthenticated(GENERIC_FAILURE)
    response.delete_cookie(MFA_COOKIE, path="/", secure=True, httponly=True, samesite="strict")
    set_session_cookies(response, result.token)
    return LoginResponse(status="ok", me=_me(services, result.user_id, result.token))


@router.post("/logout", operation_id="logout", status_code=204, responses=errors(401, 403))
def logout(auth: Auth, services: Services, response: Response) -> None:
    services.auth.logout(auth.token)
    clear_session_cookies(response)


@router.get("/me", operation_id="getMe", responses=errors(401))
def me(auth: Auth, services: Services) -> Me:
    return _me(services, auth.actor.user_id, auth.token)


@router.post("/totp/enrol", operation_id="startTotpEnrolment", responses=errors(401, 403, 422))
def totp_enrol(auth: Auth, services: Services) -> TotpEnrolmentOut:
    try:
        e = services.auth.start_totp_enrolment(auth.token)
    except AuthError as exc:
        raise InvalidRequest(str(exc)) from exc
    return TotpEnrolmentOut(secret=e.secret, provisioningUri=e.provisioning_uri)


@router.post("/totp/verify", operation_id="confirmTotpEnrolment", responses=errors(401, 403, 422))
def totp_verify(
    body: TotpCode, auth: Auth, services: Services, response: Response
) -> TotpConfirmed:
    try:
        token, codes = services.auth.confirm_totp_enrolment(auth.token, body.code)
    except AuthError as exc:
        raise InvalidRequest(str(exc)) from exc
    csrf = set_session_cookies(response, token)  # rotated: the old token stops working
    return TotpConfirmed(recoveryCodes=codes, csrfToken=csrf)
