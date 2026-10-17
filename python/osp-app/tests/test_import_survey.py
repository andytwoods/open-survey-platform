"""Import commands (task IM1): preview and create-from-file, permissions, bad input."""

from __future__ import annotations

from pathlib import Path

import pytest
from osp_app import COMMANDS, Forbidden, InvalidRequest, Rejected, build_services, make_identity
from osp_app.auth.testing import FakeClock
from osp_store import Keyring, Store, create_engine, migrate

KEY = "a" * 43 + "="
DATA = Path(__file__).resolve().parents[2] / "osp-targets/tests/data/imports"
QSF = (DATA / "coffee.qsf").read_text(encoding="utf-8")
LSS = (DATA / "coffee.lss").read_text(encoding="utf-8")
SJS = (DATA / "coffee-surveyjs.json").read_text(encoding="utf-8")


@pytest.fixture
def env(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    migrate(engine)
    svc = build_services(Store(engine, Keyring({"k1": KEY}, active="k1")), clock=FakeClock())
    actors = {
        "owner_a": svc.admit(make_identity("owner-a", {"lab-a": "owner"}, "Owner A")),
        "editor_a": svc.admit(make_identity("editor-a", {"lab-a": "editor"})),
        "viewer_a": svc.admit(make_identity("viewer-a", {"lab-a": "viewer"})),
        "both": svc.admit(make_identity("both", {"lab-a": "owner", "lab-b": "owner"})),
    }
    return svc, actors


def test_commands_are_registered():
    assert {"survey.import_preview", "survey.import"} <= set(COMMANDS)


def test_preview_reports_without_creating(env):
    svc, a = env
    p = svc.builder.run("survey.import_preview", a["editor_a"], filename="coffee.qsf", content=QSF)
    assert p.ok and p.format == "qsf"
    assert p.title == "Coffee and sleep (invented sample)"
    assert p.summary is not None and p.summary.questions == 9
    assert any(d.severity == "loss" for d in p.diagnostics)
    assert svc.builder.run("survey.list", a["editor_a"]) == []


@pytest.mark.parametrize(
    ("filename", "content", "fmt"),
    [("coffee.qsf", QSF, "qsf"), ("coffee.lss", LSS, "lss"), ("coffee.json", SJS, "surveyjs")],
)
def test_import_creates_a_draft(env, filename, content, fmt):
    svc, a = env
    out = svc.builder.run("survey.import", a["editor_a"], filename=filename, content=content)
    assert out.preview.format == fmt and out.preview.ok
    assert out.view.draft.revision == 0
    assert out.view.survey.title.startswith("Coffee and sleep")
    got = svc.builder.run("survey.get", a["editor_a"], survey_id=out.view.survey.id)
    assert got.draft.body == out.view.draft.body
    assert got.draft.body["specVersion"] == "osp-survey/0.1"


def test_import_with_a_new_title_and_an_explicit_format(env):
    svc, a = env
    out = svc.builder.run(
        "survey.import",
        a["owner_a"],
        filename="renamed.txt",
        content=SJS,
        format="surveyjs",
        title="  Pilot study  ",
    )
    assert out.view.survey.title == "Pilot study"
    assert out.view.draft.body["metadata"]["title"] == {
        "en": "Pilot study",
        "de": "Kaffee und Schlaf (erfundenes Beispiel)",
    }
    assert out.preview.title == "Pilot study"


def test_viewer_cannot_import_or_preview(env):
    svc, a = env
    with pytest.raises(Forbidden):
        svc.builder.run("survey.import_preview", a["viewer_a"], filename="c.qsf", content=QSF)
    with pytest.raises(Forbidden):
        svc.builder.run("survey.import", a["viewer_a"], filename="c.qsf", content=QSF)


def test_tenant_is_needed_when_ambiguous(env):
    svc, a = env
    with pytest.raises(InvalidRequest):
        svc.builder.run("survey.import", a["both"], filename="c.lss", content=LSS)
    out = svc.builder.run(
        "survey.import", a["both"], filename="c.lss", content=LSS, tenant_id="lab-b"
    )
    assert out.view.survey.tenant_id == "lab-b"


def test_unreadable_file_is_rejected_with_diagnostics(env):
    svc, a = env
    p = svc.builder.run("survey.import_preview", a["owner_a"], filename="x.qsf", content="{nope")
    assert not p.ok and p.diagnostics[0].severity == "error" and p.summary is None
    with pytest.raises(Rejected) as exc:
        svc.builder.run("survey.import", a["owner_a"], filename="x.qsf", content="{nope")
    assert exc.value.diagnostics[0].code == "qsf.not_json"
    assert svc.builder.run("survey.list", a["owner_a"]) == []


@pytest.mark.parametrize(
    "params",
    [
        {"filename": "", "content": QSF},
        {"filename": "x" * 300, "content": QSF},
        {"filename": "a.qsf", "content": b"bytes"},
        {"filename": "a.qsf", "content": QSF, "format": "docx"},
        {"filename": "a.qsf", "content": QSF, "title": "   "},
        {"filename": "a.qsf", "content": "x" * 20_000_001},
    ],
)
def test_bad_parameters_are_invalid_requests(env, params):
    svc, a = env
    with pytest.raises(InvalidRequest):
        svc.builder.run("survey.import", a["owner_a"], **params)
