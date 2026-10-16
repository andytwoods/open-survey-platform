"""Write the ``.lss`` XML document: a ``<document>`` of tables, each a ``<fields>`` list and
``<rows>``, every value in CDATA (the layout of our hand-written spike file,
``spikes/spike-1/survey/spike1.lss``). Deterministic: tables, fields and rows are written
in the order given, with no timestamps.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

# Characters XML 1.0 does not allow (tab, LF and CR are allowed).
_INVALID_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")

type Value = str | int | None


@dataclass
class Table:
    name: str
    fields: Sequence[str]
    rows: list[dict[str, Value]] = field(default_factory=list)

    def add(self, **values: Value) -> None:
        unknown = set(values) - set(self.fields)
        if unknown:  # pragma: no cover - programming error
            raise KeyError(f"{self.name}: unknown fields {sorted(unknown)}")
        self.rows.append(values)


def cdata(text: str) -> str:
    text = _INVALID_XML.sub("", text)
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def write_document(
    header: Sequence[tuple[str, str]],
    languages: Sequence[str],
    tables: Sequence[Table],
    comment: str = "",
) -> bytes:
    out: list[str] = ['<?xml version="1.0" encoding="UTF-8"?>']
    if comment:
        out.append("<!-- " + comment.replace("--", "- -") + " -->")
    out.append("<document>")
    for tag, value in header:
        out.append(f" <{tag}>{value}</{tag}>")
    out.append(" <languages>")
    out.extend(f"  <language>{lang}</language>" for lang in languages)
    out.append(" </languages>")
    for table in tables:
        if not table.rows:
            continue
        out.append(f" <{table.name}>")
        out.append("  <fields>")
        out.extend(f"   <fieldname>{f}</fieldname>" for f in table.fields)
        out.append("  </fields>")
        out.append("  <rows>")
        for row in table.rows:
            out.append("   <row>")
            for f in table.fields:
                v = row.get(f)
                if v is None or v == "":
                    out.append(f"    <{f}/>")
                else:
                    out.append(f"    <{f}>{cdata(str(v))}</{f}>")
            out.append("   </row>")
        out.append("  </rows>")
        out.append(f" </{table.name}>")
    out.append("</document>")
    return ("\n".join(out) + "\n").encode("utf-8")


__all__ = ["Table", "cdata", "write_document"]
