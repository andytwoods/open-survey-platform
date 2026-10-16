"""JSON export of responses (semantics §1: ``null`` value plus a ``state`` per answer).

Keys are export names, in survey order; values keep their JSON types (a decimal stays a
string so no binary float creeps in, semantics §2). Output is UTF-8, 2-space indented, with
a trailing newline, and byte-identical for the same input.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from .layout import Layout, build_layout, split_names
from .model import JsonOptions, StoredResponse, SurveyVersion
from .view import ResponseView, _map

FORMAT = "osp-response-export/1"

MISSING_VALUES = (
    "Every answer is {state, value}. state is answered, unanswered (shown, left empty), "
    "irrelevant (page reached, hidden by its show-if) or not-reached (the flow never got to "
    "its page); value is null unless state is answered. state is null only if the stored "
    "record has no entry for the question. Embedded and computed variables are {state, "
    "value} too: answered when they have a value; otherwise unanswered, or (computed) "
    "irrelevant / not-reached when every question they read is."
)

_META_KEYS = {
    "_response_id": "responseId",
    "_session_id": "sessionId",
    "_version": "version",
    "_version_checksum": "versionChecksum",
    "_plan_checksum": "planChecksum",
    "_engine_version": "engineVersion",
    "_allocation_mode": "allocationMode",
    "_save_mode": "saveMode",
    "_seed": "seed",
    "_started_at": "startedAt",
    "_submitted_at": "submittedAt",
    "_late": "late",
    "_after_close": "afterClose",
    "_end": "end",
    "_language": "language",
}


def _json_value(value: Any) -> Any:
    """Only JSON-native data; anything else (never expected) as its text."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list | tuple):
        return [_json_value(v) for v in value]
    if isinstance(value, Mapping):
        return {str(k): _json_value(v) for k, v in value.items()}
    return str(value)


def response_json(view: ResponseView, opts: JsonOptions) -> dict[str, Any]:
    lay, rec = view.lay, view.rec
    out: dict[str, Any] = {key: _json_value(view.meta(col)) for col, key in _META_KEYS.items()}
    out["conditions"] = {v.name: _json_value(view.condition(v.id)) for v in lay.assigned}
    answers: dict[str, Any] = {}
    for q in lay.questions:
        state, value = view.answer(q.id)
        answers[q.name] = {"state": state, "value": _json_value(value)}
    out["answers"] = answers
    out["variables"] = {
        v.name: {"state": view.variable_state(v.id), "value": _json_value(view.variable(v.id))}
        for v in [*lay.embedded, *lay.computed]
    }
    orders: dict[str, dict[str, Any]] = {"blocks": {}, "items": {}, "choices": {}}
    for o in lay.orders:
        key = lay.names.get(o.node, o.node) if o.kind == "choices" else o.node
        orders[o.kind][key] = _json_value(view.order(o))
    out["orders"] = orders
    out["quotas"] = _json_value(_map(rec.get("quotas")))
    out["urlParams"] = _json_value(_map(rec.get("urlParams")))
    if opts.events:
        events = rec.get("events")
        out["events"] = _json_value(events if isinstance(events, list) else [])
    return out


def _survey_json(lay: Layout) -> dict[str, Any]:
    return {
        "id": lay.survey.id,
        "title": lay.title,
        "version": lay.number,
        "checksum": lay.checksum,
    }


def _dump(doc: dict[str, Any]) -> bytes:
    return (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def export_json(
    version: SurveyVersion,
    responses: Sequence[StoredResponse],
    options: JsonOptions | None = None,
) -> bytes:
    opts = options or JsonOptions()
    lay = build_layout(version)
    views = sorted(
        (ResponseView(r, lay, version.save_mode) for r in responses), key=ResponseView.sort_key
    )
    return _dump(
        {
            "format": FORMAT,
            "survey": _survey_json(lay),
            "missingValues": MISSING_VALUES,
            "options": {"events": opts.events},
            "responses": [response_json(v, opts) for v in views],
        }
    )


def export_json_combined(
    versions: Sequence[tuple[SurveyVersion, Sequence[StoredResponse]]],
    options: JsonOptions | None = None,
) -> bytes:
    """Several versions: ``versions`` lists each one, and every response carries
    ``version`` and the answers of *its* version's questions only. A question whose type or
    choice codes differ between versions is keyed ``<name>_v<N>`` (semantics M2-3), as in
    the combined CSV and codebook."""
    opts = options or JsonOptions()
    out_versions: list[dict[str, Any]] = []
    out_responses: list[dict[str, Any]] = []
    ordered = sorted(
        versions,
        key=lambda vr: (vr[0].number if vr[0].number is not None else 0, vr[0].checksum or ""),
    )
    split = split_names([build_layout(v) for v, _ in ordered])
    for version, responses in ordered:
        lay = build_layout(version, split)
        out_versions.append(_survey_json(lay))
        views = sorted(
            (ResponseView(r, lay, version.save_mode) for r in responses),
            key=ResponseView.sort_key,
        )
        out_responses.extend(response_json(v, opts) for v in views)
    return _dump(
        {
            "format": FORMAT,
            "versions": out_versions,
            "missingValues": MISSING_VALUES,
            "options": {"events": opts.events},
            "responses": out_responses,
        }
    )
