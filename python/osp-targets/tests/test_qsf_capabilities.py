"""Completeness guard for the Qualtrics capability table (AGENTS.md rule 6): every
osp-survey schema field has a row, and no row names a field that no longer exists."""

from __future__ import annotations

import copy
from collections import Counter

from osp_spec import json_schema
from osp_targets.capabilities import LEVELS, XLSFORM, check_table
from osp_targets.qsf import QSF


def test_every_schema_field_has_a_row() -> None:
    missing, stale = check_table(json_schema(), QSF)
    assert missing == [], f"qsf: add capability rows for {missing}"
    assert stale == [], f"qsf: rows for fields that no longer exist: {stale}"


def test_rows_are_well_formed() -> None:
    for key, cap in QSF.items():
        assert cap.level in LEVELS, key
        assert cap.note.strip(), key


def test_same_schema_keys_as_xlsform() -> None:
    """Every table covers the same schema fields (target behaviours may differ)."""
    schema_keys = {k for k in QSF if not k.startswith("$") and "=" not in k}
    assert schema_keys == {k for k in XLSFORM if not k.startswith("$") and "=" not in k}


def test_guard_fails_on_a_new_field() -> None:
    schema = copy.deepcopy(json_schema())
    schema["$defs"]["Page"]["properties"]["pageShowIf"] = {"type": "object"}
    schema["$defs"]["NewThing"] = {"type": "object", "properties": {"x": {}}}
    missing, _ = check_table(schema, QSF)
    assert missing == ["NewThing.x", "Page.pageShowIf"]


def test_guard_fails_on_a_removed_field() -> None:
    schema = copy.deepcopy(json_schema())
    del schema["$defs"]["Page"]["properties"]["itemOrder"]
    _, stale = check_table(schema, QSF)
    assert stale == ["Page.itemOrder", "Page.itemOrder=shuffle"]


def test_qsf_summary_is_stable() -> None:
    """Counts per level, so a change of level is a visible, reviewed diff."""
    counts = Counter(cap.level for cap in QSF.values())
    assert dict(counts) == {"native": 144, "lowered": 58, "approximated": 27, "unsupported": 147}
    assert QSF["MatrixQuestion.type"].level == "native"
    assert QSF["MultiQuestion.type"].level == "lowered"
    assert QSF["DateQuestion.type"].level == "approximated"
    assert QSF["ComputedVariable.kind"].level == "unsupported"
    assert QSF["Survey.quotas"].level == "unsupported"
    assert QSF["BranchNode.else"].level == "lowered"
    assert QSF["$logic.unmappable"].level == "unsupported"
    assert QSF["SingleQuestion.choiceOrder=shuffle"].level == "approximated"
    assert QSF["$pipe.choiceLabel"].level == "native"
    assert QSF["$names.reserved"].level == "lowered"
