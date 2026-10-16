"""Fixtures (C3a, C3b): every folder has a survey, at least one script and a matching expected
trace; every survey is an `osp-survey/0.1` document that `osp_spec` loads with zero error
diagnostics. A fixture with a `pending.json` may only have the error diagnostics it lists."""

import json
import re
from pathlib import Path

import pytest
from osp_spec import SPEC_VERSION, parse

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "fixtures"
SEMANTICS = REPO / "planning" / "semantics.md"
FIXTURE_DIR = re.compile(r"^\d\d-[a-z0-9-]+$")
NOT_FIXTURES = {"tools"}  # fixtures/tools: the one-off v0 converter (C3b)

DIRS = sorted(p for p in FIXTURES.iterdir() if p.is_dir() and FIXTURE_DIR.match(p.name))


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _pending_note(fixture: Path) -> dict:
    path = fixture / "pending.json"
    return _load(path) if path.is_file() else {}


def _open_question_ids(ids) -> list[str]:
    if isinstance(ids, str):
        return [ids]
    return list(ids or [])


def test_at_least_twenty_fixtures():
    assert len(DIRS) >= 20, [p.name for p in DIRS]


def test_no_stray_directories():
    stray = [
        p.name
        for p in FIXTURES.iterdir()
        if p.is_dir() and not FIXTURE_DIR.match(p.name) and p.name not in NOT_FIXTURES
    ]
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
def test_survey_validates_against_osp_spec(fixture: Path):
    data = _load(fixture / "survey.json")
    assert data.get("specVersion") == SPEC_VERSION, f"{fixture.name}: not {SPEC_VERSION}"
    survey, diagnostics = parse(data)
    errors = {(d.code, d.pointer) for d in diagnostics if d.severity == "error"}
    allowed = {
        (a["code"], a["pointer"]) for a in _pending_note(fixture).get("allowedDiagnostics", [])
    }
    unexpected = sorted(errors - allowed)
    assert not unexpected, f"{fixture.name}: error diagnostics {unexpected}"
    stale = sorted(allowed - errors)
    assert not stale, (
        f"{fixture.name}: pending.json allows diagnostics that no longer occur {stale}"
    )
    if not errors:
        assert survey is not None


@pytest.mark.parametrize("fixture", DIRS, ids=lambda p: p.name)
def test_pending_questions_exist_in_semantics(fixture: Path):
    """A trace or pending note marked pending must point at an open question that exists."""
    text = SEMANTICS.read_text(encoding="utf-8")
    sources = [(p, _load(p).get("pending")) for p in sorted((fixture / "expected").glob("*.json"))]
    note = fixture / "pending.json"
    if note.is_file():
        sources.append((note, _load(note).get("pending")))
    for path, pending in sources:
        for qid in _open_question_ids(pending):
            assert f"**{qid}**" in text, f"{path}: pending {qid} not in semantics.md"
