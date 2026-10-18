"""Rich text → the HTML subset LimeSurvey texts carry (planning/rich-text.md §8, task RT4):
`<p>`, `<h3>`–`<h5>`, `<ul>`/`<ol>`/`<li>`, `<strong>`, `<em>`, `<a href target rel>`,
`<span lang>`, `<br />`. Every piece of text goes through the exporter's escaper (HTML
entities, Expression Manager braces), so the output holds only our own tags. Pure.
"""

from __future__ import annotations

import html
from collections.abc import Callable, Mapping
from typing import Any

from ..richtext import Path, Pipe, Report, heading_level, link_groups

# A text run (and its path) → the escaped text, with the exporter's own diagnostics.
type Escape = Callable[[str, Path], str]

BLOCK_TAGS = ("<p>", "<h3>", "<h4>", "<h5>", "<ul>", "<ol>")


def to_html(tree: Mapping[str, Any], escape: Escape, pipe: Pipe, report: Report) -> str:
    """One rich tree as HTML. A lone paragraph has no `<p>` wrapper (as the engine's
    `toHtml`), so one-line fields stay one line. Tolerant of malformed input."""
    blocks = tree.get("blocks") if isinstance(tree, Mapping) else None
    blocks = blocks if isinstance(blocks, list) else []
    out: list[str] = []
    for b, block in enumerate(blocks):
        if not isinstance(block, Mapping):
            continue
        kind = block.get("type")
        base: Path = ("blocks", b)
        if kind == "h":
            tag = f"h{heading_level(block) + 2}"  # under the page's own heading
            runs = _runs(block.get("content"), (*base, "content"), escape, pipe, report)
            out.append(f"<{tag}>{runs}</{tag}>")
        elif kind in ("ul", "ol"):
            items = block.get("items")
            lis = "".join(
                f"<li>{_runs(item, (*base, 'items', i), escape, pipe, report)}</li>"
                for i, item in enumerate(items if isinstance(items, list) else [])
            )
            out.append(f"<{kind}>{lis}</{kind}>")
        else:
            runs = _runs(block.get("content"), (*base, "content"), escape, pipe, report)
            if len(blocks) == 1:
                return runs
            out.append(f"<p>{runs}</p>")
    return "".join(out)


def is_block_html(text: str) -> bool:
    """Whether a rendered text already starts with one of our block elements (so a writer
    that wraps texts in `<p>` leaves it alone)."""
    return text.startswith(BLOCK_TAGS)


def _runs(runs: Any, base: Path, escape: Escape, pipe: Pipe, report: Report) -> str:
    out: list[str] = []
    for href, group in link_groups(runs):
        inner = "".join(_run(node, (*base, i), escape, pipe, report) for i, node in group)
        if href is not None and href.startswith("https://"):
            attr = html.escape(href, quote=True)
            inner = f'<a href="{attr}" target="_blank" rel="noopener noreferrer">{inner}</a>'
        out.append(inner)
    return "".join(out)


def _run(node: Any, path: Path, escape: Escape, pipe: Pipe, report: Report) -> str:
    if not isinstance(node, Mapping):
        return ""
    if node.get("br") is True:
        return "<br />"
    if isinstance(node.get("pipe"), str):
        return pipe(node["pipe"], path)
    text = node.get("text")
    if not isinstance(text, str):
        return ""
    out = escape(text, path)
    marks = node.get("marks")
    marks = marks if isinstance(marks, list) else []
    if "i" in marks:
        out = f"<em>{out}</em>"
    if "b" in marks:
        out = f"<strong>{out}</strong>"
    lang = node.get("lang")
    if isinstance(lang, str) and lang:
        out = f'<span lang="{html.escape(lang, quote=True)}">{out}</span>'
    return out


__all__ = ["BLOCK_TAGS", "Escape", "is_block_html", "to_html"]
