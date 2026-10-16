"""Survey themes (runtime-design §6a): the model, the contrast guard and the presets.

Researchers style a survey by editing these tokens, never CSS. Pure data and maths, no I/O.

- :class:`Theme` is the pydantic model; :func:`theme_json_schema` exports it. The committed
  schema, the presets and the derived palettes live in ``web/ui-components/src/theme/generated``
  (``tests/test_theme.py`` fails when they are stale and says how to regenerate).
- :func:`derive_palette` turns the seven theme colours of one mode into the colour tokens the
  page is drawn with (W1's names in ``tokens.css``). The TypeScript bridge
  (``themeToCssVars``) computes exactly the same hex values; a golden file proves it.
- :func:`check_theme` is the guard: every foreground/background pair the page actually uses
  is checked against WCAG AA (4.5:1 text, 3:1 UI components and focus indicators), and every
  failure carries the nearest passing colour, found by moving OKLCH lightness only. It also
  enforces the 16 px minimum input font size (§6, stops iOS auto-zoom).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, StringConstraints, ValidationError

from .model import Model, Text

THEME_VERSION = "osp-theme/0.1"
THEME_SCHEMA_ID = f"urn:osp:schema:{THEME_VERSION.replace('/', ':')}:theme"

type HexColour = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
type AssetId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]

PresetId = Literal["clean", "warm", "high-contrast", "dark", "compact"]
# System stacks only for now: no font files are bundled yet, and fonts are never fetched
# from a third-party CDN at runtime (participant privacy). A bundled OFL font adds an id here.
FontId = Literal["system-sans", "system-serif", "system-rounded"]
Density = Literal["comfortable", "compact"]
ButtonStyle = Literal["filled", "outline"]
ChoiceStyle = Literal["list", "cards", "buttons"]
ThemeMode = Literal["light", "dark", "auto"]
Mode = Literal["light", "dark"]

MIN_INPUT_FONT_PX = 16
TEXT_RATIO = 4.5  # WCAG 1.4.3 normal text
UI_RATIO = 3.0  # WCAG 1.4.11 UI components and graphical objects; 1.4.3 large text
FOCUS_RATIO = 3.0  # WCAG 2.4.13 / 1.4.11 focus indicator against what it sits on


# --- Model ------------------------------------------------------------------------------


class Palette(Model):
    """The colours of one mode. Everything else on the page is derived from these."""

    accent: HexColour  # links, filled buttons, selected choices
    background: HexColour  # page; also the text colour on filled (accent) buttons
    surface: HexColour  # question cards, panels
    text: HexColour
    muted: HexColour  # hints, descriptions, control borders
    error: HexColour
    focus: HexColour  # focus ring


class Colours(Model):
    light: Palette
    dark: Palette


class Theme(Model):
    """A survey theme. Fields are design tokens; there is no free-form CSS here."""

    themeVersion: Literal["osp-theme/0.1"] = THEME_VERSION
    preset: PresetId | None = None  # the preset this theme started from
    colours: Colours
    logoAssetId: AssetId | None = None  # an asset uploaded to and served from our origin
    headerText: Text | None = None
    font: FontId = "system-sans"
    baseSize: int = Field(default=16, ge=12, le=32)  # px; inputs use it, guard needs >= 16
    lineSpacing: float = Field(default=1.5, ge=1.0, le=2.5)
    radius: int = Field(default=6, ge=0, le=32)  # px
    density: Density = "comfortable"
    buttonStyle: ButtonStyle = "filled"
    choiceStyle: ChoiceStyle = "list"
    mode: ThemeMode = "auto"  # auto follows the participant's device


def theme_json_schema() -> dict[str, Any]:
    """The JSON Schema (draft 2020-12) for a theme document."""
    schema = Theme.model_json_schema(by_alias=True, mode="validation")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": THEME_SCHEMA_ID,
        **schema,
    }


# --- Colour maths (sRGB, OKLab/OKLCH, WCAG 2 contrast) ------------------------------------
# The TypeScript bridge mirrors these functions line for line (web/ui-components/src/theme).

type RGB = tuple[float, float, float]


def _to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _from_linear(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def hex_to_rgb(hex_colour: str) -> RGB:
    h = hex_colour.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


def rgb_to_hex(rgb: RGB) -> str:
    return "#" + "".join(f"{math.floor(min(1.0, max(0.0, c)) * 255 + 0.5):02x}" for c in rgb)


def relative_luminance(hex_colour: str) -> float:
    r, g, b = (_to_linear(c) for c in hex_to_rgb(hex_colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _rgb_to_oklab(rgb: RGB) -> RGB:
    r, g, b = (_to_linear(c) for c in rgb)
    lc = math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    mc = math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    sc = math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return (
        0.2104542553 * lc + 0.7936177850 * mc - 0.0040720468 * sc,
        1.9779984951 * lc - 2.4285922050 * mc + 0.4505937099 * sc,
        0.0259040371 * lc + 0.7827717662 * mc - 0.8086757660 * sc,
    )


def _oklab_to_linear(lab: RGB) -> RGB:
    L, a, b = lab
    lc = L + 0.3963377774 * a + 0.2158037573 * b
    mc = L - 0.1055613458 * a - 0.0638541728 * b
    sc = L - 0.0894841775 * a - 1.2914855480 * b
    l3, m3, s3 = lc**3, mc**3, sc**3
    return (
        4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3,
        -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3,
        -0.0041960863 * l3 - 0.7034186147 * m3 + 1.7076147010 * s3,
    )


def _oklab_to_hex(lab: RGB) -> str:
    r, g, b = _oklab_to_linear(lab)
    return rgb_to_hex((_from_linear(r), _from_linear(g), _from_linear(b)))


def hex_to_oklch(hex_colour: str) -> RGB:
    L, a, b = _rgb_to_oklab(hex_to_rgb(hex_colour))
    return (L, math.hypot(a, b), math.atan2(b, a))


def oklch_to_hex(L: float, C: float, h: float) -> str:
    """OKLCH to sRGB hex, gamut-mapped by reducing chroma (then clipped)."""

    def in_gamut(c: float) -> bool:
        lin = _oklab_to_linear((L, c * math.cos(h), c * math.sin(h)))
        return all(-1e-6 <= x <= 1 + 1e-6 for x in lin)

    if not in_gamut(C):
        lo, hi = 0.0, C
        for _ in range(24):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if in_gamut(mid) else (lo, mid)
        C = lo
    return _oklab_to_hex((L, C * math.cos(h), C * math.sin(h)))


def mix(a: str, b: str, amount: float) -> str:
    """Interpolate from ``a`` towards ``b`` by ``amount`` (0..1) in OKLab, like
    ``color-mix(in oklab, a, b amount)``, rounded to 8-bit sRGB."""
    la, lb = _rgb_to_oklab(hex_to_rgb(a)), _rgb_to_oklab(hex_to_rgb(b))
    return _oklab_to_hex(tuple(x + (y - x) * amount for x, y in zip(la, lb, strict=True)))  # type: ignore[arg-type]


# --- Derived palette ----------------------------------------------------------------------

#: W1 colour token (``--color-<name>``) -> how it is derived from the seven theme colours.
#: ``("field", f)`` copies a theme colour; ``("mix", a, b, p)`` mixes a towards b by p.
DERIVATION: dict[str, tuple[Any, ...]] = {
    "bg": ("field", "background"),
    "surface": ("field", "surface"),
    "surface-raised": ("field", "background"),  # inputs, choice cards
    "surface-sunken": ("mix", "background", "text", 0.08),  # hover
    "border": ("mix", "background", "text", 0.18),  # decorative dividers only
    "border-strong": ("field", "muted"),  # control boundaries (radios, inputs)
    "text": ("field", "text"),
    "text-muted": ("field", "muted"),
    "accent": ("field", "accent"),
    "accent-hover": ("mix", "accent", "text", 0.15),
    "on-accent": ("field", "background"),
    "accent-subtle": ("mix", "background", "accent", 0.10),
    "selected": ("mix", "background", "accent", 0.18),  # selected choice card / button
    "focus": ("field", "focus"),
    "danger": ("field", "error"),
}


def derive_palette(palette: Palette | dict[str, str]) -> dict[str, str]:
    """The colour tokens (W1 names, without ``--color-``) for one mode, as lower-case hex."""
    src = palette.model_dump() if isinstance(palette, Palette) else palette
    out: dict[str, str] = {}
    for token, rule in DERIVATION.items():
        if rule[0] == "field":
            out[token] = src[rule[1]].lower()
        else:
            out[token] = mix(src[rule[1]], src[rule[2]], rule[3])
    return out


# --- Contrast guard -----------------------------------------------------------------------

_BACKDROPS = ("bg", "surface", "surface-sunken", "accent-subtle", "selected")

#: Every pair the participant page draws: (foreground token, background token, minimum
#: ratio, what it is, theme colour to adjust when it fails).
PAIRS: tuple[tuple[str, str, float, str, str], ...] = (
    *((("text", b, TEXT_RATIO, "body text", "text")) for b in _BACKDROPS),
    *((("text-muted", b, TEXT_RATIO, "hint text", "muted")) for b in _BACKDROPS),
    ("border-strong", "surface-raised", UI_RATIO, "control border", "muted"),
    ("accent", "bg", TEXT_RATIO, "link text / filled button label", "accent"),
    ("accent", "surface", TEXT_RATIO, "link text on a card", "accent"),
    ("accent", "selected", UI_RATIO, "selected choice border", "accent"),
    ("on-accent", "accent-hover", TEXT_RATIO, "button label on hover", "accent"),
    ("danger", "bg", TEXT_RATIO, "error message", "error"),
    ("danger", "surface", TEXT_RATIO, "error message on a card", "error"),
    *((("focus", b, FOCUS_RATIO, "focus indicator", "focus")) for b in _BACKDROPS),
)


class ThemeDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True)

    severity: Literal["error", "warning"]
    code: str  # theme.contrast | theme.input_font_size | theme.schema
    message: str
    pointer: str  # RFC 6901 into the theme document
    ratio: float | None = None  # measured contrast (theme.contrast)
    required: float | None = None
    suggestion: StrictStr | int | None = None  # nearest passing value for `pointer`


def _passes(palette: dict[str, str], field: str) -> bool:
    tokens = derive_palette(palette)
    return all(
        contrast_ratio(tokens[fg], tokens[bg]) >= ratio
        for fg, bg, ratio, _, adjust in PAIRS
        if adjust == field
    )


def suggest_colour(palette: Palette | dict[str, str], field: str) -> str | None:
    """Nearest colour for ``field`` (same OKLCH chroma and hue, lightness moved as little as
    possible) with which every pair this field is adjusted for passes. None if none does."""
    src = palette.model_dump() if isinstance(palette, Palette) else dict(palette)
    L, C, h = hex_to_oklch(src[field])
    best: tuple[float, str] | None = None
    for direction in (-1, 1):
        step = 0.0025
        lightness = L
        while 0.0 <= lightness <= 1.0:
            lightness += direction * step
            candidate = oklch_to_hex(min(1.0, max(0.0, lightness)), C, h)
            if _passes({**src, field: candidate}, field):
                delta = abs(lightness - L)
                if best is None or delta < best[0]:
                    best = (delta, candidate)
                break
    return best[1] if best else None


def _modes(theme: Theme, modes: Iterable[Mode] | None) -> tuple[Mode, ...]:
    if modes is not None:
        return tuple(modes)
    return ("light", "dark") if theme.mode == "auto" else (theme.mode,)


def check_theme(theme: Theme, modes: Iterable[Mode] | None = None) -> list[ThemeDiagnostic]:
    """Guard a theme: WCAG AA contrast for every pair used, in every mode the theme can show
    (``mode: auto`` shows both), and the minimum input font size. Pure; never raises."""
    out: list[ThemeDiagnostic] = []
    if theme.baseSize < MIN_INPUT_FONT_PX:
        out.append(
            ThemeDiagnostic(
                severity="error",
                code="theme.input_font_size",
                message=(
                    f"Base size {theme.baseSize}px is below {MIN_INPUT_FONT_PX}px; text inputs "
                    "would trigger auto-zoom on iOS."
                ),
                pointer="/baseSize",
                suggestion=MIN_INPUT_FONT_PX,
            )
        )
    for mode in _modes(theme, modes):
        palette = getattr(theme.colours, mode)
        tokens = derive_palette(palette)
        suggestions: dict[str, str | None] = {}
        for fg, bg, required, what, adjust in PAIRS:
            ratio = contrast_ratio(tokens[fg], tokens[bg])
            if ratio >= required:
                continue
            if adjust not in suggestions:
                suggestions[adjust] = suggest_colour(palette, adjust)
            out.append(
                ThemeDiagnostic(
                    severity="error",
                    code="theme.contrast",
                    message=(
                        f"{mode}: {what} ({fg} {tokens[fg]} on {bg} {tokens[bg]}) has contrast "
                        f"{ratio:.2f}:1; WCAG AA needs {required}:1."
                    ),
                    pointer=f"/colours/{mode}/{adjust}",
                    ratio=round(ratio, 2),
                    required=required,
                    suggestion=suggestions[adjust],
                )
            )
    return out


def validate_theme(data: object) -> tuple[Theme | None, list[ThemeDiagnostic]]:
    """Parse untrusted theme JSON and guard it. Bad input gives diagnostics, never raises."""
    try:
        theme = Theme.model_validate(data)
    except ValidationError as exc:
        return None, [
            ThemeDiagnostic(
                severity="error",
                code="theme.schema",
                message=err["msg"],
                pointer="".join(
                    "/" + str(p).replace("~", "~0").replace("/", "~1") for p in err["loc"]
                ),
            )
            for err in exc.errors()
        ]
    return theme, check_theme(theme)


# --- Presets ------------------------------------------------------------------------------

_CLEAN_LIGHT = {
    "accent": "#2456c7",
    "background": "#ffffff",
    "surface": "#f6f7f9",
    "text": "#1d2433",
    "muted": "#505a6b",
    "error": "#b42318",
    "focus": "#2456c7",
}
_CLEAN_DARK = {
    "accent": "#8fb0ff",
    "background": "#12151b",
    "surface": "#191d25",
    "text": "#e6e9ef",
    "muted": "#a9b1bf",
    "error": "#ff8a80",
    "focus": "#8fb0ff",
}

_PRESET_DATA: dict[str, dict[str, Any]] = {
    "clean": {
        "preset": "clean",
        "colours": {"light": _CLEAN_LIGHT, "dark": _CLEAN_DARK},
    },
    "warm": {
        "preset": "warm",
        "colours": {
            "light": {
                "accent": "#a3431a",
                "background": "#fdf8f1",
                "surface": "#f5ecdf",
                "text": "#2b2118",
                "muted": "#65544a",
                "error": "#a8201a",
                "focus": "#a3431a",
            },
            "dark": {
                "accent": "#f2a571",
                "background": "#1c1713",
                "surface": "#262019",
                "text": "#f3eadf",
                "muted": "#c4b4a2",
                "error": "#ff8f84",
                "focus": "#f2a571",
            },
        },
        "font": "system-serif",
        "lineSpacing": 1.6,
        "radius": 12,
        "choiceStyle": "cards",
    },
    "high-contrast": {
        "preset": "high-contrast",
        "colours": {
            "light": {
                "accent": "#0030b8",
                "background": "#ffffff",
                "surface": "#ffffff",
                "text": "#000000",
                "muted": "#2e2e2e",
                "error": "#9e0000",
                "focus": "#000000",
            },
            "dark": {
                "accent": "#ffd75e",
                "background": "#000000",
                "surface": "#000000",
                "text": "#ffffff",
                "muted": "#e0e0e0",
                "error": "#ff9d9d",
                "focus": "#ffffff",
            },
        },
        "baseSize": 18,
        "lineSpacing": 1.6,
        "radius": 4,
        "buttonStyle": "outline",
        "choiceStyle": "buttons",
    },
    "dark": {
        "preset": "dark",
        "colours": {
            "light": _CLEAN_LIGHT,
            "dark": {
                "accent": "#9db8ff",
                "background": "#0f1115",
                "surface": "#181b21",
                "text": "#eceef2",
                "muted": "#adb4c0",
                "error": "#ff8a80",
                "focus": "#c3d3ff",
            },
        },
        "mode": "dark",
        "choiceStyle": "cards",
    },
    "compact": {
        "preset": "compact",
        "colours": {"light": _CLEAN_LIGHT, "dark": _CLEAN_DARK},
        "lineSpacing": 1.4,
        "radius": 4,
        "density": "compact",
    },
}

#: The five built-in presets, in display order.
PRESETS: dict[str, Theme] = {k: Theme.model_validate(v) for k, v in _PRESET_DATA.items()}

PRESET_NAMES: dict[str, str] = {
    "clean": "Clean",
    "warm": "Warm",
    "high-contrast": "High contrast",
    "dark": "Dark",
    "compact": "Compact",
}
