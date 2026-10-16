"""Completeness guard (AGENTS.md rule 6): every osp-survey schema field has a row in every
target's capability table, and no row names a field that no longer exists."""

from __future__ import annotations

import copy
from collections import Counter

import pytest
from osp_spec import json_schema
from osp_targets.capabilities import LEVELS, TABLES, check_table, schema_fields


def test_schema_has_fields() -> None:
    fields = schema_fields(json_schema())
    assert "Survey.flow" in fields
    assert "SingleQuestion.choiceOrder" in fields
    assert "BranchNode.if" in fields  # alias, as in the JSON
    assert len(fields) > 100


@pytest.mark.parametrize("target", sorted(TABLES))
def test_every_schema_field_has_a_row(target: str) -> None:
    missing, stale = check_table(json_schema(), TABLES[target])
    assert missing == [], f"{target}: add capability rows for {missing}"
    assert stale == [], f"{target}: rows for fields that no longer exist: {stale}"


@pytest.mark.parametrize("target", sorted(TABLES))
def test_rows_are_well_formed(target: str) -> None:
    for key, cap in TABLES[target].items():
        assert cap.level in LEVELS, key
        assert cap.note.strip(), key


def test_guard_fails_on_a_new_field() -> None:
    schema = copy.deepcopy(json_schema())
    schema["$defs"]["Page"]["properties"]["pageShowIf"] = {"type": "object"}
    schema["$defs"]["NewThing"] = {"type": "object", "properties": {"x": {}}}
    missing, _ = check_table(schema, TABLES["xlsform"])
    assert missing == ["NewThing.x", "Page.pageShowIf"]


def test_guard_fails_on_a_removed_field() -> None:
    schema = copy.deepcopy(json_schema())
    del schema["$defs"]["Page"]["properties"]["itemOrder"]
    _, stale = check_table(schema, TABLES["xlsform"])
    assert stale == ["Page.itemOrder", "Page.itemOrder=shuffle"]


def test_xlsform_summary_is_stable() -> None:
    """Counts per level, so a change of level is a visible, reviewed diff."""
    counts = Counter(cap.level for cap in TABLES["xlsform"].values())
    assert set(counts) == set(LEVELS)
    assert counts["unsupported"] >= 10  # quotas, licence, ddi, back navigation off ...
    assert TABLES["xlsform"]["Survey.quotas"].level == "unsupported"
    assert TABLES["xlsform"]["SingleQuestion.choiceOrder=shuffle"].level == "lowered"
    assert TABLES["xlsform"]["Page.itemOrder=shuffle"].level == "approximated"
