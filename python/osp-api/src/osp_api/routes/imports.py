"""Survey import (task IM1): preview a Qualtrics / LimeSurvey / SurveyJS file, or create a
draft from it. Thin: HTTP <-> ``survey.import_preview`` / ``survey.import``.

Registered before the ``/api/surveys/{survey_id}`` routes, so ``import`` is never read as
a survey id.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from osp_app.import_survey import MAX_BYTES, ImportPreview
from osp_spec import Diagnostic
from pydantic import BaseModel, ConfigDict, Field

from .common import Auth, Services, errors
from .surveys import SurveyDetail, detail

ImportFormat = Literal["qsf", "lss", "surveyjs"]


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=255, description="Used to guess the format")
    content: str = Field(
        max_length=MAX_BYTES,
        description="The file's text (.qsf and SurveyJS are JSON, .lss is XML; UTF-8)",
    )
    format: ImportFormat | None = Field(
        None, description="Override the format guessed from the content and file name"
    )


class CreateFromImportRequest(ImportRequest):
    title: str | None = Field(
        None, min_length=1, max_length=500, description="Replaces the imported title"
    )
    tenantId: str | None = Field(None, description="Needed only if you belong to several labs")


class ImportDiagnosticOut(BaseModel):
    format: ImportFormat
    severity: Literal["info", "warning", "loss", "error"]
    code: str
    feature: str
    pointer: str = Field(description="Where in the source file")
    message: str
    target: str | None = Field(None, description="Where in the imported survey, if anywhere")


class ImportSummaryOut(BaseModel):
    title: str
    languages: list[str]
    blocks: int
    pages: int
    questions: int
    byType: dict[str, int]
    choiceLists: int
    variables: int
    quotas: int
    flowNodes: int
    conditions: int
    losses: int
    warnings: int
    infos: int


class ImportPreviewResponse(BaseModel):
    format: ImportFormat
    ok: bool = Field(description="False: nothing can be imported (see the error diagnostics)")
    title: str
    summary: ImportSummaryOut | None
    diagnostics: list[ImportDiagnosticOut] = Field(
        description="What carried over with a note, what will behave differently, what was lost"
    )
    validation: list[Diagnostic] = Field(
        description="The validator's diagnostics for the survey as it would be created"
    )


class ImportSurveyResponse(BaseModel):
    survey: SurveyDetail
    preview: ImportPreviewResponse = Field(description="The import report for this draft")


def _preview_out(p: ImportPreview) -> ImportPreviewResponse:
    return ImportPreviewResponse(
        format=p.format,
        ok=p.ok,
        title=p.title,
        summary=None if p.summary is None else ImportSummaryOut(**p.summary.model_dump()),
        diagnostics=[ImportDiagnosticOut(**d.model_dump()) for d in p.diagnostics],
        validation=p.validation,
    )


router = APIRouter(prefix="/api/surveys/import", tags=["surveys"])


@router.post(
    "/preview",
    operation_id="previewSurveyImport",
    responses=errors(401, 403, 422),
)
def preview_import(body: ImportRequest, auth: Auth, services: Services) -> ImportPreviewResponse:
    p = services.builder.run(
        "survey.import_preview",
        auth.actor,
        filename=body.filename,
        content=body.content,
        format=body.format,
    )
    return _preview_out(p)


@router.post(
    "",
    operation_id="importSurvey",
    status_code=201,
    responses=errors(401, 403, 422),
)
def import_survey(
    body: CreateFromImportRequest, auth: Auth, services: Services
) -> ImportSurveyResponse:
    params: dict[str, Any] = {
        "filename": body.filename,
        "content": body.content,
        "format": body.format,
        "title": body.title,
        "tenant_id": body.tenantId,
    }
    outcome = services.builder.run("survey.import", auth.actor, **params)
    return ImportSurveyResponse(survey=detail(outcome.view), preview=_preview_out(outcome.preview))
