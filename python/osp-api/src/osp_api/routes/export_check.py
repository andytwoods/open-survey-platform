"""Export targets and export checks (task B10). Thin: HTTP <-> ``osp_targets``.

- ``GET /api/meta/targets``: the export targets and their capability tables.
- ``GET /api/surveys/{id}/export-check?target=…``: the diagnostics an export of the draft
  would produce (feature, level, JSON pointer), without producing a file. Reading a draft
  is enough (``survey.get``): no file leaves the server, so viewers may check too.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import cache
from typing import Any, Literal

from fastapi import APIRouter, Response
from osp_targets import (
    TABLES,
    ExportDiagnostic,
    Level,
    build_lss,
    build_qsf,
    build_surveyjs,
    build_xlsform,
)
from pydantic import BaseModel, Field

from .common import Auth, Services, errors

TargetId = Literal["xlsform", "lss", "qsf", "surveyjs"]

_LABELS: dict[str, str] = {
    "xlsform": "XLSForm",
    "lss": "LimeSurvey",
    "qsf": "Qualtrics",
    "surveyjs": "SurveyJS",
}
_DESCRIPTIONS: dict[str, str] = {
    "xlsform": "XLSForm workbook for ODK, Enketo and KoboToolbox (.xlsx).",
    "lss": "LimeSurvey survey structure (.lss).",
    "qsf": "Qualtrics survey file (.qsf).",
    "surveyjs": "SurveyJS survey JSON (.json).",
}


def _diagnostics_only(build: Callable[[Any], tuple[Any, list[ExportDiagnostic]]]):
    return lambda body: build(body)[1]


_CHECKS: dict[str, Callable[[Mapping[str, Any]], list[ExportDiagnostic]]] = {
    "xlsform": _diagnostics_only(build_xlsform),
    "lss": _diagnostics_only(build_lss),
    "qsf": _diagnostics_only(build_qsf),
    "surveyjs": _diagnostics_only(build_surveyjs),
}


class CapabilityRow(BaseModel):
    level: Level
    note: str


class ExportTarget(BaseModel):
    id: TargetId
    label: str
    description: str
    capabilities: dict[str, CapabilityRow] = Field(
        description='Capability table: "<SchemaDef>.<field>[=<value>]" or "$<behaviour>" -> row'
    )


class ExportCheck(BaseModel):
    target: TargetId
    revision: int = Field(description="The draft revision that was checked")
    exportable: bool = Field(description="False when an error diagnostic means no file")
    counts: dict[str, int] = Field(description="Diagnostics per severity")
    diagnostics: list[ExportDiagnostic]


@cache
def _targets() -> list[ExportTarget]:
    return [
        ExportTarget(
            id=tid,  # type: ignore[arg-type]
            label=_LABELS.get(tid, tid),
            description=_DESCRIPTIONS.get(tid, ""),
            capabilities={
                k: CapabilityRow(level=c.level, note=c.note) for k, c in sorted(table.items())
            },
        )
        for tid, table in TABLES.items()
        if tid in _CHECKS
    ]


router = APIRouter()


@router.get(
    "/api/meta/targets", operation_id="listExportTargets", tags=["meta"], responses=errors(401)
)
def targets(_auth: Auth, response: Response) -> list[ExportTarget]:
    response.headers["Cache-Control"] = "private, max-age=300"
    return _targets()


@router.get(
    "/api/surveys/{survey_id}/export-check",
    operation_id="checkExport",
    tags=["surveys"],
    responses=errors(401, 403, 404),
)
def export_check(survey_id: str, target: TargetId, auth: Auth, services: Services) -> ExportCheck:
    view = services.builder.run("survey.get", auth.actor, survey_id=survey_id)
    diagnostics = _CHECKS[target](view.draft.body)
    counts = {s: 0 for s in ("error", "loss", "warning", "info")}
    for d in diagnostics:
        counts[d.severity] = counts.get(d.severity, 0) + 1
    return ExportCheck(
        target=target,
        revision=view.draft.revision,
        exportable=counts["error"] == 0,
        counts=counts,
        diagnostics=diagnostics,
    )
