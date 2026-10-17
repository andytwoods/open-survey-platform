"""Completeness guard for the LimeSurvey capability table (AGENTS.md rule 6): every
osp-survey schema field has a row, and no row names a field that no longer exists."""

from __future__ import annotations

import copy
from collections import Counter

from osp_spec import json_schema
from osp_targets.capabilities import LEVELS, XLSFORM, check_table
from osp_targets.lss import LSS


def test_every_schema_field_has_a_row() -> None:
    missing, stale = check_table(json_schema(), LSS)
    assert missing == [], f"lss: add capability rows for {missing}"
    assert stale == [], f"lss: rows for fields that no longer exist: {stale}"


def test_rows_are_well_formed() -> None:
    for key, cap in LSS.items():
        assert cap.level in LEVELS, key
        assert cap.note.strip(), key


def test_same_schema_keys_as_xlsform() -> None:
    """Both tables cover the same schema fields (target behaviours may differ)."""
    schema_keys = {k for k in LSS if not k.startswith("$") and "=" not in k}
    assert schema_keys == {k for k in XLSFORM if not k.startswith("$") and "=" not in k}


def test_guard_fails_on_a_new_field() -> None:
    schema = copy.deepcopy(json_schema())
    schema["$defs"]["Page"]["properties"]["pageShowIf"] = {"type": "object"}
    schema["$defs"]["NewThing"] = {"type": "object", "properties": {"x": {}}}
    missing, _ = check_table(schema, LSS)
    assert missing == ["NewThing.x", "Page.pageShowIf"]


def test_guard_fails_on_a_removed_field() -> None:
    schema = copy.deepcopy(json_schema())
    del schema["$defs"]["Page"]["properties"]["itemOrder"]
    _, stale = check_table(schema, LSS)
    assert stale == ["Page.itemOrder", "Page.itemOrder=shuffle"]


def test_lss_summary_is_stable() -> None:
    """Counts per level, so a change of level is a visible, reviewed diff."""
    counts = Counter(cap.level for cap in LSS.values())
    assert dict(counts) == {"native": 142, "lowered": 50, "approximated": 23, "unsupported": 53}
    assert LSS["MatrixQuestion.type"].level == "native"
    assert LSS["SliderQuestion.type"].level == "approximated"
    assert LSS["Survey.quotas"].level == "lowered"
    assert LSS["Quota.when=unmappable"].level == "unsupported"
    assert LSS["SingleQuestion.choiceOrder=shuffle"].level == "approximated"
    assert LSS["Page.itemOrder=shuffle"].level == "approximated"
    assert LSS["$pipe.choiceLabel"].level == "native"
    assert LSS["$names.reserved"].level == "lowered"
