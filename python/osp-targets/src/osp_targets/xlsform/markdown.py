"""Rich text → the Markdown subset XLSForm labels carry in Enketo and ODK Collect
(planning/rich-text.md §8, task RT4). Pure functions over the JSON form of a rich tree.

The rules come from the XLSForm/ODK docs ("Styling prompts", "Escaping Markdown") and from
reading Enketo's transformer (MIT; learned from, not copied):

- `**bold**`; `*italic*` (`*` works inside a word, `_` only between white space); bold and
  italic together as `*__text__*`; `[text](https://url)`; `#`…`#####` at the start of a line
  is a heading; `- item` lines are a bulleted list and `1. item` lines after a newline a
  numbered one; `\\n` is a line break and a blank line a paragraph break.
- A literal `\\`, `*`, `_` or `#` is written with a backslash in front and shows as written.
  `<`, `>`, the link syntax and a list marker at the start of a line have no escape
  (`$text.markup`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ..richtext import Path, Pipe, Report, heading_level, link_groups

_ESCAPE = re.compile(r"[\\*_#]")
_PIPE = re.compile(r"\$\{([^}]*)\}")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# What a backslash cannot escape and Enketo or Collect may still render as markup: tags,
# the link syntax, and a bullet or number at the start of a line (a `*` there is escaped).
UNESCAPABLE = re.compile(r"[<>]|\[[^\]]*\]\([^)]*\)|(?:^|\n)[ \t]*(?:[-+]|\d+\.) ")


def escape(text: str) -> str:
    """Literal `\\ * _ #` escaped with a backslash, so Enketo and Collect show them."""
    return _ESCAPE.sub(lambda m: "\\" + m.group(0), text)


def escape_plain(text: str) -> str:
    """A plain string escaped outside its `${id}` pipes (the ids stay as they are)."""
    out: list[str] = []
    pos = 0
    for m in _PIPE.finditer(text):
        out.append(escape(text[pos : m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(escape(text[pos:]))
    return "".join(out)


def to_markdown(tree: Mapping[str, Any], pipe: Pipe, report: Report) -> str:
    """One rich tree as Markdown. `pipe` writes each pipe node; `report` receives the
    capability key and path of anything approximated (`$rich.listBreak`,
    `$rich.linkSyntax`, `$text.markup`, `$text.controlCharacters`). Tolerant of malformed
    input: what is not tree-shaped is skipped."""
    blocks = tree.get("blocks") if isinstance(tree, Mapping) else None
    out: list[str] = []
    for b, block in enumerate(blocks if isinstance(blocks, list) else []):
        if not isinstance(block, Mapping):
            continue
        kind = block.get("type")
        base: Path = ("blocks", b)
        if kind == "h":
            hashes = "#" * (heading_level(block) + 1)  # `#` is the form title's size
            runs = _runs(block.get("content"), (*base, "content"), pipe, report, in_list=False)
            out.append(f"{hashes} {runs}")
        elif kind in ("ul", "ol"):
            items = block.get("items")
            lines = []
            for i, item in enumerate(items if isinstance(items, list) else []):
                marker = f"{i + 1}. " if kind == "ol" else "- "
                lines.append(marker + _runs(item, (*base, "items", i), pipe, report, in_list=True))
            text = "\n".join(lines)
            if kind == "ol" and not out:
                text = "\n" + text  # Enketo reads a numbered list only after a newline
            out.append(text)
        else:
            out.append(_runs(block.get("content"), (*base, "content"), pipe, report, in_list=False))
    return "\n\n".join(out)


def _runs(runs: Any, base: Path, pipe: Pipe, report: Report, *, in_list: bool) -> str:
    out: list[str] = []
    for href, group in link_groups(runs):
        inner = "".join(_run(node, (*base, i), pipe, report, in_list) for i, node in group)
        if href is None:
            out.append(inner)
        elif "]" in inner or ")" in href or "\n" in inner:
            # `[text](url)` cannot hold them: the text, then the URL in parentheses.
            report("$rich.linkSyntax", (*base, group[0][0]))
            out.append(f"{inner} ({href})")
        else:
            out.append(f"[{inner}]({href})")
    return "".join(out)


def _run(node: Any, path: Path, pipe: Pipe, report: Report, in_list: bool) -> str:
    if not isinstance(node, Mapping):
        return ""
    if node.get("br") is True:
        if in_list:
            report("$rich.listBreak", path)
            return " "
        return "\n"
    if isinstance(node.get("pipe"), str):
        return pipe(node["pipe"], path)
    text = node.get("text")
    if not isinstance(text, str):
        return ""
    if CONTROL.search(text):
        report("$text.controlCharacters", path)
    if UNESCAPABLE.search(text):
        report("$text.markup", path)
    if in_list and "\n" in text:
        report("$rich.listBreak", path)
        text = text.replace("\n", " ")
    marks = node.get("marks")
    marks = marks if isinstance(marks, list) else []
    return "\n".join(_marked(line, marks) for line in text.split("\n"))


def _marked(line: str, marks: list[Any]) -> str:
    """One line of a run with its marks: the markers hug the text (Enketo and Collect do
    not read `* text*`), white space stays outside them."""
    core = line.strip()
    if not core or not marks:
        return escape(line)
    lead = line[: len(line) - len(line.lstrip())]
    trail = line[len(line.rstrip()) :]
    core = escape(core)
    bold, italic = "b" in marks, "i" in marks
    if bold and italic:
        core = f"*__{core}__*"
    elif bold:
        core = f"**{core}**"
    elif italic:
        core = f"*{core}*"
    return lead + core + trail


__all__ = ["CONTROL", "UNESCAPABLE", "escape", "escape_plain", "to_markdown"]
