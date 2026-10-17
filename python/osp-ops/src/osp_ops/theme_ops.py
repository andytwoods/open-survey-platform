"""Theme op: `set_theme` (runtime-design §6a, Appearance view "Use for this survey").

The survey keeps its own full copy of the theme in `settings.theme` (osp_spec.model.Settings);
a lab library theme is copied in by the caller, never referenced by id. The contrast guard
does not block this edit (a draft may be mid-fix); publishing does (osp_app.publish_theme).
"""

from __future__ import annotations

import copy

from osp_spec.theme import validate_theme
from pydantic import JsonValue

from .registry import REVERSE_PATCH, Ctx, Invocation, OpError, Params, op


class SetTheme(Params):
    theme: dict[str, JsonValue] | None = None  # None: back to the lab default / "clean"


@op("set_theme", SetTheme, label="Set survey theme", area="survey")
def set_theme(ctx: Ctx, p: SetTheme) -> Invocation:
    """Set the survey's theme (a full `osp-theme/0.1` document), or with `theme: null`
    remove it, so publishing uses the lab default theme, else the Clean preset. The theme
    must match the theme schema; contrast problems are reported at publish."""
    settings = ctx.doc.get("settings")
    if p.theme is None:
        if not isinstance(settings, dict) or "theme" not in settings:
            return REVERSE_PATCH  # nothing to remove
        del settings["theme"]
        if not settings:
            del ctx.doc["settings"]
        ctx.touch()
        return REVERSE_PATCH
    theme, found = validate_theme(p.theme)
    if theme is None:
        first = found[0] if found else None
        raise OpError(
            "op.invalid_result",
            f"not a valid theme: {first.message if first else 'schema mismatch'}"[:300],
            "/settings/theme" + (first.pointer if first else ""),
        )
    if not isinstance(settings, dict):
        settings = ctx.doc["settings"] = {}
    settings["theme"] = copy.deepcopy(theme.model_dump(mode="json", by_alias=True))
    ctx.touch()
    return REVERSE_PATCH
