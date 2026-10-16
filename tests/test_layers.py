"""S2 acceptance: the import-linter layer contracts exist, cover every package, and bite.

The violation tests never touch the real tree. They copy every package's sources into
a temp dir, inject one bad import there, and run lint-imports against that copy
(PYTHONPATH puts the copy ahead of the editable installs).
"""

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"


def _config() -> dict:
    return tomllib.loads(PYPROJECT.read_text())["tool"]["importlinter"]


def _package_modules() -> list[str]:
    return sorted(
        p.name.replace("-", "_")
        for p in (REPO / "python").iterdir()
        if (p / "pyproject.toml").exists()
    )


def _layer_modules() -> set[str]:
    contract = next(c for c in _config()["contracts"] if c["id"] == "layers")
    return {m.strip() for layer in contract["layers"] for m in layer.split("|")}


def test_every_package_is_registered_in_a_layer():
    mods = set(_package_modules())
    assert mods == set(_config()["root_packages"])
    assert mods == _layer_modules()


def _lint_with_injected(tmp_path: Path, module: str, code: str) -> subprocess.CompletedProcess:
    src_root = tmp_path / "src"
    for mod in _package_modules():
        pkg_dir = REPO / "python" / mod.replace("_", "-") / "src" / mod
        shutil.copytree(pkg_dir, src_root / mod)
    (src_root / module / "_injected_violation.py").write_text(code)
    shutil.copy(PYPROJECT, tmp_path / "pyproject.toml")
    env = {**os.environ, "PYTHONPATH": str(src_root)}
    lint = Path(sys.executable).with_name("lint-imports")
    return subprocess.run(
        [str(lint), "--no-cache", "--config", str(tmp_path / "pyproject.toml")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )


def test_clean_copy_passes(tmp_path):
    result = _lint_with_injected(tmp_path, "osp_expr", "X = 1\n")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("module", "code", "contract"),
    [
        ("osp_expr", "import osp_spec\n", "Layers L0-L6"),  # L0 -> L1 (upward)
        ("osp_spec", "import osp_api\n", "Layers L0-L6"),  # L1 -> L6 (upward)
        ("osp_engine", "import osp_ops\n", "Layers L0-L6"),  # same-layer siblings
        ("osp_engine", "import socket\n", "L0-L3 do no I/O"),
        ("osp_targets", "import random\n", "L0-L3 do no I/O"),
        ("osp_qa", "from urllib import request\n", "L0-L3 do no I/O"),
        ("osp_app", "import fastapi\n", "Nothing below L6"),
    ],
)
def test_violation_breaks_contract(tmp_path, module, code, contract):
    result = _lint_with_injected(tmp_path, module, code)
    out = result.stdout + result.stderr
    assert result.returncode != 0, out
    broken_lines = [line for line in out.splitlines() if line.endswith("BROKEN")]
    assert any(line.startswith(contract) for line in broken_lines), out
