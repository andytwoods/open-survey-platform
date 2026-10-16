"""``osp-cli seed-fixture``: a fixture survey imported, published and startable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from osp_cli.main import main, open_services, seed_fixture
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
