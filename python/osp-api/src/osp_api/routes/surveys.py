"""Survey CRUD, history, publish and XLSForm export. Thin: HTTP <-> osp_app.Builder.

Edits to a draft go through ``/ops`` (``ops.py``), never through a PUT of the body.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Response
from osp_app import SurveyView
from osp_spec import Diagnostic, validate
from osp_store import Survey
from pydantic import BaseModel, ConfigDict, Field

from ..participant import participant_url, plan_url
from .common import Auth, Services, errors

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
LSS = "application/xml"
JSON_FILE = "application/json"


class SurveySummary(BaseModel):
    id: str
    tenantId: str
    title: str
    createdBy: str
    createdAt: datetime
    closedAt: datetime | None = None
    publicSlug: str | None = Field(None, description="Participant link id: /s/{publicSlug}")


class SurveyDetail(SurveySummary):
    revision: int
    survey: dict[str, Any] = Field(description="The draft (osp-survey JSON)")
    updatedAt: datetime
    updatedBy: str
    diagnostics: list[Diagnostic] = Field(
        description="The validator's diagnostics for the draft as it is now"
    )
    publishedVersions: int = Field(
        0, description="How many versions have been published (0: never published)"
    )


class CreateSurveyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    survey: dict[str, Any] | None = Field(
        None, description="Initial osp-survey JSON; omitted: a one-page skeleton"
    )
    tenantId: str | None = Field(None, description="Needed only if you belong to several labs")


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseRevision: int | None = Field(
        None, ge=0, description="If given, publish only if the draft is still at it"
    )
    saveMode: Literal["every-page", "end-only"] | None = Field(
        None,
        description="Participant save mode (runtime-design section 5.0); "
        "default: the survey's settings.saveMode",
    )


class PublishResponse(BaseModel):
    versionId: str
    number: int
    checksum: str
    publishedAt: datetime
    revision: int
    diagnostics: list[Diagnostic]
    slug: str = Field(description="The survey's public slug: participants start at /s/{slug}")
    planChecksum: str
    planUrl: str = Field(description="Where the immutable runtime plan is served")
    participantUrl: str = Field(
        description="The link participants open (absolute, or relative to the builder's origin)"
    )
    saveMode: Literal["every-page", "end-only"]


class HistoryItem(BaseModel):
    transactionId: str
    kind: str = Field(description="edit | undo | redo")
    revision: int
    ops: list[str]
    actor: str
    at: datetime


def summary(s: Survey) -> SurveySummary:
    return SurveySummary(
        id=s.id,
        tenantId=s.tenant_id,
        title=s.title,
        createdBy=s.created_by,
        createdAt=s.created_at,
        closedAt=s.closed_at,
        publicSlug=s.public_slug,
    )


def detail(v: SurveyView) -> SurveyDetail:
    s, d = v.survey, v.draft
    return SurveyDetail(
        **summary(s).model_dump(),
        revision=d.revision,
        survey=d.body,
        updatedAt=d.updated_at,
        updatedBy=d.updated_by,
        diagnostics=validate(d.body),
        publishedVersions=v.published_versions,
    )


router = APIRouter(prefix="/api/surveys", tags=["surveys"])


@router.get("", operation_id="listSurveys", responses=errors(401))
def list_surveys(auth: Auth, services: Services) -> list[SurveySummary]:
    return [summary(s) for s in services.builder.run("survey.list", auth.actor)]


@router.post("", operation_id="createSurvey", status_code=201, responses=errors(401, 403, 422))
def create_survey(body: CreateSurveyRequest, auth: Auth, services: Services) -> SurveyDetail:
    view = services.builder.run(
        "survey.create",
        auth.actor,
        title=body.title,
        survey=body.survey,
        tenant_id=body.tenantId,
    )
    return detail(view)


@router.get("/{survey_id}", operation_id="getSurvey", responses=errors(401, 403, 404))
def get_survey(survey_id: str, auth: Auth, services: Services) -> SurveyDetail:
    return detail(services.builder.run("survey.get", auth.actor, survey_id=survey_id))


@router.delete(
    "/{survey_id}",
    operation_id="deleteSurvey",
    status_code=204,
    responses=errors(401, 403, 404, 409),
)
def delete_survey(survey_id: str, auth: Auth, services: Services) -> None:
    services.builder.run("survey.delete", auth.actor, survey_id=survey_id)


@router.get(
    "/{survey_id}/history", operation_id="getSurveyHistory", responses=errors(401, 403, 404)
)
def history(survey_id: str, auth: Auth, services: Services) -> list[HistoryItem]:
    return [
        HistoryItem(
            transactionId=h.transaction_id,
            kind=h.kind,
            revision=h.revision,
            ops=h.ops,
            actor=h.actor,
            at=h.at,
        )
        for h in services.builder.run("survey.history", auth.actor, survey_id=survey_id)
    ]


@router.post(
    "/{survey_id}/publish",
    operation_id="publishSurvey",
    status_code=201,
    responses=errors(401, 403, 404, 422, conflict=True),
)
def publish(
    survey_id: str, auth: Auth, services: Services, body: PublishRequest | None = None
) -> PublishResponse:
    r = services.builder.run(
        "survey.publish",
        auth.actor,
        survey_id=survey_id,
        base_revision=None if body is None else body.baseRevision,
        save_mode=None if body is None else body.saveMode,
    )
    return PublishResponse(
        versionId=r.version_id,
        number=r.number,
        checksum=r.checksum,
        publishedAt=r.published_at,
        revision=r.revision,
        diagnostics=r.diagnostics,
        slug=r.slug,
        planChecksum=r.plan_checksum,
        planUrl=plan_url(r.slug, r.plan_checksum),
        participantUrl=participant_url(r.slug),
        saveMode=r.runtime_config["saveMode"],
    )


@router.get(
    "/{survey_id}/export/xlsform",
    operation_id="exportXlsform",
    response_class=Response,
    responses={
        200: {
            "content": {XLSX: {"schema": {"type": "string", "format": "binary"}}},
            "description": "XLSForm workbook",
        },
        **errors(401, 403, 404, 422),
    },
)
def export_xlsform(survey_id: str, auth: Auth, services: Services) -> Response:
    r = services.builder.run("survey.export_xlsform", auth.actor, survey_id=survey_id)
    return Response(
        r.content,
        media_type=XLSX,
        headers={
            "Content-Disposition": f'attachment; filename="{r.filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/{survey_id}/export/lss",
    operation_id="exportLss",
    response_class=Response,
    responses={
        200: {
            "content": {LSS: {"schema": {"type": "string", "format": "binary"}}},
            "description": "LimeSurvey survey structure (.lss)",
        },
        **errors(401, 403, 404, 422),
    },
)
def export_lss(survey_id: str, auth: Auth, services: Services) -> Response:
    r = services.builder.run("survey.export_lss", auth.actor, survey_id=survey_id)
    return Response(
        r.content,
        media_type=LSS,
        headers={
            "Content-Disposition": f'attachment; filename="{r.filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/{survey_id}/export/qsf",
    operation_id="exportQsf",
    response_class=Response,
    responses={
        200: {
            "content": {JSON_FILE: {"schema": {"type": "string", "format": "binary"}}},
            "description": "Qualtrics survey file (.qsf)",
        },
        **errors(401, 403, 404, 422),
    },
)
def export_qsf(survey_id: str, auth: Auth, services: Services) -> Response:
    r = services.builder.run("survey.export_qsf", auth.actor, survey_id=survey_id)
    return Response(
        r.content,
        media_type=JSON_FILE,
        headers={
            "Content-Disposition": f'attachment; filename="{r.filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/{survey_id}/export/surveyjs",
    operation_id="exportSurveyjs",
    response_class=Response,
    responses={
        200: {
            "content": {JSON_FILE: {"schema": {"type": "string", "format": "binary"}}},
            "description": "SurveyJS survey JSON",
        },
        **errors(401, 403, 404, 422),
    },
)
def export_surveyjs(survey_id: str, auth: Auth, services: Services) -> Response:
    r = services.builder.run("survey.export_surveyjs", auth.actor, survey_id=survey_id)
    return Response(
        r.content,
        media_type=JSON_FILE,
        headers={
            "Content-Disposition": f'attachment; filename="{r.filename}"',
            "Cache-Control": "no-store",
        },
    )
