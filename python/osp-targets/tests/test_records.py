"""The engine records under ``tests/data/records`` are complete and current.

``test_data_export.py`` and ``test_repro.py`` read real engine output: one record per
fixture script, ``result(state)`` after playing it through ``web/engine``. A new fixture
whose records were never generated would silently drop out of both suites, and a fixture
whose survey changed would be tested against a plan that no longer exists. This test makes
both a failure, with the command that fixes it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from osp_runtime.plan import compile_survey

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "fixtures"
RECORDS = Path(__file__).resolve().parent / "data" / "records"
REGENERATE = (
    "regenerate the records with `make engine-records`, then the goldens with "
    "`OSP_UPDATE_GOLDEN=1 uv run pytest python/osp-targets/tests/test_data_export.py`, "
    "and review the diff"
)
SCRIPTED = sorted(
    p.name for p in FIXTURES.iterdir() if p.is_dir() and any((p / "scripts").glob("*.json"))
)


def _plan_checksum(fixture: str) -> str | None:
    survey = json.loads((FIXTURES / fixture / "survey.json").read_text(encoding="utf-8"))
    plan, _ = compile_survey(survey)
    return None if plan is None else str(plan["checksum"])


def test_every_scripted_fixture_is_covered() -> None:
    assert SCRIPTED, "no fixture scripts found"
    for fixture in SCRIPTED:
        if _plan_checksum(fixture) is None:
            continue  # the survey does not compile, so there is nothing to record
        assert (RECORDS / fixture).is_dir(), (
            f"fixtures/{fixture} has scripts but no engine records in "
            f"python/osp-targets/tests/data/records/{fixture}/: {REGENERATE}"
        )


def test_no_records_for_removed_fixtures() -> None:
    stale = sorted(p.name for p in RECORDS.iterdir() if p.is_dir() and p.name not in SCRIPTED)
    assert not stale, f"records for fixtures that no longer have scripts: {stale}; {REGENERATE}"


@pytest.mark.parametrize("fixture", SCRIPTED)
def test_records_match_scripts_and_current_plan(fixture: str) -> None:
    want = _plan_checksum(fixture)
    if want is None:
        pytest.skip(f"fixtures/{fixture} does not compile")
    scripts = sorted(p.name for p in (FIXTURES / fixture / "scripts").glob("*.json"))
    records = sorted(p.name for p in (RECORDS / fixture).glob("*.json"))
    assert records == scripts, (
        f"fixtures/{fixture}: scripts {scripts} but records {records}; {REGENERATE}"
    )
    for name in records:
        rec = json.loads((RECORDS / fixture / name).read_text(encoding="utf-8"))
        assert rec.get("planChecksum") == want, (
            f"records/{fixture}/{name} was made from plan {rec.get('planChecksum')}, but "
            f"fixtures/{fixture}/survey.json now compiles to {want}: {REGENERATE}"
        )
