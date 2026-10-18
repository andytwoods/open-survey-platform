"""What the rich-text writers share (planning/rich-text.md §8, task RT4): the JSON form of
a `Text`, node paths, and the grouping of adjacent runs that make one link. Pure, no I/O.
The target-specific writers are `xlsform/markdown.py` and `lss/html.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from typing import Any

from pydantic import BaseModel

# A node's path inside a rich tree, e.g. ("blocks", 0, "content", 2); the exporter turns it
# into a JSON pointer below the field's pointer.
type Path = tuple[str | int, ...]
# A pipe node (its id and path) → the target's text for it.
type Pipe = Callable[[str, Path], str]
# A capability key and the path of the node it is about.
type Report = Callable[[str, Path], None]


def as_json(text: object) -> Any:
    """A `Text` (plain, rich or per language; model classes or JSON) in its JSON form."""
    if isinstance(text, BaseModel):
        return text.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(text, Mapping):
        return {k: as_json(v) for k, v in text.items()}
    return text


def heading_level(block: Mapping[str, Any]) -> int:
    """A heading's level clamped to 1–3 (the model allows nothing else; tolerant of input)."""
    level = block.get("level")
    return min(max(level, 1), 3) if isinstance(level, int) else 1


def link_groups(runs: Any) -> Iterator[tuple[str | None, list[tuple[int, Any]]]]:
    """The runs of one paragraph, heading or list item grouped by link: adjacent runs with
    the same `href` are one link (§3.1); every other run is a group of its own with
    `href` None. Each run comes with its index in `runs`."""
    if not isinstance(runs, list):
        return
    i = 0
    while i < len(runs):
        node = runs[i]
        href = node.get("href") if isinstance(node, Mapping) else None
        if not isinstance(href, str) or not href:
            yield None, [(i, node)]
            i += 1
            continue
        j = i
        while j < len(runs) and isinstance(runs[j], Mapping) and runs[j].get("href") == href:
            j += 1
        yield href, [(k, runs[k]) for k in range(i, j)]
        i = j


__all__ = ["Path", "Pipe", "Report", "as_json", "heading_level", "link_groups"]
