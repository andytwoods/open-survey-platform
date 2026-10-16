"""C3a: every fixture folder has a survey, at least one script and a matching expected trace,
and all of it is valid JSON. Schema-agnostic on purpose: C3b validates against osp-spec."""

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "fixtures"
SEMANTICS = REPO / "planning" / "semantics.md"
FIXTURE_DIR = re.compile(r"^\d\d-[a-z0-9-]+$")

DIRS = sorted(p for p in FIXTURES.iterdir() if p.is_dir() and FIXTURE_DIR.match(p.name))


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_at_least_twenty_fixtures():
    assert len(DIRS) >= 20, [p.name for p in DIRS]


def test_no_stray_directories():
    stray = [p.name for p in FIXTURES.iterdir() if p.is_dir() and not FIXTURE_DIR.match(p.name)]
    assert not stray, f"fixture folders must be named NN-name: {stray}"


@pytest.mark.parametrize("fixture", DIRS, ids=lambda p: p.name)
def test_fixture_shape(fixture: Path):
    survey = fixture / "survey.json"
    assert survey.is_file(), f"{fixture.name}: missing survey.json"
    assert isinstance(_load(survey), dict)

    scripts = sorted((fixture / "scripts").glob("*.json"))
    expected = sorted((fixture / "expected").glob("*.json"))
    assert scripts, f"{fixture.name}: no scripts/*.json"
    assert [p.name for p in scripts] == [p.name for p in expected], (
        f"{fixture.name}: every script needs an expected trace with the same file name"
    )
    for path in scripts + expected:
        assert isinstance(_load(path), dict), path


@pytest.mark.parametrize("fixture", DIRS, ids=lambda p: p.name)
def test_pending_questions_exist_in_semantics(fixture: Path):
    """A trace marked pending must point at an open question that really exists."""
    text = SEMANTICS.read_text(encoding="utf-8")
    for path in sorted((fixture / "expected").glob("*.json")):
        pending = _load(path).get("pending") or []
        if isinstance(pending, str):
            pending = [pending]
        for qid in pending:
            assert f"**{qid}**" in text, f"{path}: pending {qid} not in semantics.md"
