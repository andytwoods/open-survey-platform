"""The edit flow (builder-design §4): ops as one transaction, undo, redo.

POST /api/surveys/{id}/ops   {ops: [{op, params}], baseRevision, transactionId?}
  -> 200 {revision, patch, diagnostics, transactionId}
  -> 409 {currentRevision}  stale baseRevision: refetch and replay
  -> 422 {diagnostics, failedIndex}  rejected; nothing applied
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from osp_app import EditResult
from osp_ops import Invocation
from osp_spec import Diagnostic
from pydantic import BaseModel, ConfigDict, Field

from .common import Auth, Services, errors


class OpsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ops: list[Invocation] = Field(max_length=1000, description="Applied all or nothing")
    baseRevision: int = Field(ge=0)
    transactionId: str | None = Field(
        None,
        pattern=r"^[A-Za-z0-9_-]{1,36}$",
        description="Client-chosen id; a retry with the same id is not applied twice",
    )


class ReverseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transactionId: str = Field(min_length=1, max_length=36)
    baseRevision: int = Field(ge=0)


class EditResponse(BaseModel):
    revision: int
    patch: list[dict[str, Any]] = Field(description="RFC 6902, from baseRevision to revision")
    diagnostics: list[Diagnostic]
    transactionId: str | None = Field(
        description="Undo handle; null when nothing changed (nothing logged)"
    )
    replayed: bool = False


def _out(r: EditResult) -> EditResponse:
    return EditResponse(
        revision=r.revision,
        patch=r.patch,
        diagnostics=r.diagnostics,
        transactionId=r.transaction_id,
        replayed=r.replayed,
    )


router = APIRouter(prefix="/api/surveys", tags=["ops"])

_ERR = errors(401, 403, 404, 422, conflict=True)


@router.post("/{survey_id}/ops", operation_id="applyOps", responses=_ERR)
def apply_ops(survey_id: str, body: OpsRequest, auth: Auth, services: Services) -> EditResponse:
    return _out(
        services.builder.run(
            "survey.apply_ops",
            auth.actor,
            survey_id=survey_id,
            ops=body.ops,
            base_revision=body.baseRevision,
            transaction_id=body.transactionId,
        )
    )


@router.post("/{survey_id}/undo", operation_id="undo", responses=_ERR)
def undo(survey_id: str, body: ReverseRequest, auth: Auth, services: Services) -> EditResponse:
    return _out(
        services.builder.run(
            "survey.undo",
            auth.actor,
            survey_id=survey_id,
            transaction_id=body.transactionId,
            base_revision=body.baseRevision,
        )
    )


@router.post("/{survey_id}/redo", operation_id="redo", responses=_ERR)
def redo(survey_id: str, body: ReverseRequest, auth: Auth, services: Services) -> EditResponse:
    return _out(
        services.builder.run(
            "survey.redo",
            auth.actor,
            survey_id=survey_id,
            transaction_id=body.transactionId,
            base_revision=body.baseRevision,
        )
    )
