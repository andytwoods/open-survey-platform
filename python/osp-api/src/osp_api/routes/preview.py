"""Preview plan (task B11). Thin: HTTP <-> the ``survey.preview_plan`` app command.

``POST /api/surveys/{id}/preview-plan`` (``survey.edit``: owner, editor; viewers 403, other
labs 404) compiles the current draft into a runtime plan with ``seedVersion: "draft"``
(R1-1) and publishes nothing. A draft with errors answers 200 with ``plan: null`` and the
diagnostics, so the preview can say what to fix.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from osp_spec import Diagnostic
from pydantic import BaseModel, Field

from .common import Auth, Services, errors

router = APIRouter(prefix="/api/surveys", tags=["surveys"])


class PreviewPlanResponse(BaseModel):
    surveyId: str
    revision: int = Field(description="The draft revision the plan was compiled from")
    plan: dict[str, Any] | None = Field(
        description="The runtime plan (osp-runtime-plan/1, seedVersion 'draft'); null when "
        "the draft has errors"
    )
    conditions: dict[str, str] = Field(
        description="Each condition in the plan as text, by engine site "
        "(items.<id>.showIf, pages.<id>.showIf, flow.<id>.if, quotas.<id>.when, "
        "variables.<id>.expr, items.<id>.constraint)"
    )
    diagnostics: list[Diagnostic]


@router.post(
    "/{survey_id}/preview-plan",
    operation_id="previewPlan",
    response_model=PreviewPlanResponse,
    responses=errors(401, 403, 404),
)
def preview_plan(survey_id: str, auth: Auth, services: Services) -> dict[str, Any]:
    return services.builder.run("survey.preview_plan", auth.actor, survey_id=survey_id)
