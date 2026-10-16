"""CSV export of responses (semantics §1, §7, §9). Pure: bytes in memory, no I/O.

- One row per response, ordered by submission time then response id, so the same input
  always gives byte-identical output.
- Missing values are an **empty cell** plus ``<var>__state``; never ``-99``-style codes.
- RFC 4180: CRLF line ends, fields with ``,`` ``"`` CR or LF quoted, quotes doubled.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Sequence
from typing import Any

from .layout import Column, Layout, build_layout, csv_columns
from .model import CsvOptions, StoredResponse, SurveyVersion
from .view import ResponseView

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_PLAIN_NUMBER = re.compile(r"-?[0-9]+(\.[0-9]+)?")


def fmt(value: Any) -> str:
    """A cell's text. Integers and decimal strings print as stored (decimals stay exact
    text, semantics §2); booleans as true/false; a list as space-separated items."""
    match value:
        case None:
            return ""
        case bool():
            return "true" if value else "false"
        case int() | str():
            return str(value)
        case float():
            return repr(value)
        case list() | tuple():
            return " ".join(fmt(v) for v in value)
        case _:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def escape_formula(cell: str) -> str:
    """Prefix ``'`` to a cell a spreadsheet would run as a formula (OWASP CSV injection).
    Plain numbers such as ``-3`` and ``-2.5`` are data, not formulas, and stay as they are."""
    if cell.startswith(_FORMULA_START) and not _PLAIN_NUMBER.fullmatch(cell):
        return "'" + cell
    return cell


def _write(headers: list[str], rows: list[list[str]], opts: CsvOptions) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    w.writerow(headers)
    for row in rows:
        w.writerow([escape_formula(c) if opts.escape_formulas else c for c in row])
    text = buf.getvalue()
    return ("﻿" if opts.bom else "").encode("utf-8") + text.encode("utf-8")


def _views(
    lay: Layout, version: SurveyVersion, responses: Sequence[StoredResponse]
) -> list[ResponseView]:
    views = [ResponseView(r, lay, version.save_mode) for r in responses]
    return sorted(views, key=ResponseView.sort_key)


def _row(cols: list[Column], view: ResponseView) -> list[str]:
    return [fmt(c.cell(view)) for c in cols]


def export_csv(
    version: SurveyVersion,
    responses: Sequence[StoredResponse],
    options: CsvOptions | None = None,
) -> bytes:
    """One version's responses as CSV. Raises ``ExportError`` (with diagnostics) only for
    an invalid survey or clashing column names."""
    opts = options or CsvOptions()
    lay = build_layout(version)
    cols = csv_columns(lay, opts)
    rows = [_row(cols, v) for v in _views(lay, version, responses)]
    return _write([c.header for c in cols], rows, opts)


def export_csv_combined(
    versions: Sequence[tuple[SurveyVersion, Sequence[StoredResponse]]],
    options: CsvOptions | None = None,
) -> bytes:
    """Several versions in one file: the union of their columns (first appearance, versions
    in ascending number), ``_version`` on every row. A column a version does not have is
    empty in its rows, *including* its ``__state`` cell (the codebook says so). Rows are
    grouped by version, then ordered as in ``export_csv``. One version gives exactly the
    single-version export."""
    opts = options or CsvOptions()
    ordered = sorted(versions, key=lambda vr: _version_key(vr[0]))
    headers: list[str] = []
    seen: set[str] = set()
    per_version: list[tuple[dict[str, Column], list[ResponseView]]] = []
    for version, responses in ordered:
        lay = build_layout(version)
        cols = csv_columns(lay, opts)
        for c in cols:
            if c.header not in seen:
                seen.add(c.header)
                headers.append(c.header)
        per_version.append(({c.header: c for c in cols}, _views(lay, version, responses)))
    rows: list[list[str]] = []
    for by_header, views in per_version:
        for v in views:
            rows.append([fmt(by_header[h].cell(v)) if h in by_header else "" for h in headers])
    return _write(headers, rows, opts)


def _version_key(version: SurveyVersion) -> tuple[int, str]:
    return (version.number if version.number is not None else 0, version.checksum or "")
