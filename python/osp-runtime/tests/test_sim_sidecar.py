"""Node sidecar for the simulator (task M1): limits and failures with fake CLIs, and one
round trip through the real bundled CLI (built by `make sim-build`, which py-test runs)."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest
from osp_runtime.plan import compile_survey
from osp_runtime.sim_sidecar import (
    DEFAULT_CLI,
    SidecarLimits,
    SimulatorError,
    run_sidecar,
    simulate_plan,
)

REPO = Path(__file__).resolve().parents[3]
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")
needs_cli = pytest.mark.skipif(
    NODE is None or not DEFAULT_CLI.is_file(),
    reason="web/engine-sim/dist/cli.js is not built (make sim-build)",
)


def _fake(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "fake-cli.mjs"
    script.write_text(body, encoding="utf-8")
    return script


def _plan(fixture: str) -> dict:
    plan, _ = compile_survey(json.loads((REPO / "fixtures" / fixture / "survey.json").read_text()))
    assert plan is not None
    return plan


@needs_node
def test_timeout_kills_the_sidecar(tmp_path):
    cli = _fake(tmp_path, "setInterval(() => {}, 1000);\n")
    t0 = time.monotonic()
    with pytest.raises(SimulatorError) as exc:
        run_sidecar({"x": 1}, cli=cli, limits=SidecarLimits(timeout_s=0.5))
    assert exc.value.code == "sim.timeout"
    assert time.monotonic() - t0 < 5


@needs_node
def test_output_over_the_limit_is_refused(tmp_path):
    cli = _fake(tmp_path, "process.stdout.write('x'.repeat(5000));\n")
    with pytest.raises(SimulatorError) as exc:
        run_sidecar({}, cli=cli, limits=SidecarLimits(max_output_bytes=1000))
    assert exc.value.code == "sim.too_large"


def test_input_over_the_limit_is_refused_before_starting(tmp_path):
    with pytest.raises(SimulatorError) as exc:
        run_sidecar(
            {"plan": "x" * 2000},
            cli=tmp_path / "nope.js",
            limits=SidecarLimits(max_input_bytes=100),
        )
    assert exc.value.code == "sim.too_large"


@needs_node
@pytest.mark.parametrize(
    "body",
    [
        "process.stdout.write('not json');\n",
        "process.exit(3);\n",
        "throw new Error('boom');\n",
        "process.stdout.write(JSON.stringify([1, 2]));\n",
    ],
)
def test_crashes_and_garbage_are_sim_failed(tmp_path, body):
    with pytest.raises(SimulatorError) as exc:
        run_sidecar({}, cli=_fake(tmp_path, body))
    assert exc.value.code == "sim.failed"


def test_missing_cli_or_node_is_unavailable(tmp_path, monkeypatch):
    with pytest.raises(SimulatorError) as exc:
        run_sidecar({}, cli=tmp_path / "missing.js")
    assert exc.value.code == "sim.unavailable"
    monkeypatch.setenv("OSP_SIM_CLI", str(tmp_path / "missing.js"))
    with pytest.raises(SimulatorError) as exc:
        run_sidecar({})
    assert exc.value.code == "sim.unavailable"
    with pytest.raises(SimulatorError) as exc:
        run_sidecar({}, cli=_fake(tmp_path, ""), node=str(tmp_path / "no-node"))
    assert exc.value.code == "sim.unavailable"


@pytest.mark.parametrize("n", [0, 10_001, 1.5, "10", None, True])
def test_n_is_checked_before_running(n):
    with pytest.raises(SimulatorError) as exc:
        simulate_plan({}, {"n": n, "seed": 1}, cli=Path("/nonexistent"))
    assert exc.value.code == "options.n"


@needs_cli
def test_real_cli_round_trip():
    result = simulate_plan(_plan("11-end-nodes"), {"n": 200, "seed": 1})
    assert result["format"] == "osp-sim/1"
    assert result["coverage"] == "exhaustive"
    assert result["sample"]["runs"] == 200
    assert set(result["sample"]["ends"]) == {"end_ineligible", "end_early_exit", "end_complete"}


@needs_cli
def test_real_cli_reports_its_errors():
    with pytest.raises(SimulatorError) as exc:
        simulate_plan({**_plan("11-end-nodes"), "checksum": "sha256:00"}, {"n": 5, "seed": 1})
    assert exc.value.code == "plan.checksum"
    with pytest.raises(SimulatorError) as exc:
        simulate_plan(_plan("11-end-nodes"), {"n": 5, "seed": -1})
    assert exc.value.code == "options.seed"
    reply = run_sidecar({"nothing": True})
    assert reply == {
        "ok": False,
        "error": {"code": "input.shape", "message": 'input must be {"plan": ..., "options": ...}'},
    }
