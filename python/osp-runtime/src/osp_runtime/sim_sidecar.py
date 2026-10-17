"""Node sidecar for the simulator (task M1, runtime-design.md §4): the simulator runs the
TS engine, so the server runs ``node web/engine-sim/dist/cli.js`` with
``{"plan": ..., "options": ...}`` on stdin and reads one JSON object back.

Limits: input size, output size, wall-clock timeout (the process is killed), and a V8 heap
cap. Every failure is a ``SimulatorError`` with a short code; nothing else escapes.

Configuration (environment, read per call): ``OSP_NODE`` (node binary; default ``node``
on PATH) and ``OSP_SIM_CLI`` (the bundled CLI; default ``web/engine-sim/dist/cli.js`` in
this repository, built by ``make sim-build``).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CLI = Path(__file__).resolve().parents[4] / "web" / "engine-sim" / "dist" / "cli.js"
MAX_PARTICIPANTS = 10_000


class SimulatorError(Exception):
    """The simulation could not be run. ``code`` is one of: ``sim.unavailable`` (no node or
    no CLI), ``sim.timeout``, ``sim.too_large`` (input or output), ``sim.failed`` (crash or
    unreadable output), or the CLI's own code (``options.*``, ``plan.*``)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SidecarLimits:
    timeout_s: float = 60.0
    max_input_bytes: int = 8 * 1024 * 1024
    max_output_bytes: int = 16 * 1024 * 1024
    heap_mb: int = 512


def _command(cli: Path | None, node: str | None) -> list[str]:
    node_bin = node or os.environ.get("OSP_NODE") or shutil.which("node")
    if not node_bin:
        raise SimulatorError("sim.unavailable", "node is not installed")
    path = cli or Path(os.environ.get("OSP_SIM_CLI") or DEFAULT_CLI)
    if not path.is_file():
        raise SimulatorError("sim.unavailable", "simulator is not built (make sim-build)")
    return [node_bin, path.as_posix()]


def run_sidecar(
    payload: dict[str, Any],
    *,
    limits: SidecarLimits | None = None,
    cli: Path | None = None,
    node: str | None = None,
) -> dict[str, Any]:
    """Run the CLI on ``payload`` and return its parsed JSON reply (``{"ok": ...}``)."""
    lim = limits or SidecarLimits()
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > lim.max_input_bytes:
        raise SimulatorError("sim.too_large", "the plan is too large to simulate")
    cmd = _command(cli, node)
    cmd.insert(1, f"--max-old-space-size={lim.heap_mb}")
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PATH": os.environ.get("PATH", ""), "NODE_OPTIONS": ""},
        )
    except OSError as exc:
        raise SimulatorError("sim.unavailable", f"could not start node: {exc.strerror}") from exc

    out: list[bytes] = []

    def pump() -> None:
        assert proc.stdin is not None and proc.stdout is not None
        try:
            proc.stdin.write(data)
            proc.stdin.close()
        except OSError:  # the child exited early; its reply (if any) says why
            pass
        out.append(proc.stdout.read(lim.max_output_bytes + 1))

    worker = threading.Thread(target=pump, daemon=True)
    worker.start()
    worker.join(lim.timeout_s)
    if worker.is_alive():
        proc.kill()
        proc.wait()
        worker.join(5)
        raise SimulatorError("sim.timeout", f"the simulation took longer than {lim.timeout_s:g}s")
    raw = out[0] if out else b""
    if len(raw) > lim.max_output_bytes:
        proc.kill()
        proc.wait()
        raise SimulatorError("sim.too_large", "the simulation result is too large")
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    try:
        reply = json.loads(raw)
    except ValueError as exc:
        raise SimulatorError("sim.failed", "the simulator gave no readable result") from exc
    if not isinstance(reply, dict) or not isinstance(reply.get("ok"), bool):
        raise SimulatorError("sim.failed", "the simulator gave no readable result")
    return reply


def simulate_plan(
    plan: dict[str, Any],
    options: dict[str, Any],
    *,
    limits: SidecarLimits | None = None,
    cli: Path | None = None,
    node: str | None = None,
) -> dict[str, Any]:
    """Simulate ``plan`` (a runtime plan) and return the ``osp-sim/1`` result."""
    n = options.get("n")
    if type(n) is not int or not 1 <= n <= MAX_PARTICIPANTS:
        raise SimulatorError("options.n", f"n must be an integer from 1 to {MAX_PARTICIPANTS}")
    reply = run_sidecar({"plan": plan, "options": options}, limits=limits, cli=cli, node=node)
    if not reply["ok"]:
        err = reply.get("error") if isinstance(reply.get("error"), dict) else {}
        code = str(err.get("code") or "sim.failed")[:60]
        raise SimulatorError(code, str(err.get("message") or "simulation failed")[:500])
    result = reply.get("result")
    if not isinstance(result, dict) or result.get("format") != "osp-sim/1":
        raise SimulatorError("sim.failed", "the simulator gave no readable result")
    return result
