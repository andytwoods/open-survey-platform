"""Figure export audit (task V4, planning/results-viewer.md V-D3, V-D6).

Figures (SVG, PNG, CSV, Vega-Lite spec, manifest, page ZIP) are drawn in the browser from
the aggregates the results query already returned, so the server never sees the files.
Before a download the builder calls ``survey.results_export``: it checks the caller may
export (``survey.export``: owner, editor), resolves the query's versions the same way the
results query does (so ``queryHash`` matches the one in the manifest), and writes one
``results.export`` audit row: actor, normalised query, versions, cards, formats, scope and
the suppression threshold. Never any answer value or count.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .auth.permissions import Action, Actor
from .builder import Builder
from .commands import command
from .errors import InvalidRequest
from .results import load, parse_query

FORMATS = ("svg", "png", "csv", "vega-lite", "manifest", "zip")
SCOPES = ("card", "page")
MAX_CARDS = 500
MAX_K = 1000


def _cards(value: Any) -> list[str]:
    if not isinstance(value, list | tuple) or not 0 < len(value) <= MAX_CARDS:
        raise InvalidRequest(f"cards must be a list of 1-{MAX_CARDS} question ids")
    out: list[str] = []
    for c in value:
        if not isinstance(c, str) or not 0 < len(c) <= 200:
            raise InvalidRequest("cards[] must be question ids of 1-200 characters")
        if c not in out:
            out.append(c)
    return out


def _formats(value: Any) -> list[str]:
    if not isinstance(value, list | tuple) or not 0 < len(value) <= len(FORMATS):
        raise InvalidRequest("formats must be a non-empty list")
    out: list[str] = []
    for f in value:
        if f not in FORMATS:
            raise InvalidRequest(f"formats[] must be one of {', '.join(FORMATS)}")
        if f not in out:
            out.append(f)
    return sorted(out, key=FORMATS.index)


def _k(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_K:
        raise InvalidRequest(f"suppressBelow must be an integer from 1 to {MAX_K}, or null")
    return value


@command("survey.results_export", label="Record a figure export", action=Action.SURVEY_EXPORT)
def results_export(
    builder: Builder,
    actor: Actor,
    *,
    survey_id: str,
    query: Any = None,
    cards: Any = None,
    formats: Any = None,
    scope: Any = "card",
    suppress_below: Any = None,
) -> dict[str, Any]:
    # Access first (fail closed): a non-member learns nothing, not even about bad input.
    builder._locate(actor, survey_id, Action.SURVEY_EXPORT)
    if scope not in SCOPES:
        raise InvalidRequest("scope must be card or page")
    if query is not None and not isinstance(query, Mapping):
        raise InvalidRequest("query must be an object")
    q = parse_query(query)
    card_ids = _cards(cards)
    fmts = _formats(formats)
    k = _k(suppress_below)
    loaded = load(builder, actor, survey_id, q.versions)
    numbers = [vi.number for vi in loaded.versions]
    norm = q.normalised(numbers)
    query_hash = hashlib.sha256(
        json.dumps(norm, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    builder.store.audit(
        loaded.ctx,
        "results.export",
        "survey",
        survey_id,
        {
            "query": norm,
            "queryHash": query_hash,
            "versions": numbers,
            "cards": card_ids,
            "formats": fmts,
            "scope": scope,
            "suppressBelow": k,
        },
    )
    return {"recorded": True, "queryHash": query_hash, "versions": numbers, "formats": fmts}
