"""osp-instruments (layer L2): the bundled library of validated instruments
(planning/question-bank.md §3, §7).

One `osp-bank-item/0.1` document per instrument under `library/<id>.json`, read from the
package's own data and nothing else (no other I/O). Only instruments whose item text may
be redistributed are here: every document's `licence.class` must be in
`licence-policy.toml` `[instruments] allowed`, and its `licence` quotes the holder's terms
with the URL and the date they were read. `LICENCES.md` is generated from the library
(`licences_markdown()`; a test keeps it current).
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

from osp_spec import Source
from osp_spec.bank import BankItem, instrument_entry

from .compose import ComposeRequest, compose_fragment, parse_items, prefix_from, request_from_stub
from .stubs import InstrumentStub, load_stub, load_stub_document, load_stubs, stub_ids

LIBRARY = "library"


@cache
def _documents() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    root = resources.files(__package__).joinpath(LIBRARY)
    for entry in sorted(root.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".json"):
            doc = json.loads(entry.read_text(encoding="utf-8"))
            out[doc["id"]] = doc
    return out


def library_ids() -> list[str]:
    return sorted(_documents())


def load_document(instrument_id: str) -> dict[str, Any] | None:
    """The raw bank item document (a fresh copy), or None."""
    doc = _documents().get(instrument_id)
    return json.loads(json.dumps(doc)) if doc is not None else None


def load_library() -> list[BankItem]:
    """Every bundled instrument as a validated `BankItem`, in id order."""
    return [BankItem.model_validate(_documents()[i]) for i in library_ids()]


def lookup(source: Source) -> dict[str, Any] | None:
    """For `osp_spec.bank.with_instruments`: the description of a bundled source."""
    if source.library != "bundled":
        return None
    doc = _documents().get(source.bank)
    if doc is None or doc.get("version") != source.version:
        return None
    return instrument_entry(doc)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def licences_markdown() -> str:
    """LICENCES.md: every bundled instrument, its holder, class, terms page, access date
    and the operative sentence quoted from the holder."""
    out = [
        "# Bundled instruments: licences and evidence",
        "",
        "Generated from `src/osp_instruments/library/*.json` by",
        "`osp_instruments.licences_markdown()`; `tests/test_library.py` fails when this file is",
        "stale. Each statement was read on the rights holder's page on the date given",
        "(planning/question-bank.md §7, lead decision 7). Only the classes in",
        "`licence-policy.toml` `[instruments] allowed` may appear here.",
        "",
        "| Id | Instrument | Class | Holder | Terms page (read on) |",
        "|---|---|---|---|---|",
    ]
    docs = [_documents()[i] for i in library_ids()]
    for d in docs:
        lic = d["licence"]
        out.append(
            f"| `{d['id']}` | {_cell(d.get('abbreviation') or d['title'])} | `{lic['class']}` | "
            f"{_cell(lic.get('holder') or '')} | {lic['url']} ({lic['evidenceDate']}) |"
        )
    out.append("")
    for d in docs:
        lic = d["licence"]
        out += [
            f"## {_cell(d['title'])} (`{d['id']}`)",
            "",
            f"- Holder: {lic.get('holder') or 'not stated'}",
            f"- Class: `{lic['class']}`",
            f"- Terms page: {lic['url']}, read {lic['evidenceDate']}",
            f"- Item text from: {d['source']['url']}",
            f"- Citation: {d['citation']['text']}"
            + (f" doi:{d['citation']['doi']}" if d["citation"].get("doi") else ""),
            "",
            f"> {lic['statement']}",
            "",
        ]
    return "\n".join(out)


__all__ = [
    "ComposeRequest",
    "InstrumentStub",
    "compose_fragment",
    "library_ids",
    "licences_markdown",
    "load_document",
    "load_library",
    "load_stub",
    "load_stub_document",
    "load_stubs",
    "lookup",
    "parse_items",
    "prefix_from",
    "request_from_stub",
    "stub_ids",
]
