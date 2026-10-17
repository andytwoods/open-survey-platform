"""``osp-cli seed-fixture``: a fixture survey imported, published and startable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from osp_app.identity import dev_identity
from osp_cli.main import main, open_services, researcher, seed_fixture
from osp_store import generate_key

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("OSP_STORE_KEYS", f"k1:{generate_key()}")
    monkeypatch.delenv("OSP_STORE_ACTIVE_KEY", raising=False)


def test_seed_fixture_publishes_a_startable_survey(tmp_path, keys, capsys):
    db = f"sqlite:///{tmp_path / 'seed.db'}"
    assert main(["seed-fixture", str(FIXTURES / "16-assign"), "--db", db]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["versionNumber"] == 1 and out["planUrl"].endswith(out["planChecksum"])

    services = open_services(db)
    started = services.sessions.start(out["slug"])
    assert started.plan_checksum == out["planChecksum"]
    assert started.assigned["cond"] in ("control", "treatment")
    plan = services.sessions.plan(out["slug"], out["planChecksum"])
    assert plan["survey"]["id"] == "f16_assign" and plan["survey"]["seedVersion"] == "1"

    # Seeding again reuses the researcher and lab, and gives a new survey + slug.
    assert main(["seed-fixture", str(FIXTURES / "33-end-only-save"), "--db", db]) == 0
    again = json.loads(capsys.readouterr().out)
    assert again["userId"] == out["userId"] and again["tenantId"] == out["tenantId"]
    assert again["slug"] != out["slug"]


def test_every_fixture_seeds(tmp_path, keys):
    services = open_services(f"sqlite:///{tmp_path / 'all.db'}")
    dirs = sorted(d for d in FIXTURES.iterdir() if (d / "survey.json").is_file())
    assert len(dirs) >= 37
    for d in dirs:
        out = seed_fixture(services, d)
        assert services.sessions.plan(out["slug"], out["planChecksum"])["checksum"]


def test_errors_are_messages_not_tracebacks(tmp_path, keys, monkeypatch, capsys):
    db = f"sqlite:///{tmp_path / 'e.db'}"
    assert main(["seed-fixture", str(tmp_path / "missing"), "--db", db]) == 2
    assert "can't read" in capsys.readouterr().err
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "survey.json").write_text('{"specVersion": "nope"}')
    assert main(["seed-fixture", str(bad), "--db", db]) == 2
    assert "not structurally valid" in capsys.readouterr().err
    monkeypatch.delenv("OSP_STORE_KEYS")
    assert main(["seed-fixture", str(FIXTURES / "16-assign"), "--db", db]) == 2
    assert "gen-key" in capsys.readouterr().err
    assert main(["gen-key"]) == 0
    assert capsys.readouterr().out.startswith("OSP_STORE_KEYS=k1:")


DEV_FIXTURES = [FIXTURES / n for n in ("01-all-types", "13-randomiser-blocks", "18-multi-language")]


def test_dev_seed_creates_once_then_reprints(tmp_path, keys, capsys, monkeypatch):
    monkeypatch.delenv("OSP_ENV", raising=False)
    db = f"sqlite:///{tmp_path / 'dev.db'}"
    argv = ["dev-seed", *map(str, DEV_FIXTURES), "--db", db, "--data-dir", str(tmp_path)]
    assert main(argv) == 0
    first = capsys.readouterr().out
    assert "first run" in first and "dev-researcher" in first
    assert "participant app not built yet" in first
    state = json.loads((tmp_path / "dev-seed.json").read_text())
    assert [s["fixture"] for s in state["surveys"]] == [p.name for p in DEV_FIXTURES]
    assert "password" not in first.lower() and "password" not in state
    assert (tmp_path / "dev-seed.json").stat().st_mode & 0o077 == 0

    # The dev identity (what osp-api's Dev provider uses) sees them; a second run reuses all.
    services = open_services(db)
    assert main([*argv, "--participant-link", "http://localhost:5174/r/?s={slug}"]) == 0
    again = capsys.readouterr().out
    assert "first run" not in again
    assert f"localhost:5174/r/?s={state['surveys'][0]['slug']}" in again
    actor = services.admit(dev_identity())
    assert len(services.builder.run("survey.list", actor)) == 3
    assert researcher(services, state["user"], state["lab"]) == actor


def test_old_dev_seed_file_asks_for_a_reset(tmp_path, keys, capsys, monkeypatch):
    monkeypatch.delenv("OSP_ENV", raising=False)
    (tmp_path / "dev-seed.json").write_text('{"email": "dev@osp.example", "surveys": []}')
    db = f"sqlite:///{tmp_path / 'dev.db'}"
    argv = ["dev-seed", str(DEV_FIXTURES[0]), "--db", db, "--data-dir", str(tmp_path)]
    assert main(argv) == 2
    assert "dev-reset" in capsys.readouterr().err


def test_lab_create(tmp_path, keys, capsys):
    db = f"sqlite:///{tmp_path / 'lab.db'}"
    assert main(["lab", "create", "psych-7", "--name", "Psychology", "--db", db]) == 0
    assert capsys.readouterr().out.strip() == "psych-7"
    assert main(["lab", "create", "bad lab", "--db", db]) == 2
    services = open_services(db)
    services.auto_create_labs = False
    actor = researcher(services, "u1", "psych-7")
    assert dict(actor.roles) == {"psych-7": "owner"}


def test_dev_seed_refused_in_production(tmp_path, keys, capsys, monkeypatch):
    monkeypatch.setenv("OSP_ENV", "production")
    db = f"sqlite:///{tmp_path / 'dev.db'}"
    assert main(["dev-seed", str(DEV_FIXTURES[0]), "--db", db, "--data-dir", str(tmp_path)]) == 2
    assert "development only" in capsys.readouterr().err
    assert not (tmp_path / "dev-seed.json").exists()
