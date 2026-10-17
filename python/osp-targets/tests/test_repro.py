"""Reproducibility package (task M3): deterministic zip, checksums, replay kit.

Packages are built from the fixture surveys, their compiled runtime plans and M2's engine
records (``tests/data/records``: ``result(state)`` after playing each fixture script through
``web/engine``). ``replay.py`` runs under ``python -I`` from the extracted zip, and
``replay.mjs`` under Node with the bundled ``engine.js`` (``make engine-bundle``, which
py-test runs; skipped without node or the bundle).
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import osp_engine.random
import osp_targets.repro
import pytest
from osp_runtime.plan import compile_survey, runtime_config
from osp_targets.data import StoredResponse
from osp_targets.repro import ReproData, ReproInputs, ReproKit, build_repro_package

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "fixtures"
RECORDS = Path(__file__).resolve().parent / "data" / "records"
KIT = Path(osp_targets.repro.__file__).resolve().parent / "kit"
BUNDLE = REPO / "web" / "engine" / "dist" / "engine.js"
NODE = shutil.which("node")
T0 = datetime(2026, 10, 16, 9, 30, tzinfo=UTC)
RECORD_FIXTURES = sorted(p.name for p in RECORDS.iterdir() if p.is_dir())
# Fixture scripts that inject a server assignment their seed would not draw (they test the
# branch, not the draw; our server always draws `assign(levels, node_seed(...))`), so
# replay.py rightly reports exactly that condition. 10 of the 15 recorded assignments and
# every recorded order match.
INJECTED = {
    ("16-assign", "resp-treatment"): "conditions.cond",
    ("20-worked-example", "resp-complete-gain"): "conditions.framing",
    ("20-worked-example", "resp-loss-charity-back-refresh"): "conditions.framing",
    ("20-worked-example", "resp-screenout-quota-full"): "conditions.incentive",
    ("23-refresh-every-step", "resp-arm-a"): "conditions.arm",
}

needs_node = pytest.mark.skipif(
    NODE is None or not BUNDLE.is_file(), reason="needs node and web/engine/dist/engine.js"
)


def _kit(engine: bool = True) -> ReproKit:
    return ReproKit(
        replay_py=(KIT / "replay.py").read_bytes(),
        replay_mjs=(KIT / "replay.mjs").read_bytes(),
        random_py=Path(osp_engine.random.__file__).read_bytes(),
        engine_js=BUNDLE.read_bytes() if engine and BUNDLE.is_file() else None,
    )


def _checksum(body: Any) -> str:
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _responses(fixture: str) -> list[StoredResponse]:
    out = []
    for i, path in enumerate(sorted((RECORDS / fixture).glob("*.json"))):
        rec = json.loads(path.read_text(encoding="utf-8"))
        out.append(
            StoredResponse(
                response_id=f"resp-{path.stem}",
                record=rec,
                session_id=f"sess-{path.stem}",
                allocation_mode="server",
                session_seed=rec["sessionSeed"],
                engine_version=rec["engineVersion"],
                started_at=T0 + timedelta(minutes=i),
                submitted_at=T0 + timedelta(minutes=i, seconds=30),
                late=False,
            )
        )
    return out


def _inputs(fixture: str, *, data: bool = True, engine: bool = True, **kw: Any) -> ReproInputs:
    survey = kw.pop("survey", None) or json.loads(
        (FIXTURES / fixture / "survey.json").read_text(encoding="utf-8")
    )
    plan, diags = compile_survey(survey)
    assert plan is not None, diags
    return ReproInputs(
        survey=survey,
        survey_id="0123456789abcdef",
        version=survey.get("version") or 1,
        survey_checksum=_checksum(survey),
        plan=plan,
        kit=_kit(engine),
        versions={"spec": "osp-survey/0.1", "platform (osp-app)": "0.0.0"},
        runtime_config=runtime_config(plan),
        data=ReproData(_responses(fixture), "every-page") if data else None,
        **kw,
    )


def _extract(content: bytes, dest: Path) -> Path:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        names = z.namelist()
        roots = {n.split("/", 1)[0] for n in names}
        assert len(roots) == 1, roots
        z.extractall(dest)
    return dest / roots.pop()


def _run(cmd: list[str], cwd: Path) -> tuple[int, dict[str, Any]]:
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=120
    )
    assert proc.returncode in (0, 1), proc.stderr
    assert proc.stdout, f"no report (exit {proc.returncode}): {proc.stderr}"
    return proc.returncode, json.loads(proc.stdout)


def _replay_py(root: Path, *extra: str) -> tuple[int, dict[str, Any]]:
    return _run([sys.executable, "-I", "replay/replay.py", "--json", *extra], root)


def _replay_mjs(root: Path) -> tuple[int, dict[str, Any]]:
    assert NODE is not None
    return _run([NODE, "replay/replay.mjs", "--json"], root)


# -- the zip -----------------------------------------------------------------------------


def test_byte_for_byte_deterministic() -> None:
    a = build_repro_package(_inputs("13-randomiser-blocks"))
    b = build_repro_package(_inputs("13-randomiser-blocks"))
    assert a.content == b.content and a.filename == b.filename
    assert hashlib.sha256(a.content).hexdigest() == hashlib.sha256(b.content).hexdigest()
    with zipfile.ZipFile(io.BytesIO(a.content)) as z:
        assert [i.filename for i in z.infolist()] == sorted(i.filename for i in z.infolist())
        assert {i.date_time for i in z.infolist()} == {(2000, 1, 1, 0, 0, 0)}
    # a different input gives a different package
    assert build_repro_package(_inputs("14-item-order-shuffle")).content != a.content


def test_file_list_with_and_without_data() -> None:
    full = build_repro_package(_inputs("13-randomiser-blocks"))
    assert full.filename == "survey-01234567-v1-repro.zip"
    expected = [
        "LICENSE.md",
        "README.md",
        "checksums.sha256",
        "data/codebook.json",
        "data/codebook.md",
        "data/responses.csv",
        "data/responses.json",
        "exports/lss-diagnostics.json",
        "exports/survey.lss",
        "exports/survey.xlsx",
        "exports/xlsform-diagnostics.json",
        "manifest.json",
        "replay/osp_engine/__init__.py",
        "replay/osp_engine/random.py",
        "replay/replay.py",
        "survey/plan.json",
        "survey/runtime-config.json",
        "survey/survey.json",
    ]
    if BUNDLE.is_file():
        expected += ["replay/engine.js", "replay/replay.mjs"]
    assert full.files == sorted(expected)
    bare = build_repro_package(_inputs("13-randomiser-blocks", data=False))
    assert not [f for f in bare.files if f.startswith("data/")]
    with zipfile.ZipFile(io.BytesIO(bare.content)) as z:
        root = z.namelist()[0].split("/")[0]
        manifest = json.loads(z.read(f"{root}/manifest.json"))
        readme = z.read(f"{root}/README.md").decode()
    assert manifest["includesData"] is False and manifest["responses"] == 0
    assert "no participant data" in readme
    assert "osp-runtime-plan/1" in readme and manifest["survey"]["checksumOk"] is True


def test_checksums_sha256_verifies(tmp_path: Path) -> None:
    pkg = build_repro_package(_inputs("15-choice-order-shuffle"))
    root = _extract(pkg.content, tmp_path)
    lines = (root / "checksums.sha256").read_text().splitlines()
    listed = {}
    for line in lines:
        digest, path = line.split("  ", 1)
        listed[path] = digest
    on_disk = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert sorted(listed) == [p for p in on_disk if p != "checksums.sha256"]
    for path, digest in listed.items():
        assert hashlib.sha256((root / path).read_bytes()).hexdigest() == digest, path
    tool = shutil.which("sha256sum") or shutil.which("shasum")
    if tool:
        cmd = [tool, "-c", "checksums.sha256"]
        if tool.endswith("shasum"):
            cmd[1:1] = ["-a", "256"]
        assert subprocess.run(cmd, cwd=root, capture_output=True).returncode == 0
        (root / "survey" / "plan.json").write_text("{}")
        assert subprocess.run(cmd, cwd=root, capture_output=True).returncode != 0


def test_manifest_versions_checksums_and_vendored_prng() -> None:
    inp = _inputs("16-assign")
    pkg = build_repro_package(inp)
    with zipfile.ZipFile(io.BytesIO(pkg.content)) as z:
        root = z.namelist()[0].split("/")[0]
        m = json.loads(z.read(f"{root}/manifest.json"))
        vendored = z.read(f"{root}/replay/osp_engine/random.py")
        plan = json.loads(z.read(f"{root}/survey/plan.json"))
        survey = json.loads(z.read(f"{root}/survey/survey.json"))
    assert m["format"] == "osp-repro-package/1"
    assert m["plan"]["checksum"] == inp.plan["checksum"] == plan["checksum"]
    assert m["plan"]["planVersion"] == "osp-runtime-plan/1" and m["plan"]["source"] == "published"
    assert m["survey"]["checksum"] == _checksum(survey)
    assert vendored == Path(osp_engine.random.__file__).read_bytes()


def test_license_note() -> None:
    survey = json.loads((FIXTURES / "13-randomiser-blocks" / "survey.json").read_text())
    survey["metadata"]["license"] = "CC-BY-4.0"
    pkg = build_repro_package(_inputs("13-randomiser-blocks", survey=survey, data=False))
    with zipfile.ZipFile(io.BytesIO(pkg.content)) as z:
        root = z.namelist()[0].split("/")[0]
        text = z.read(f"{root}/LICENSE.md").decode()
    assert "**CC-BY-4.0**" in text and "MIT License" in text
    plain = build_repro_package(_inputs("13-randomiser-blocks", data=False))
    with zipfile.ZipFile(io.BytesIO(plain.content)) as z:
        text = z.read(f"{z.namelist()[0].split('/')[0]}/LICENSE.md").decode()
    assert "has not set a licence" in text


def test_without_engine_bundle_no_replay_mjs() -> None:
    pkg = build_repro_package(_inputs("13-randomiser-blocks", engine=False))
    assert "replay/replay.mjs" not in pkg.files and "replay/engine.js" not in pkg.files
    assert "replay/replay.py" in pkg.files


# -- replay.py ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", RECORD_FIXTURES)
def test_replay_py_matches(fixture: str, tmp_path: Path) -> None:
    root = _extract(build_repro_package(_inputs(fixture)).content, tmp_path)
    code, report = _replay_py(root)
    assert report["plan"]["checksumOk"] is True
    expected_bad = {k[1]: v for k, v in INJECTED.items() if k[0] == fixture}
    for r in report["responses"]:
        if r["responseId"] in expected_bad:
            assert r["status"] == "mismatch"
            assert [m["what"] for m in r["mismatches"]] == [expected_bad[r["responseId"]]]
        else:
            assert r["status"] == "match", r
    assert len(report["responses"]) == len(list((RECORDS / fixture).glob("*.json")))
    assert code == (1 if expected_bad else 0)


def test_replay_py_checks_orders_and_assignments(tmp_path: Path) -> None:
    """The fixtures with random decisions really are checked (not vacuously matched)."""
    checked = {}
    for fixture in ("13-randomiser-blocks", "14-item-order-shuffle", "15-choice-order-shuffle"):
        root = _extract(build_repro_package(_inputs(fixture)).content, tmp_path / fixture)
        _, report = _replay_py(root)
        checked[fixture] = sum(r["checks"] for r in report["responses"])
    assert all(n > 0 for n in checked.values()), checked
    root = _extract(build_repro_package(_inputs("16-assign")).content, tmp_path / "16")
    _, report = _replay_py(root)
    control = next(r for r in report["responses"] if r["responseId"] == "resp-control")
    assert control["status"] == "match" and control["checks"] == 1


def _tamper(root: Path) -> None:
    path = root / "data" / "responses.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    order = doc["responses"][0]["orders"]["blocks"]["r_blocks"]
    doc["responses"][0]["orders"]["blocks"]["r_blocks"] = list(reversed(order))
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_tampered_order_is_a_mismatch(tmp_path: Path) -> None:
    root = _extract(build_repro_package(_inputs("13-randomiser-blocks")).content, tmp_path)
    assert _replay_py(root)[0] == 0
    _tamper(root)
    code, report = _replay_py(root)
    assert code == 1
    (r,) = report["responses"]
    assert r["status"] == "mismatch"
    assert [m["what"] for m in r["mismatches"]] == ["orders.blocks.r_blocks"]
    text = subprocess.run(
        [sys.executable, "-I", "replay/replay.py"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    assert "MISMATCH" in text and "orders.blocks.r_blocks" in text


def test_tampered_plan_fails_its_checksum(tmp_path: Path) -> None:
    root = _extract(build_repro_package(_inputs("13-randomiser-blocks")).content, tmp_path)
    plan = json.loads((root / "survey" / "plan.json").read_text())
    plan["title"] = {"en": ["changed"]}
    (root / "survey" / "plan.json").write_text(json.dumps(plan))
    code, report = _replay_py(root)
    assert code == 1 and report["plan"]["checksumOk"] is False


def test_replay_py_without_data(tmp_path: Path) -> None:
    root = _extract(
        build_repro_package(_inputs("13-randomiser-blocks", data=False)).content, tmp_path
    )
    code, report = _replay_py(root)
    assert code == 0 and report["responses"] == [] and "no participant data" in report["note"]


def test_replay_py_bad_seed_and_unknown_order(tmp_path: Path) -> None:
    root = _extract(build_repro_package(_inputs("13-randomiser-blocks")).content, tmp_path)
    path = root / "data" / "responses.json"
    doc = json.loads(path.read_text())
    good = doc["responses"][0]
    doc["responses"] = [
        {**copy.deepcopy(good), "responseId": "bad-seed", "seed": 0},
        {**copy.deepcopy(good), "responseId": "lime", "allocationMode": "limesurvey-native"},
        {**copy.deepcopy(good), "responseId": "ghost", "orders": {"blocks": {"nope": ["a"]}}},
    ]
    path.write_text(json.dumps(doc))
    code, report = _replay_py(root)
    by = {r["responseId"]: r for r in report["responses"]}
    assert code == 1
    assert by["bad-seed"]["status"] == "mismatch"
    assert by["lime"]["status"] == "skipped"
    assert by["ghost"]["mismatches"][0]["what"] == "orders.blocks.nope"
    path.write_text("not json")
    proc = subprocess.run(
        [sys.executable, "-I", "replay/replay.py"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 2 and "can't read" in proc.stderr


# -- replay.mjs --------------------------------------------------------------------------


@needs_node
@pytest.mark.parametrize("fixture", RECORD_FIXTURES)
def test_replay_mjs_matches(fixture: str, tmp_path: Path) -> None:
    root = _extract(build_repro_package(_inputs(fixture)).content, tmp_path)
    code, report = _replay_mjs(root)
    assert report["plan"]["checksumOk"] is True
    for r in report["responses"]:
        assert r["status"] == "match", r
        assert r["checks"] > 0
    assert code == 0


@needs_node
def test_replay_mjs_tampered_order(tmp_path: Path) -> None:
    root = _extract(build_repro_package(_inputs("13-randomiser-blocks")).content, tmp_path)
    _tamper(root)
    code, report = _replay_mjs(root)
    assert code == 1
    (r,) = report["responses"]
    assert [m["what"] for m in r["mismatches"]] == ["orders.blocks.r_blocks"]
