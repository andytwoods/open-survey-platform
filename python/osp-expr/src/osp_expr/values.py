"""Answer-value rules shared with the browser engine (planning/semantics.md §2).

Both constants and both functions have an exact twin in `web/engine/src/values.ts`, and
both sides are tested against the same vector files in `contract/vectors/`
(`trim.json`, `decimal.json`), so Python and TypeScript cannot drift apart.

- **Trimming** removes the Unicode `White_Space` characters plus U+FEFF (the byte-order
  mark) from both ends, and nothing else: not the zero-width space U+200B, and not the
  C0 separators U+001C-U+001F that Python's `str.strip()` also removes. Text is never
  Unicode-normalised; the raw text is kept.
- **Decimals** are stored and exported in canonical form: no exponent, no leading `+`,
  no superfluous leading zeros, no trailing zeros after the point, `0` for any zero
  (`2.50` -> `2.5`, `-0.0` -> `0`, `.5` -> `0.5`, `1E+2` -> `100`). Input with more than
  `DECIMAL_DIGITS` significant digits is rejected, because arithmetic keeps 28.
"""

from __future__ import annotations

import re
from decimal import Context, Decimal, InvalidOperation

TRIM_CODE_POINTS: tuple[int, ...] = (
    *range(0x0009, 0x000E),  # TAB, LF, VT, FF, CR
    0x0020,  # SPACE
    0x0085,  # NEXT LINE
    0x00A0,  # NO-BREAK SPACE
    0x1680,  # OGHAM SPACE MARK
    *range(0x2000, 0x200B),  # EN QUAD ... HAIR SPACE (not U+200B ZERO WIDTH SPACE)
    0x2028,  # LINE SEPARATOR
    0x2029,  # PARAGRAPH SEPARATOR
    0x202F,  # NARROW NO-BREAK SPACE
    0x205F,  # MEDIUM MATHEMATICAL SPACE
    0x3000,  # IDEOGRAPHIC SPACE
    0xFEFF,  # ZERO WIDTH NO-BREAK SPACE (byte-order mark)
)
"""Unicode White_Space (Unicode 15.1, PropList.txt) plus U+FEFF. Never U+200B."""

TRIM_CHARS = "".join(map(chr, TRIM_CODE_POINTS))

DECIMAL_DIGITS = 28
"""Most significant digits a decimal answer may have (the arithmetic precision)."""

# Decimal text a participant (or a fixture) may type: an optional sign, digits with an
# optional point. No exponent, no thousands separators.
_DECIMAL_INPUT = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")

# normalize() rounds to its context's precision: use one wide enough never to round.
_WIDE = Context(prec=1_000_000, Emax=999_999_999, Emin=-999_999_999)


def trim(text: str) -> str:
    """Remove `TRIM_CHARS` from both ends of `text`."""
    return text.strip(TRIM_CHARS)


def canonical_decimal(value: str | int | Decimal) -> str | None:
    """The canonical text of a decimal, or None if it is not one or is too long.

    Text input must match `[+-]digits[.digits]` after trimming (no exponent). A
    `Decimal` or `int` is formatted the same way. More than `DECIMAL_DIGITS`
    significant digits (after dropping leading and trailing zeros) gives None.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = trim(value)
        if not _DECIMAL_INPUT.match(text):
            return None
        try:
            d = Decimal(text)
        except InvalidOperation:  # pragma: no cover - the pattern rules it out
            return None
    elif isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, Decimal):
        if not value.is_finite():
            return None
        d = value
    else:
        return None
    if d.is_zero():
        return "0"
    d = d.normalize(_WIDE)
    if len(d.as_tuple().digits) > DECIMAL_DIGITS:
        return None
    return format(d, "f")


__all__ = ["DECIMAL_DIGITS", "TRIM_CHARS", "TRIM_CODE_POINTS", "canonical_decimal", "trim"]
