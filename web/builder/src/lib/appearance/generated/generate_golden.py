"""Golden outputs of the Python theme guard, for the builder's TypeScript port (guard.ts).

Regenerate from the repo root after changing osp_spec.theme:

    uv run python web/builder/src/lib/appearance/generated/generate_golden.py

Writes guard.golden.json and theme.schema.json next to this file. guard.test.ts checks the
TS guard against the golden file, and checks theme.schema.json against the copy R8 commits
in web/ui-components (so a stale copy here fails the web tests, not silently).
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from osp_spec.theme import (
    PRESETS,
    Theme,
    check_theme,
    suggest_colour,
    theme_json_schema,
    validate_theme,
)

HERE = Path(__file__).resolve().parent
FIELDS = ("accent", "background", "surface", "text", "muted", "error", "focus")


def _dump(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _hex(rng: random.Random) -> str:
    return "#" + "".join(f"{rng.randrange(256):02x}" for _ in range(3))


def _guard_cases() -> list[dict[str, Any]]:
    cases: list[tuple[str, dict[str, Any]]] = [
        (f"preset:{pid}", theme.model_dump(mode="json")) for pid, theme in PRESETS.items()
    ]
    clean = PRESETS["clean"].model_dump(mode="json")

    def variant(name: str, mode: str, **colours: str) -> None:
        theme = json.loads(json.dumps(clean))
        theme["colours"][mode].update(colours)
        cases.append((name, theme))

    variant("pale-accent", "light", accent="#66aaff")
    variant("pale-accent-dark", "dark", accent="#1a2a55")
    variant("grey-muted", "light", muted="#aaaaaa")
    variant("dark-bg-in-light", "light", background="#333333")
    variant("yellow-accent", "light", accent="#ffee00", focus="#ffee00")
    variant("bad-error", "dark", error="#550000")
    variant("all-grey", "light", **dict.fromkeys(FIELDS, "#808080"))
    small = json.loads(json.dumps(clean))
    small["baseSize"] = 14
    cases.append(("small-base", small))

    rng = random.Random(20261016)
    for i in range(40):
        theme = json.loads(json.dumps(clean))
        theme["mode"] = rng.choice(["light", "dark", "auto"])
        for mode in ("light", "dark"):
            for field in rng.sample(FIELDS, rng.randrange(1, 4)):
                theme["colours"][mode][field] = _hex(rng)
        cases.append((f"random-{i:02d}", theme))

    out = []
    for name, data in cases:
        theme = Theme.model_validate(data)
        out.append(
            {
                "name": name,
                "theme": data,
                "diagnostics": [d.model_dump(mode="json") for d in check_theme(theme)],
            }
        )
    return out


def _suggestion_cases() -> list[dict[str, Any]]:
    rng = random.Random(7)
    out = []
    for _ in range(30):
        palette = {f: _hex(rng) for f in FIELDS}
        out.append(
            {
                "palette": palette,
                "suggestions": {f: suggest_colour(palette, f) for f in FIELDS},
            }
        )
    return out


def _validation_cases() -> list[dict[str, Any]]:
    clean = PRESETS["clean"].model_dump(mode="json")

    def with_(**kw: Any) -> dict[str, Any]:
        return {**json.loads(json.dumps(clean)), **kw}

    light = clean["colours"]["light"]
    inputs: list[tuple[str, Any]] = [
        ("clean", clean),
        ("minimal", {"colours": clean["colours"]}),
        ("not-an-object", [1, 2]),
        ("string", "hello"),
        ("null", None),
        ("missing-colours", {"font": "system-sans"}),
        ("unknown-field", with_(css="body{}")),
        ("bad-hex", with_(colours={"light": {**light, "accent": "red"}, "dark": light})),
        ("short-hex", with_(colours={"light": {**light, "accent": "#fff"}, "dark": light})),
        ("missing-palette-field", with_(colours={"light": {"accent": "#000000"}, "dark": light})),
        ("extra-palette-field", with_(colours={"light": {**light, "x": "#000000"}, "dark": light})),
        ("bad-font", with_(font="Comic Sans")),
        ("base-too-big", with_(baseSize=40)),
        ("base-too-small", with_(baseSize=8)),
        ("base-float", with_(baseSize=16.5)),
        ("base-string", with_(baseSize="16")),
        ("base-bool", with_(baseSize=True)),
        ("line-low", with_(lineSpacing=0.5)),
        ("line-int", with_(lineSpacing=2)),
        ("radius-negative", with_(radius=-1)),
        ("bad-mode", with_(mode="sepia")),
        ("bad-version", with_(themeVersion="osp-theme/9")),
        ("preset-null", with_(preset=None)),
        ("preset-bad", with_(preset="neon")),
        ("header-string", with_(headerText="Sleep study")),
        ("header-map", with_(headerText={"en": "Sleep", "de-AT": "Schlaf"})),
        ("header-bad-lang", with_(headerText={"english!": "Sleep"})),
        ("header-number", with_(headerText=3)),
        ("logo-ok", with_(logoAssetId="logo_01")),
        ("logo-bad", with_(logoAssetId="../etc/passwd")),
        ("choice-bad", with_(choiceStyle="grid")),
        ("button-bad", with_(buttonStyle=None)),
    ]
    out = []
    for name, data in inputs:
        theme, _ = validate_theme(data)
        out.append({"name": name, "input": data, "valid": theme is not None})
    return out


def main() -> None:
    (HERE / "theme.schema.json").write_text(_dump(theme_json_schema()))
    golden = {
        "_comment": "Generated by generate_golden.py from osp_spec.theme. Do not edit.",
        "guard": _guard_cases(),
        "suggestions": _suggestion_cases(),
        "validation": _validation_cases(),
    }
    (HERE / "guard.golden.json").write_text(_dump(golden))


if __name__ == "__main__":
    main()
