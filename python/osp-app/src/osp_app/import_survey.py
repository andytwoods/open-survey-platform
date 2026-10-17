"""Import commands (task IM1): preview a Qualtrics ``.qsf``, LimeSurvey ``.lss`` or
SurveyJS JSON file, and create a draft from it.

- ``survey.import_preview``: runs the importer and returns what would be created (title,
  counts, every import diagnostic, the validator's diagnostics on the result) without
  touching the store. Needs ``survey.edit`` in at least one lab.
- ``survey.import``: the same, then ``survey.create`` with the imported document (the
  usual tenant rules apply). The import diagnostics come back with the new draft so the
  builder can show them once; they are not stored.

Both need ``survey.edit`` (owner, editor), never viewer. Content is text (``.qsf`` and
SurveyJS are JSON, ``.lss`` is XML; all UTF-8), capped at :data:`MAX_BYTES`. The importers
never raise on input (osp_targets.imports); a file that cannot be read at all is a
``Rejected`` with the importer's ``error`` diagnostics.

Registered on import (``osp_app/__init__.py``); dispatched through ``Builder.run`` like the
other survey commands, so ``builder`` is the first argument.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from osp_spec import Diagnostic
from osp_targets.imports import (
    FORMATS,
    Format,
    ImportDiagnostic,
    ImportResult,
    ImportSummary,
    import_survey,
)

from .auth.permissions import Action, Actor, Resource, ResourceKind, can
from .builder import Builder, SurveyView, title_of
from .commands import command
from .errors import Forbidden, InvalidRequest, Rejected

MAX_BYTES = 20_000_000
_MAX_FILENAME = 255


@dataclass(frozen=True)
class ImportPreview:
    format: Format
    title: str
    summary: ImportSummary | None
    diagnostics: list[ImportDiagnostic]
    validation: list[Diagnostic]
    ok: bool


@dataclass(frozen=True)
class ImportOutcome:
    view: SurveyView
    preview: ImportPreview


def _check(actor: Actor, filename: object, content: object, fmt: object) -> tuple[str, str, Any]:
    if not any(
        can(actor, Action.SURVEY_EDIT, Resource(ResourceKind.SURVEY, tid)) for tid in actor.roles
    ):
        raise Forbidden("Not permitted.")
    if not isinstance(filename, str) or not 0 < len(filename) <= _MAX_FILENAME:
        raise InvalidRequest(f"filename must be 1-{_MAX_FILENAME} characters")
    if not isinstance(content, str):
        raise InvalidRequest("content must be the file's text")
    if len(content.encode("utf-8", "surrogatepass")) > MAX_BYTES:
        raise InvalidRequest(f"the file is larger than {MAX_BYTES // 1_000_000} MB")
    if fmt is not None and fmt not in FORMATS:
        raise InvalidRequest(f"format must be one of {', '.join(FORMATS)}")
    return filename, content, fmt


def _preview(result: ImportResult, title: str | None) -> ImportPreview:
    shown = (
        title
        if title
        else (result.summary.title if result.summary else None)
        or (title_of(result.survey) if result.survey else None)
        or ""
    )
    return ImportPreview(
        format=result.format,
        title=shown,
        summary=result.summary,
        diagnostics=list(result.diagnostics),
        validation=list(result.validation),
        ok=result.ok,
    )


def _rejected(result: ImportResult) -> Rejected:
    errors = [d for d in result.diagnostics if d.severity == "error"]
    return Rejected(
        "The file could not be imported.",
        [
            Diagnostic(severity="error", code=d.code, message=d.message, pointer=d.pointer)
            for d in errors
        ],
    )


@command("survey.import_preview", label="Preview a survey import", action=Action.SURVEY_EDIT)
def preview_import(
    builder: Builder,
    actor: Actor,
    *,
    filename: str,
    content: str,
    format: str | None = None,  # noqa: A002 - the API's name for it
) -> ImportPreview:
    filename, content, fmt = _check(actor, filename, content, format)
    result = import_survey(filename, content, fmt)
    return _preview(result, None)


@command("survey.import", label="Import a survey", action=Action.SURVEY_EDIT)
def import_as_draft(
    builder: Builder,
    actor: Actor,
    *,
    filename: str,
    content: str,
    format: str | None = None,  # noqa: A002
    title: str | None = None,
    tenant_id: str | None = None,
) -> ImportOutcome:
    filename, content, fmt = _check(actor, filename, content, format)
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise InvalidRequest("title must not be empty")
    result = import_survey(filename, content, fmt)
    if result.survey is None:
        raise _rejected(result)
    body = result.survey
    if title and title.strip():
        default = body["metadata"].get("defaultLanguage") or body["metadata"]["languages"][0]
        old = body["metadata"]["title"]
        body["metadata"]["title"] = (
            {**old, default: title.strip()} if isinstance(old, dict) else title.strip()
        )
    view = builder.create_survey(
        actor,
        title=title_of(body) or filename,
        survey=body,
        tenant_id=tenant_id,
    )
    return ImportOutcome(view, _preview(result, title_of(body)))


__all__ = ["MAX_BYTES", "ImportOutcome", "ImportPreview", "import_as_draft", "preview_import"]
