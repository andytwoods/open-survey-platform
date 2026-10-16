"""Per-target capability tables (planning/review.md §2.4), kept as data.

A table maps a model feature to how a target handles it. Keys are
``"<SchemaDef>.<field>"`` for every field of every object in the ``osp-survey`` JSON
Schema (``Survey.<field>`` for the root), optionally refined by value as
``"<SchemaDef>.<field>=<value>"`` when one value behaves differently (for example
``"Page.itemOrder=shuffle"``). A completeness test fails when a schema field has no row.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import LEVELS, Capability, Level
from .xlsform import XLSFORM

TABLES: dict[str, dict[str, Capability]] = {"xlsform": XLSFORM}


def schema_fields(schema: Mapping[str, Any]) -> set[str]:
    """``"<Def>.<field>"`` for every property of every object in a JSON Schema
    (the root object is named by its ``title``)."""
    out: set[str] = set()
    objects = [(schema.get("title", "Survey"), schema)]
    objects += list(schema.get("$defs", {}).items())
    for name, obj in objects:
        for prop in obj.get("properties", {}):
            out.add(f"{name}.{prop}")
    return out


def check_table(
    schema: Mapping[str, Any], table: Mapping[str, Capability]
) -> tuple[list[str], list[str]]:
    """``(missing, stale)``: schema fields with no row, and rows naming no schema field.

    Value refinements (``"<Def>.<field>=<value>"``) must refine an existing field;
    target behaviours (``"$..."``) are not schema fields and are not checked.
    """
    fields = schema_fields(schema)
    missing = sorted(f for f in fields if f not in table)
    stale = sorted(k for k in table if not k.startswith("$") and k.split("=", 1)[0] not in fields)
    return missing, stale


__all__ = [
    "LEVELS",
    "TABLES",
    "XLSFORM",
    "Capability",
    "Level",
    "check_table",
    "schema_fields",
]
