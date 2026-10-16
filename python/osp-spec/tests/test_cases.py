"""Fixture surveys under tests/cases/: each asserts its exact (code, pointer) diagnostics.

Case file: {"description": str, "expect": [{"code", "pointer"}], "survey": <any JSON>}.
`valid/` cases expect no diagnostics at all; `invalid/` cases expect at least one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from osp_spec import CODES, Survey, parse

CASES = Path(__file__).parent / "cases"
FILES = sorted(CASES.glob("*/*.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_there_are_at_least_30_cases() -> None:
    assert len(FILES) >= 30
    assert len(list(CASES.glob("valid/*.json"))) >= 10


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_case(path: Path) -> None:
    case = _load(path)
    survey, diagnostics = parse(case["survey"])
    got = sorted((d.code, d.pointer) for d in diagnostics)
    expected = sorted((e["code"], e["pointer"]) for e in case["expect"])
    assert got == expected, [d.model_dump() for d in diagnostics]
    for d in diagnostics:
        assert d.code in CODES and d.severity == CODES[d.code]
    if path.parent.name == "valid":
        assert expected == []
        assert isinstance(survey, Survey)
    else:
        assert expected, "an invalid case must expect at least one diagnostic"


@pytest.mark.parametrize("path", sorted(CASES.glob("valid/*.json")), ids=lambda p: p.stem)
def test_valid_cases_round_trip(path: Path) -> None:
    """Dumping a parsed survey and re-parsing it gives the same model and no diagnostics."""
    survey, _ = parse(_load(path)["survey"])
    assert survey is not None
    dumped = survey.model_dump(mode="json", exclude_none=True)
    again, diagnostics = parse(json.loads(json.dumps(dumped)))
    assert diagnostics == []
    assert again == survey
