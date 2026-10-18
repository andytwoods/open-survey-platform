"""Rich text (planning/rich-text.md §3): levels, limits, walking, counting, normalising
and flattening the tree. Pure functions over the JSON form (and over the model classes,
which are converted to JSON first). No I/O.

A `Text` value is a plain string, a tree `{"type": "rich", "blocks": [...]}` or a
`{language: string | tree}` map (`osp_spec.model.Text`). Every participant-facing field
has a **level** that says how much of the tree it may hold and how long it may be:

| level  | allowed                                           | limit  |
|--------|---------------------------------------------------|--------|
| block  | paragraphs, headings 1–3, lists, marks, links, pipes, breaks | 20 000 |
| stem   | as block but no headings (a stem is a label)      |  2 000 |
| inline | exactly one paragraph; marks, links, pipes, breaks|    500 |
| plain  | a string only (`PlainText` in the model)          |      – |

The limits count text characters per field per language; pipes count 0. The validator
(`osp_spec.validate`) applies them to plain strings too.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from typing import Any, Literal

from pydantic import BaseModel

from .diagnostics import pointer

type Level = Literal["block", "stem", "inline"]
type Json = Any

LEVELS: tuple[Level, ...] = ("block", "stem", "inline")
LIMITS: dict[Level, int] = {"block": 20_000, "stem": 2_000, "inline": 500}
MAX_BLOCKS = 200
MAX_LIST_ITEMS = 100

_PIPE = re.compile(r"\$\{([^}]*)\}")

# Fields whose level is not the family default (see `text_level`).
_EXPLICIT: dict[tuple[str, str], Level] = {
    ("Metadata", "description"): "block",
    ("Consent", "text"): "block",
    ("Consent", "agreeLabel"): "inline",
    ("Consent", "declineLabel"): "inline",
    ("EndNode", "message"): "block",
    ("Ending", "title"): "inline",
    ("Ending", "body"): "block",
    ("EndRedirect", "label"): "inline",
    ("NoteQuestion", "label"): "block",
    ("Choice", "label"): "inline",
    ("MatrixRow", "label"): "inline",
    ("Page", "title"): "inline",
    ("SliderQuestion", "minLabel"): "inline",
    ("SliderQuestion", "maxLabel"): "inline",
}


def text_level(owner: type[BaseModel] | str, field: str) -> Level | None:
    """The rich-text level of `field` on the model class `owner` (a class or its name), or
    None for a field that holds no `Text` (ids, titles that are `PlainText`, hook strings).

    Defaults by field name: `label` and `help` are `stem` (a note's label is `block`),
    `constraintMessage` is `inline`; everything else is listed in `_EXPLICIT`.
    """
    name = owner if isinstance(owner, str) else owner.__name__
    if (name, field) in _EXPLICIT:
        return _EXPLICIT[name, field]
    if name.endswith("Question") and field in ("label", "help"):
        return "stem"
    if name.endswith("Question") and field == "constraintMessage":
        return "inline"
    return None


# --- Shape helpers -------------------------------------------------------------------------


def _json(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    return value


def is_rich(value: Any) -> bool:
    """True for a rich tree (the JSON form or the `RichText` model)."""
    value = _json(value)
    return isinstance(value, Mapping) and value.get("type") == "rich" and "blocks" in value


def _content_of(block: Mapping[str, Any]) -> list[tuple[tuple[str | int, ...], list[Any]]]:
    """(path, inline list) pairs of a block: one for a paragraph or heading, one per item
    of a list. Tolerant of malformed input (returns what is list-shaped)."""
    if block.get("type") in ("ul", "ol"):
        items = block.get("items")
        if not isinstance(items, list):
            return []
        return [(("items", i), run) for i, run in enumerate(items) if isinstance(run, list)]
    content = block.get("content")
    return [(("content",), content)] if isinstance(content, list) else []


def inline_paths(tree: Any) -> Iterator[tuple[tuple[str | int, ...], Any]]:
    """Every inline node of a tree with its path from the tree root
    (`("blocks", 0, "content", 3)` or `("blocks", 1, "items", 0, 2)`), in reading order."""
    tree = _json(tree)
    blocks = tree.get("blocks") if isinstance(tree, Mapping) else None
    if not isinstance(blocks, list):
        return
    for b, block in enumerate(blocks):
        if not isinstance(block, Mapping):
            continue
        for sub, runs in _content_of(block):
            for i, node in enumerate(runs):
                yield ("blocks", b, *sub, i), node


def pipes_of(tree: Any) -> Iterator[tuple[tuple[str | int, ...], str]]:
    """`(path, id)` of every pipe node of a tree."""
    for path, node in inline_paths(tree):
        if isinstance(node, Mapping) and isinstance(node.get("pipe"), str):
            yield path, node["pipe"]


def has_pipes(value: Any) -> bool:
    """Whether a text (plain, rich or per language) pipes anything."""
    value = _json(value)
    if isinstance(value, str):
        return bool(_PIPE.search(value))
    if is_rich(value):
        return any(True for _ in pipes_of(value))
    if isinstance(value, Mapping):
        return any(has_pipes(v) for v in value.values())
    return False


def char_count(value: Any) -> int:
    """Text characters of one plain string or tree: pipes count 0, breaks count 0."""
    value = _json(value)
    if isinstance(value, str):
        return len(_PIPE.sub("", value))
    n = 0
    for _, node in inline_paths(value):
        if isinstance(node, Mapping) and isinstance(node.get("text"), str):
            n += len(node["text"])
    return n


FEATURES = ("bold", "italic", "link", "heading", "list", "break", "lang")


def features(tree: Any) -> set[str]:
    """Which formatting features a tree uses (`FEATURES` names), for export diagnostics."""
    tree = _json(tree)
    out: set[str] = set()
    for block in tree.get("blocks", []) if isinstance(tree, Mapping) else []:
        if not isinstance(block, Mapping):
            continue
        if block.get("type") == "h":
            out.add("heading")
        elif block.get("type") in ("ul", "ol"):
            out.add("list")
    for _, node in inline_paths(tree):
        if not isinstance(node, Mapping):
            continue
        if node.get("br") is True:
            out.add("break")
        marks = node.get("marks") or []
        if "b" in marks:
            out.add("bold")
        if "i" in marks:
            out.add("italic")
        if node.get("href"):
            out.add("link")
        if node.get("lang"):
            out.add("lang")
    return out


# --- Validation ----------------------------------------------------------------------------

type Emit = Callable[[str, str, str], None]


def check_rich(tree: Any, level: Level, ptr: str, emit: Emit) -> list[tuple[str, str]]:
    """The level, link and size rules for one (structurally valid) tree at `ptr`.

    Emits `text.block_not_allowed`, `text.too_many_blocks`, `link.scheme` and `link.empty`
    through `emit(code, pointer, message)`. Returns `(pointer, id)` for every pipe node, so
    the caller checks references exactly as for `${id}` in a plain string. `text.too_long`
    is the caller's (it applies to plain strings too: `char_count`).
    """
    tree = _json(tree)
    blocks = tree.get("blocks", []) if isinstance(tree, Mapping) else []
    if len(blocks) > MAX_BLOCKS:
        emit("text.too_many_blocks", ptr, f"{len(blocks)} blocks; at most {MAX_BLOCKS}")
    if level == "inline" and len(blocks) > 1:
        emit(
            "text.block_not_allowed",
            ptr + "/blocks",
            f"{len(blocks)} blocks in a one-line field; only one paragraph is allowed",
        )
    for b, block in enumerate(blocks):
        bp = ptr + pointer("blocks", b)
        kind = block.get("type") if isinstance(block, Mapping) else None
        if kind == "h" and level != "block":
            emit(
                "text.block_not_allowed",
                bp,
                "a heading is only allowed in notes, descriptions, consent and ending text",
            )
        elif kind in ("ul", "ol"):
            if level == "inline":
                emit("text.block_not_allowed", bp, "a list is not allowed in a one-line field")
            items = block.get("items") if isinstance(block, Mapping) else None
            if isinstance(items, list) and len(items) > MAX_LIST_ITEMS:
                emit(
                    "text.too_many_blocks",
                    bp + "/items",
                    f"{len(items)} list items; at most {MAX_LIST_ITEMS}",
                )
    pipes: list[tuple[str, str]] = []
    for path, node in inline_paths(tree):
        np = ptr + pointer(*path)
        if not isinstance(node, Mapping):
            continue
        if isinstance(node.get("pipe"), str):
            pipes.append((np, node["pipe"]))
            continue
        href = node.get("href")
        if href is None:
            continue
        if not isinstance(href, str) or not _https(href):
            emit("link.scheme", np + "/href", "a link must be an absolute https: URL")
        if not isinstance(node.get("text"), str) or node["text"] == "":
            emit("link.empty", np, "a link needs text")
    return pipes


def _https(href: str) -> bool:
    return href.startswith("https://") and len(href) > len("https://") and " " not in href


# --- Normalisation and flattening -------------------------------------------------------


def _run_plain(node: Any) -> str | None:
    """A run as plain text when it carries no formatting, else None."""
    if not isinstance(node, Mapping):
        return None
    if isinstance(node.get("pipe"), str) and len(node) == 1:
        return "${" + node["pipe"] + "}"
    if isinstance(node.get("text"), str) and set(node) - {"text", "marks"} == set():
        return node["text"] if not node.get("marks") else None
    return None


def normalise_text(value: Json) -> Json:
    """Rich text with **no formatting** (one paragraph; no marks, links, breaks, headings,
    lists or language spans) as the plain string it is, with pipes written back as `${id}`
    (planning/rich-text.md §3.3, RT-D3). An empty tree is `""`. Plain strings, formatted
    trees and anything that is not a text come back unchanged; a per-language map is
    normalised value by value. Never raises."""
    if isinstance(value, Mapping) and is_rich(value):
        blocks = value.get("blocks")
        if not isinstance(blocks, list):
            return value
        if not blocks:
            return ""
        if len(blocks) != 1:
            return value
        block = blocks[0]
        if not isinstance(block, Mapping) or block.get("type") != "p":
            return value
        content = block.get("content")
        if not isinstance(content, list):
            return value
        parts = [_run_plain(n) for n in content]
        if any(p is None for p in parts):
            return value
        return "".join(p for p in parts if p is not None)
    if isinstance(value, Mapping):
        return {k: normalise_text(v) for k, v in value.items()}
    return value


def to_plain(value: Any) -> str:
    """One plain string or tree flattened to text: runs joined, pipes as `${id}`, breaks
    as newlines, blocks separated by a blank line, list items on their own lines with
    `- ` or `1. ` markers, headings as their text. For exports that cannot carry
    formatting, codebooks, accessible names and search."""
    value = _json(value)
    if isinstance(value, str):
        return value
    if not isinstance(value, Mapping):
        return ""
    out: list[str] = []
    for block in value.get("blocks", []) or []:
        if not isinstance(block, Mapping):
            continue
        kind = block.get("type")
        if kind in ("ul", "ol"):
            lines = []
            for i, run in enumerate(block.get("items") or []):
                marker = f"{i + 1}. " if kind == "ol" else "- "
                lines.append(marker + _runs_plain(run))
            out.append("\n".join(lines))
        else:
            out.append(_runs_plain(block.get("content")))
    return "\n\n".join(out)


def _runs_plain(runs: Any) -> str:
    if not isinstance(runs, list):
        return ""
    parts: list[str] = []
    for node in runs:
        if not isinstance(node, Mapping):
            continue
        if isinstance(node.get("text"), str):
            parts.append(node["text"])
        elif isinstance(node.get("pipe"), str):
            parts.append("${" + node["pipe"] + "}")
        elif node.get("br") is True:
            parts.append("\n")
    return "".join(parts)


def flatten_text(value: Any) -> str | dict[str, str] | None:
    """A `Text` with every rich value flattened by `to_plain`: a plain string, or a
    `{language: string}` map. None stays None. The shape every pre-RT4 writer expects."""
    value = _json(value)
    if value is None or isinstance(value, str):
        return value
    if is_rich(value):
        return to_plain(value)
    if isinstance(value, Mapping):
        return {k: (to_plain(v) if is_rich(v) else v) for k, v in value.items()}
    return value


def plain_text(value: Any, lang: str | None = None) -> str:
    """One string for a `Text`: the given language, else the first; rich flattened."""
    flat = flatten_text(value)
    if flat is None:
        return ""
    if isinstance(flat, str):
        return flat
    if lang is not None and isinstance(flat.get(lang), str):
        return flat[lang]
    first = next(iter(flat.values()), "")
    return first if isinstance(first, str) else ""


__all__ = [
    "FEATURES",
    "LEVELS",
    "LIMITS",
    "MAX_BLOCKS",
    "MAX_LIST_ITEMS",
    "Level",
    "char_count",
    "check_rich",
    "features",
    "flatten_text",
    "has_pipes",
    "inline_paths",
    "is_rich",
    "normalise_text",
    "pipes_of",
    "plain_text",
    "text_level",
    "to_plain",
]
