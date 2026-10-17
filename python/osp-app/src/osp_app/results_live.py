"""Live results, the cheap half (task LV2, ``planning/live-results.md`` LV-D1, LV-D2).

The results page polls ``survey.results_watermark`` and re-queries only when the value
differs from the ``watermark`` of its last ``ResultsResponse``. The watermark is a hash of
each version's (response count, newest ``submitted_at``): one ``COUNT`` / ``MAX`` per
version that reads no answer, so the call is **not audited** (LV-D7), like reading a
survey's metadata. Access is ``survey.export`` (owner, editor), the same as the query, so
a viewer or another lab learns nothing here that the query would refuse.

The poll interval the server wants (``pollAfterMs``, ``OSP_LIVE_POLL_MS``) and the
per-actor rate limit are the API shell's (``osp_api.routes.results``): deployment
settings, not survey semantics.
"""

from __future__ import annotations

from typing import Any

from .auth.permissions import Action, Actor
from .builder import Builder
from .commands import command
from .results import choose_versions, parse_query, watermark_of


@command("survey.results_watermark", label="Results watermark", action=Action.SURVEY_EXPORT)
def results_watermark(
    builder: Builder, actor: Actor, *, survey_id: str, versions: Any = None
) -> dict[str, Any]:
    """``{watermark, responses, versionsUsed}`` for the latest published version or the
    given ones: the same ``watermark`` a results query of those versions returns, and the
    stored response count of the versions (every status, before any filter)."""
    numbers = parse_query({"versions": versions} if versions else None).versions
    ctx, chosen = choose_versions(builder, actor, survey_id, numbers)
    watermark, responses = watermark_of(builder, ctx, chosen)
    return {
        "watermark": watermark,
        "responses": responses,
        "versionsUsed": [v.number for v in chosen],
    }
