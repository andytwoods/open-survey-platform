"""The theme a publish embeds in the runtime plan (runtime-design §6a).

Resolution order: the survey's own theme (``settings.theme``, once the survey model carries
one), else the lab default from the theme library, else the "clean" preset. The chosen theme
runs through the contrast guard (``osp_spec.theme.validate_theme``); any error blocks the
publish with diagnostics whose pointers say where the theme came from.
"""

from __future__ import annotations

from typing import Any

from osp_spec import Diagnostic
from osp_spec.theme import PRESETS, ThemeDiagnostic, validate_theme
from osp_store import Store, TenantContext

DEFAULT_PRESET = "clean"


def _diagnostic(d: ThemeDiagnostic, source: str, prefix: str) -> Diagnostic:
    hint = f" Nearest passing value: {d.suggestion}." if d.suggestion is not None else ""
    return Diagnostic(
        severity=d.severity,
        code=d.code,
        message=f"Theme ({source}): {d.message}{hint}",
        pointer=prefix + d.pointer,
    )


def resolve_theme(
    store: Store, ctx: TenantContext, body: Any
) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    """``(theme JSON, diagnostics)``. The theme is None when the guard reports an error."""
    settings = body.get("settings") if isinstance(body, dict) else None
    own = settings.get("theme") if isinstance(settings, dict) else None
    if own is not None:
        raw, source, prefix = own, "survey theme", "/settings/theme"
    else:
        lab = store.get_lab_default_theme(ctx)
        if lab is not None:
            raw, source, prefix = lab.body, f"lab default {lab.name!r}", "/labTheme"
        else:
            raw = PRESETS[DEFAULT_PRESET].model_dump(mode="json", by_alias=True)
            source, prefix = f"{DEFAULT_PRESET} preset", "/labTheme"
    theme, found = validate_theme(raw)
    diagnostics = [_diagnostic(d, source, prefix) for d in found]
    if theme is None or any(d.severity == "error" for d in found):
        return None, diagnostics
    return theme.model_dump(mode="json", by_alias=True), diagnostics
