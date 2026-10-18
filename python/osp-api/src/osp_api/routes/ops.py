"""The edit flow (builder-design §4): ops as one transaction, undo, redo.

POST /api/surveys/{id}/ops   {ops: [{op, params}], baseRevision, transactionId?}
  -> 200 {revision, patch, diagnostics, transactionId}
  -> 409 {currentRevision}  stale baseRevision: refetch and replay
  -> 422 {diagnostics, failedIndex}  rejected; nothing applied

PUT /api/surveys/{id}/draft  {baseRevision, patch, ops, transactionId}   (the builder, CE5)
  The builder applies its ops in the browser (@osp/ops) and saves the resulting document as
  an RFC 6902 patch; the server validates the whole document (osp_app.draft_save).
  -> 200 {revision, diagnostics, transactionId, replayed}
  -> 409 {currentRevision}  stale baseRevision: refetch, rebase the local ops, save again
  -> 422 {diagnostics}  the patch doesn't apply or the result is invalid; nothing saved
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from osp_app import DraftSaved, EditResult
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


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseRevision: int = Field(ge=0, description="The revision the patch was made against")
    patch: list[dict[str, Any]] = Field(
        max_length=10_000, description="RFC 6902, from baseRevision to the new document"
    )
    ops: list[Invocation] = Field(
        default_factory=list,
        max_length=1000,
        description="The ops the client applied to make the patch: logged, not re-run",
    )
    transactionId: str = Field(
        pattern=r"^[A-Za-z0-9_-]{1,36}$",
        description="Client-chosen id; a retry with the same id is not applied twice",
    )


class DraftResponse(BaseModel):
    revision: int
    diagnostics: list[Diagnostic] = Field(description="The validator's, for the saved draft")
    transactionId: str | None = Field(
        description="The transaction logged; null when the patch changed nothing"
    )
    replayed: bool = False


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


@router.put("/{survey_id}/draft", operation_id="saveDraft", responses=_ERR)
def save_draft(survey_id: str, body: DraftRequest, auth: Auth, services: Services) -> DraftResponse:
    r: DraftSaved = services.builder.run(
        "survey.save_draft",
        auth.actor,
        survey_id=survey_id,
        base_revision=body.baseRevision,
        patch=body.patch,
        ops=body.ops,
        transaction_id=body.transactionId,
    )
    return DraftResponse(
        revision=r.revision,
        diagnostics=r.diagnostics,
        transactionId=r.transaction_id,
        replayed=r.replayed,
    )
