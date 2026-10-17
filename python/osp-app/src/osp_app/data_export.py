"""Response data export commands (task M2): CSV / JSON responses and the codebook.

Both need ``survey.export`` (owner, editor; never viewer), because they contain or
describe participant data. Reading responses is audited by the store (``responses.read``
per version, ``response.read`` per full record).

- ``version`` given: that version's responses with that version's codebook.
- ``version`` omitted: every published version, combined (union of columns plus a
  ``_version`` column; with one version this is exactly that version's export).

Registered on import (``osp_app/__init__.py``); dispatched through ``Builder.run`` like the
other survey commands, so ``builder`` is the first argument.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from osp_store import NotFound, ParticipantStore, Response, Survey, TenantContext, Version
from osp_targets.data import (
    CsvOptions,
    ExportError,
    JsonOptions,
    StoredResponse,
    SurveyVersion,
    codebook,
    codebook_combined,
    export_csv,
    export_csv_combined,
    export_json,
    export_json_combined,
)

from .auth.permissions import Action, Actor
from .builder import Builder, ExportResult
from .commands import command
from .errors import InvalidRequest, NotFoundError, Rejected

CSV_MEDIA = "text/csv; charset=utf-8"
JSON_MEDIA = "application/json"
MD_MEDIA = "text/markdown; charset=utf-8"


@dataclass(frozen=True)
class DataExport(ExportResult):
    media_type: str = "application/octet-stream"


def _after_close(survey: Survey, r: Response) -> bool:
    """Submitted after the survey was closed (``_after_close``; not the same as late)."""
    return survey.closed_at is not None and r.submitted_at > survey.closed_at


def _stored(builder: Builder, ctx: TenantContext, survey: Survey, v: Version) -> list[Any]:
    participants = ParticipantStore(builder.store)
    out: list[StoredResponse] = []
    for r in builder.store.list_responses(ctx, v.id):
        try:
            full = participants.get_record(ctx, r.id)
        except NotFound:  # recorded without the participant runtime: row data only
            full = None
        full = full if isinstance(full, Mapping) else {}
        record = full.get("record")
        server = full.get("server") if isinstance(full.get("server"), Mapping) else {}
        out.append(
            StoredResponse(
                response_id=r.id,
                record=record if isinstance(record, Mapping) else None,
                answers=r.answers,
                session_id=r.session_id,
                version=v.number,
                version_checksum=r.version_checksum,
                allocation_mode=r.allocation_mode,
                save_mode=server.get("saveMode"),
                session_seed=r.session_seed,
                assigned=r.assigned_conditions,
                orders=r.realised_orders,
                engine_version=r.engine_version,
                started_at=r.started_at,
                submitted_at=r.submitted_at,
                # semantics S-2 / M2-1: the server's own flag, set when it accepted a
                # submit after the session expired; a record without one is not late.
                late=server.get("late") is True,
                after_close=_after_close(survey, r),
                consent_version=server.get("consentVersion"),
                consented_at=_when(server.get("consentedAt")),
            )
        )
    return out


def _when(value: Any) -> datetime | None:
    """An ISO 8601 timestamp the server stored (``server.consentedAt``), or None."""
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _save_mode(responses: list[StoredResponse]) -> Any:
    modes = {r.save_mode for r in responses if r.save_mode}
    return modes.pop() if len(modes) == 1 else None


def _load(
    builder: Builder, actor: Actor, survey_id: str, version: object, *, responses: bool
) -> tuple[Survey, list[tuple[SurveyVersion, list[StoredResponse]]]]:
    ctx = builder._locate(actor, survey_id, Action.SURVEY_EXPORT)
    if version is not None and (type(version) is not int or version < 1):
        raise InvalidRequest("version must be a positive integer")
    survey = builder.store.get_survey(ctx, survey_id)
    versions = builder.store.list_versions(ctx, survey_id)
    if version is not None:
        versions = [v for v in versions if v.number == version]
    if not versions:
        raise NotFoundError(
            "No such published version." if version is not None else "Nothing published yet."
        )
    out = []
    for v in versions:
        rows = _stored(builder, ctx, survey, v) if responses else []
        sv = SurveyVersion(v.body, number=v.number, checksum=v.checksum, save_mode=_save_mode(rows))
        out.append((sv, rows))
    return survey, out


def _name(survey_id: str, version: int | None, what: str, ext: str) -> str:
    which = f"v{version}" if version is not None else "all-versions"
    return f"survey-{survey_id[:8]}-{which}-{what}.{ext}"


@command("survey.export_responses", label="Export responses", action=Action.SURVEY_EXPORT)
def export_responses(
    builder: Builder,
    actor: Actor,
    *,
    survey_id: str,
    format: Literal["csv", "json"] = "csv",
    version: int | None = None,
    state_columns: bool = True,
    multi: Literal["columns", "codes"] = "columns",
    excel: bool = False,
    events: bool = False,
) -> DataExport:
    if format not in ("csv", "json") or multi not in ("columns", "codes"):
        raise InvalidRequest("format must be csv or json; multi must be columns or codes")
    _, loaded = _load(builder, actor, survey_id, version, responses=True)
    try:
        if format == "csv":
            opts = CsvOptions(state_columns=state_columns, multi=multi, bom=bool(excel))
            content = export_csv(*loaded[0], opts) if version else export_csv_combined(loaded, opts)
            return DataExport(
                content, _name(survey_id, version, "responses", "csv"), media_type=CSV_MEDIA
            )
        jopts = JsonOptions(events=bool(events))
        content = export_json(*loaded[0], jopts) if version else export_json_combined(loaded, jopts)
        return DataExport(
            content, _name(survey_id, version, "responses", "json"), media_type=JSON_MEDIA
        )
    except ExportError as exc:
        raise Rejected(str(exc), exc.diagnostics) from exc


@command("survey.delete_response", label="Delete response", action=Action.RESPONSE_DELETE)
def delete_response(builder: Builder, actor: Actor, *, survey_id: str, response_id: str) -> None:
    """Delete one participant's response and its session (e.g. a withdrawal request that
    reached the researcher). Needs ``response.delete`` (owner, editor). The store writes a
    ``response.delete`` audit entry naming the response and the reason, never answers.
    A response of another survey is "not found", as for any other lab's data."""
    ctx = builder._locate(actor, survey_id, Action.RESPONSE_DELETE)
    if not isinstance(response_id, str) or not 0 < len(response_id) <= 36:
        raise NotFoundError("Response not found.")
    try:
        version_id = builder.store.locate_response(ctx, response_id)
    except NotFound as exc:
        raise NotFoundError("Response not found.") from exc
    if version_id not in {v.id for v in builder.store.list_versions(ctx, survey_id)}:
        raise NotFoundError("Response not found.")
    builder.store.delete_response(ctx, response_id, reason="researcher deletion")


@command("survey.export_codebook", label="Export codebook", action=Action.SURVEY_EXPORT)
def export_codebook(
    builder: Builder,
    actor: Actor,
    *,
    survey_id: str,
    format: Literal["md", "json"] = "md",
    version: int | None = None,
    state_columns: bool = True,
    multi: Literal["columns", "codes"] = "columns",
) -> DataExport:
    if format not in ("md", "json") or multi not in ("columns", "codes"):
        raise InvalidRequest("format must be md or json; multi must be columns or codes")
    # Responses are read only for the recorded save mode; the codebook holds no answers.
    _, loaded = _load(builder, actor, survey_id, version, responses=True)
    opts = CsvOptions(state_columns=state_columns, multi=multi)
    try:
        book = (
            codebook(loaded[0][0], opts)
            if version
            else codebook_combined([sv for sv, _ in loaded], opts)
        )
    except ExportError as exc:
        raise Rejected(str(exc), exc.diagnostics) from exc
    if format == "md":
        return DataExport(
            book.markdown.encode("utf-8"),
            _name(survey_id, version, "codebook", "md"),
            media_type=MD_MEDIA,
        )
    return DataExport(
        (json.dumps(book.data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        _name(survey_id, version, "codebook", "json"),
        media_type=JSON_MEDIA,
    )
