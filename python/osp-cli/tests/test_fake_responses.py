"""``osp-cli fake-responses`` (task DS1): invented responses made by the real engine and
stored through the participant session service. Needs node and
``web/engine-sim/dist/fake.js`` (``make sim-build``, which py-test runs). Fake data only."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from osp_app.identity import DEV_LAB_ID, DEV_USER_ID
from osp_cli.fake_responses import FAKE_CLI, FakeError, fake_responses
from osp_cli.main import (
    dev_fake_count,
    main,
    open_services,
    researcher,
    seed_fixture,
    store_factory,
)
from osp_store import ParticipantStore, TenantContext, generate_key

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
BUNDLE = Path(__file__).resolve().parents[3] / "web" / "engine" / "dist" / "engine.js"
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
DEV = {"OSP_ENV": "dev"}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None or not FAKE_CLI.is_file(),
    reason="needs node and web/engine-sim/dist/fake.js (make sim-build)",
)


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("OSP_STORE_KEYS", f"k1:{generate_key()}")
    monkeypatch.delenv("OSP_STORE_ACTIVE_KEY", raising=False)


def _setup(tmp_path: Path, fixture: str, name: str = "f.db") -> tuple[str, Any, dict[str, Any]]:
    db = f"sqlite:///{tmp_path / name}"
    services = open_services(db)
    out = seed_fixture(services, FIXTURES / fixture, user=DEV_USER_ID, lab=DEV_LAB_ID)
    return db, services, out


def _fake(db: str, target: str, **kw: Any) -> Any:
    kw.setdefault("environ", DEV)
    kw.setdefault("now", NOW)
    kw.setdefault("keep_participants", True)
    return fake_responses(store_factory(db), target, **kw)


def _results(services: Any, survey_id: str) -> dict[str, Any]:
    actor = researcher(services, DEV_USER_ID, DEV_LAB_ID)
    return services.builder.run(
        "survey.results_query", actor, survey_id=survey_id, query={"status": "all"}
    )


def _responses(services: Any, out: dict[str, Any]) -> list[tuple[Any, Any]]:
    ctx = TenantContext(DEV_LAB_ID, "test")
    return list(ParticipantStore(services.store).stream_responses(ctx, out["versionId"]))


def test_refused_outside_dev(tmp_path, keys, monkeypatch, capsys):
    db, _services, out = _setup(tmp_path, "01-all-types")
    for env in ({}, {"OSP_ENV": "production"}, {"OSP_ENV": "test"}):
        with pytest.raises(FakeError, match="OSP_ENV=dev"):
            fake_responses(store_factory(db), out["slug"], environ=env)
    monkeypatch.delenv("OSP_ENV", raising=False)
    assert main(["fake-responses", out["slug"], "--db", db]) == 2
    assert "OSP_ENV=dev" in capsys.readouterr().err
    assert dev_fake_count({}) == 0 and dev_fake_count({"OSP_ENV": "production"}) == 0
    assert dev_fake_count(DEV) == 150
    assert dev_fake_count({**DEV, "DEV_FAKE_RESPONSES": "0"}) == 0
    assert dev_fake_count({**DEV, "DEV_FAKE_RESPONSES": "40"}) == 40


def test_bad_options_and_unknown_survey(tmp_path, keys):
    db, _services, out = _setup(tmp_path, "01-all-types")
    for kw in ({"n": 0}, {"partial": 1.5}, {"days": 0}, {"seed": -1}):
        with pytest.raises(FakeError):
            _fake(db, out["slug"], **kw)
    with pytest.raises(FakeError, match="no published survey"):
        _fake(db, "no-such-survey")


@needs_node
@pytest.mark.parametrize(
    "fixture",
    [
        "01-all-types",
        "13-randomiser-blocks",
        "16-assign",
        "18-multi-language",
        "24-quota-pending-retry",
        "33-end-only-save",
        "38-matrix",
        "39-slider",
        "40-consent",
    ],
)
def test_fake_responses_are_real_ones_and_add_up(fixture, tmp_path, keys):
    db, services, out = _setup(tmp_path, fixture)
    n = 40
    report = _fake(db, out["surveyId"], n=n, seed=7, partial=0.25, days=14)
    assert report.stuck == 0
    assert report.submitted + report.dropped == n
    assert 0 < report.dropped < n // 2

    # Stored as responses of the published version, with the server's own checks passed
    # (submit validates checksum, session and assignment) and times inside the window.
    rows = _responses(services, out)
    assert len(rows) == report.submitted
    for resp, full in rows:
        rec, server = full["record"], full["server"]
        assert rec["planChecksum"] == out["planChecksum"] == server["planChecksum"]
        assert rec["sessionSeed"] == server["sessionSeed"] and rec["format"] == "osp-response/1"
        assert rec["events"][0]["type"] == "start" and rec["end"] is not None
        assert NOW - timedelta(days=14) <= resp.submitted_at.replace(tzinfo=UTC) <= NOW
        assert resp.answers == rec["answers"]

    # The results query counts every submitted response once per question.
    res = _results(services, out["surveyId"])
    assert res["responses"] == report.submitted
    for card in res["cards"]:
        if card["type"] == "note":
            continue
        states = [card["states"]] if card.get("states") else [r["states"] for r in card["rows"]]
        for s in states:
            assert sum(s.values()) == report.submitted, card["question"]
            assert s["unrecorded"] == 0 and s["invalid"] == 0, card["question"]


@needs_node
@pytest.mark.parametrize(
    "fixture", ["13-randomiser-blocks", "24-quota-pending-retry", "40-consent"]
)
def test_replay_of_every_fake_response_matches(fixture, tmp_path, keys):
    """The reproducibility package replays each stored event log with the engine bundle
    and the Python checker: a fake response is as reproducible as a real one."""
    if not BUNDLE.is_file():
        pytest.skip("needs web/engine/dist/engine.js (make engine-bundle)")
    db, services, out = _setup(tmp_path, fixture)
    report = _fake(db, out["slug"], n=25, seed=3)
    actor = researcher(services, DEV_USER_ID, DEV_LAB_ID)
    pkg = services.builder.run(
        "survey.repro_package", actor, survey_id=out["surveyId"], version=1, data=True
    )
    with zipfile.ZipFile(io.BytesIO(pkg.content)) as z:
        z.extractall(tmp_path / "repro")
        (root,) = {n.split("/", 1)[0] for n in z.namelist()}
    for cmd in (
        [shutil.which("node"), "replay/replay.mjs", "--json"],
        [sys.executable, "-I", "replay/replay.py", "--json"],
    ):
        proc = subprocess.run(
            cmd, cwd=tmp_path / "repro" / root, capture_output=True, text=True, timeout=120
        )
        assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
        replayed = json.loads(proc.stdout)["responses"]
        assert len(replayed) == report.submitted
        assert all(r["status"] == "match" for r in replayed)


@needs_node
@pytest.mark.parametrize("fixture", ["18-multi-language", "39-slider", "40-consent"])
def test_partials_stop_and_are_not_reached_after_their_stop(fixture, tmp_path, keys):
    db, services, out = _setup(tmp_path, fixture)
    report = _fake(db, out["slug"], n=40, seed=11, partial=0.5)
    plan = services.sessions.plan(out["slug"], out["planChecksum"])
    order = list(plan["pages"])
    drops = [p for p in report.participants if not p["submitted"]]
    assert drops
    ps = ParticipantStore(services.store)
    for p in drops:
        rec, stop = p["record"], p["droppedOn"]
        assert rec["end"] is None
        # The server holds the participant's last state and no response.
        sess = ps.get(TenantContext(DEV_LAB_ID, "test"), p["sessionId"])
        assert sess.submitted_at is None
        assert sess.snapshot["revision"] == rec["revision"]
        shown = [h["page"] for h in sess.snapshot["data"]["history"]]
        assert shown[-1] == stop
        for qid, ans in rec["answers"].items():
            page = plan["items"][qid]["page"]
            if order.index(page) > order.index(stop):
                assert ans["state"] == "not-reached", (qid, stop)
            elif page == stop:
                assert ans["state"] in ("answered", "unanswered", "irrelevant")


@needs_node
def test_deterministic_by_seed(tmp_path, keys):
    def run(name: str, seed: int) -> list[Any]:
        db, services, out = _setup(tmp_path, "13-randomiser-blocks", name)
        _fake(db, out["slug"], n=20, seed=seed)
        return [
            (
                str(resp.submitted_at),
                full["record"]["assigned"],
                full["record"]["orders"],
                {k: v for k, v in resp.answers.items()},
            )
            for resp, full in _responses(services, out)
        ]

    a, b, c = run("a.db", 5), run("b.db", 5), run("c.db", 6)
    assert a == b and len(a) > 10
    assert a != c


@needs_node
def test_cli_and_dev_seed(tmp_path, keys, monkeypatch, capsys):
    monkeypatch.setenv("OSP_ENV", "dev")
    monkeypatch.setenv("DEV_FAKE_RESPONSES", "12")
    db = f"sqlite:///{tmp_path / 'dev.db'}"
    fixtures = [str(FIXTURES / n) for n in ("01-all-types", "18-multi-language")]
    assert main(["dev-seed", *fixtures, "--db", db, "--data-dir", str(tmp_path)]) == 0
    banner = capsys.readouterr().out
    assert banner.count("12 fake sessions") == 2
    state = json.loads((tmp_path / "dev-seed.json").read_text())
    services = open_services(db)
    first = _results(services, state["surveys"][0]["surveyId"])["responses"]
    assert 0 < first <= 12
    # A second dev-seed run adds nothing; `make dev-fake` (--dev-seeded) adds more.
    assert main(["dev-seed", *fixtures, "--db", db, "--data-dir", str(tmp_path)]) == 0
    assert "fake sessions" not in capsys.readouterr().out
    argv = ["fake-responses", "--dev-seeded", "--n", "5", "--seed", "9", "--db", db]
    assert main([*argv, "--data-dir", str(tmp_path)]) == 0
    printed = capsys.readouterr().out
    assert printed.count("5 fake sessions") == 2
    summary = json.loads(printed.splitlines()[1])
    assert summary["sessions"] == 5
    again = _results(services, state["surveys"][0]["surveyId"])["responses"]
    assert first < again <= first + 5
