"""Participant endpoints (``planning/runtime-design.md`` §5). Thin: HTTP <-> SessionService.

Every session call carries the resume token as ``Authorization: Bearer <token>``
(never in a URL, so it stays out of logs and referrers).

No IP address or user agent is stored or logged here (runtime-design §7, review §9 Q8):
the client address is only a key for the in-memory rate limiter. Consent, decline and
withdrawal (semantics.md §11): ``/consent``, ``/decline``, ``/withdraw``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from osp_runtime import (
    ConsentRequired,
    InvalidPayload,
    InvalidToken,
    NotFoundError,
    PayloadTooLarge,
    RateLimited,
    SaveModeForbidden,
    SessionError,
    SessionExpired,
    SessionService,
    SessionSubmitted,
    StaleRevision,
    SubmitMismatch,
    SurveyClosed,
)
from osp_store import AccessDenied, InvalidInput, NotFound
from pydantic import BaseModel, ConfigDict, Field

STATUS: dict[type[SessionError], int] = {
    NotFoundError: 404,
    SurveyClosed: 410,
    InvalidToken: 401,
    SessionExpired: 410,
    SessionSubmitted: 409,
    SaveModeForbidden: 403,
    ConsentRequired: 403,
    StaleRevision: 409,
    SubmitMismatch: 409,
    InvalidPayload: 422,
    PayloadTooLarge: 413,
    RateLimited: 429,
}


# -- models ----------------------------------------------------------------------------


class ErrorBody(BaseModel):
    code: str
    message: str


class StaleBody(ErrorBody):
    revision: int
    snapshot: Any = None


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    urlParams: dict[str, str] = Field(
        default_factory=dict,
        description="URL parameters (e.g. a Prolific id). Not stored in end-only mode.",
    )


class StartResponse(BaseModel):
    sessionId: str
    resumeToken: str = Field(description="Secret. Send as `Authorization: Bearer <token>`.")
    sessionSeed: int = Field(ge=1, le=2**53 - 1)
    assigned: dict[str, Any]
    planUrl: str
    planChecksum: str
    saveMode: Literal["every-page", "end-only"]
    revision: int


class SnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseRevision: int = Field(ge=0)
    snapshot: dict[str, Any]


class SnapshotResponse(BaseModel):
    revision: int
    replay: bool = Field(description="True when this was a retry of the last accepted write.")


class QuotaResponse(BaseModel):
    nodeId: str
    result: Literal["admitted", "full"]
    replay: bool


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    state: Literal["answered", "unanswered", "irrelevant", "not-reached"]
    value: Any = None


class ResponseRecordIn(BaseModel):
    """The engine's ``result(state)``. Extra fields are stored as sent."""

    model_config = ConfigDict(extra="allow")
    sessionId: str
    planChecksum: str
    assigned: dict[str, Any]
    answers: dict[str, AnswerIn]
    orders: dict[str, Any] = Field(default_factory=dict)
    events: list[Any] = Field(default_factory=list)
    engineVersion: str | None = None


class SubmitResponse(BaseModel):
    responseId: str
    submittedAt: datetime
    replay: bool = Field(description="True for a retry with identical data: the original success.")
    late: bool = Field(
        default=False,
        description=(
            "Submitted after the session's quota holds were released or its resume link "
            "expired. Accepted, flagged, and not counted toward quotas."
        ),
    )


class ConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consentVersion: str = Field(
        max_length=80, description="The plan's `consent.version` the participant agreed to."
    )


class ConsentResponse(BaseModel):
    consentVersion: str
    consentedAt: datetime = Field(description="Server time of the (first) agreement.")
    replay: bool


class WithdrawResponse(BaseModel):
    withdrawn: Literal[True]
    responsesDeleted: int


class ResumeResponse(BaseModel):
    sessionId: str
    revision: int
    snapshot: dict[str, Any] | None
    sessionSeed: int
    assigned: dict[str, Any]
    planUrl: str
    planChecksum: str
    saveMode: Literal["every-page", "end-only"]
    submitted: bool


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {c: {"model": StaleBody if c == 409 else ErrorBody} for c in codes}


def plan_url(slug: str, checksum: str) -> str:
    return f"/api/s/{slug}/plan/{checksum}"


# -- wiring ----------------------------------------------------------------------------

bearer = HTTPBearer(auto_error=False, description="The session's resume token.")
Token = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def _token(creds: HTTPAuthorizationCredentials | None) -> str | None:
    return None if creds is None else creds.credentials


def _service(request: Request) -> SessionService:
    service = getattr(request.app.state, "sessions", None)
    if service is None:
        raise SessionError("participant sessions are not configured on this server")
    return service


Svc = Annotated[SessionService, Depends(_service)]


def install(app: FastAPI, service: SessionService | None) -> None:
    app.state.sessions = service

    @app.exception_handler(SessionError)
    async def _session_error(_req: Request, exc: SessionError) -> JSONResponse:
        status = STATUS.get(type(exc), 503)
        body: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if isinstance(exc, StaleRevision):
            body |= {"revision": exc.revision, "snapshot": exc.snapshot}
        return JSONResponse(body, status_code=status)

    @app.exception_handler(NotFound)
    @app.exception_handler(AccessDenied)
    async def _not_found(_req: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse({"code": "not_found", "message": "not found"}, status_code=404)

    @app.exception_handler(InvalidInput)
    async def _invalid(_req: Request, exc: InvalidInput) -> JSONResponse:
        return JSONResponse({"code": "payload.invalid", "message": str(exc)}, status_code=422)

    r = APIRouter(prefix="/api", tags=["participant"])

    @r.post(
        "/s/{slug}/sessions",
        operation_id="startSession",
        status_code=201,
        responses=_errors(404, 410, 422, 429),
    )
    def start_session(
        slug: str, request: Request, s: Svc, body: StartRequest | None = None
    ) -> StartResponse:
        client = request.client.host if request.client else None  # memory only, never stored
        st = s.start(slug, (body or StartRequest()).urlParams, client_key=client)
        return StartResponse(
            sessionId=st.session_id,
            resumeToken=st.resume_token,
            sessionSeed=st.session_seed,
            assigned=st.assigned,
            planUrl=plan_url(st.slug, st.plan_checksum),
            planChecksum=st.plan_checksum,
            saveMode=st.save_mode,
            revision=st.revision,
        )

    @r.get("/s/{slug}/plan/{checksum}", operation_id="getPlan", responses=_errors(404))
    def get_plan(slug: str, checksum: str, s: Svc, response: Response) -> dict[str, Any]:
        plan = s.plan(slug, checksum)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return plan

    @r.put(
        "/sessions/{session_id}/snapshot",
        operation_id="saveSnapshot",
        responses=_errors(401, 403, 409, 410, 413, 422),
    )
    def save_snapshot(
        session_id: str, body: SnapshotRequest, s: Svc, token: Token
    ) -> SnapshotResponse:
        ack = s.save_snapshot(session_id, _token(token), body.baseRevision, body.snapshot)
        return SnapshotResponse(revision=ack.revision, replay=ack.replay)

    @r.post(
        "/sessions/{session_id}/quota/{node_id}",
        operation_id="checkQuota",
        responses=_errors(401, 404, 409, 410),
    )
    def check_quota(session_id: str, node_id: str, s: Svc, token: Token) -> QuotaResponse:
        q = s.check_quota(session_id, _token(token), node_id)
        return QuotaResponse(nodeId=q.node_id, result=q.result, replay=q.replay)

    @r.post(
        "/sessions/{session_id}/submit",
        operation_id="submitSession",
        responses=_errors(401, 409, 410, 413, 422),
    )
    def submit(session_id: str, body: ResponseRecordIn, s: Svc, token: Token) -> SubmitResponse:
        record = body.model_dump(mode="json")
        ack = s.submit(session_id, _token(token), record)
        return SubmitResponse(
            responseId=ack.response_id,
            submittedAt=ack.submitted_at,
            replay=ack.replay,
            late=ack.late,
        )

    @r.post(
        "/sessions/{session_id}/consent",
        operation_id="giveConsent",
        responses=_errors(401, 404, 409, 410, 422),
    )
    def consent(session_id: str, body: ConsentRequest, s: Svc, token: Token) -> ConsentResponse:
        """The participant agreed (semantics.md §11). Until then the server takes no
        snapshot, quota check or submit for a survey with a consent page."""
        ack = s.consent(session_id, _token(token), body.consentVersion)
        return ConsentResponse(
            consentVersion=ack.version, consentedAt=ack.consented_at, replay=ack.replay
        )

    @r.post(
        "/sessions/{session_id}/decline",
        operation_id="declineConsent",
        status_code=204,
        responses=_errors(401, 404, 422),
    )
    def decline(session_id: str, s: Svc, token: Token) -> None:
        """The participant declined: the session is deleted. Nothing is kept but an
        anonymous count, and only if the survey asks for one."""
        s.decline(session_id, _token(token))

    @r.post(
        "/sessions/{session_id}/withdraw",
        operation_id="withdrawSession",
        responses=_errors(401, 404),
    )
    def withdraw(session_id: str, s: Svc, token: Token) -> WithdrawResponse:
        """The participant withdraws (before or after submitting): their response and
        session are deleted, and an audit entry without answer data is written. The resume
        token stops working."""
        n = s.withdraw(session_id, _token(token))
        return WithdrawResponse(withdrawn=True, responsesDeleted=n)

    @r.get("/sessions/resume", operation_id="resumeSession", responses=_errors(401, 410, 429))
    def resume(request: Request, s: Svc, token: Token) -> ResumeResponse:
        client = request.client.host if request.client else None
        st = s.resume(_token(token), client_key=client)
        return ResumeResponse(
            sessionId=st.session_id,
            revision=st.revision,
            snapshot=st.snapshot,
            sessionSeed=st.session_seed,
            assigned=st.assigned,
            planUrl=plan_url(st.slug, st.plan_checksum),
            planChecksum=st.plan_checksum,
            saveMode=st.save_mode,
            submitted=st.submitted,
        )

    app.include_router(r)
