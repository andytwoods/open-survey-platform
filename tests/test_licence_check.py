"""S4 acceptance: the licence gate passes the real tree and fails on copyleft.

No GPL code is ever added: GPL dependencies are synthetic entries passed with --extra.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "licence_check.py"

_spec = importlib.util.spec_from_file_location("licence_check", SCRIPT)
lc = importlib.util.module_from_spec(_spec)
sys.modules["licence_check"] = lc
_spec.loader.exec_module(lc)

POLICY = lc.load_policy()


def _dep(licence, dev=False, eco="js", name="pkg"):
    return lc.Dep(eco, name, "1.0.0", licence, dev)


@pytest.mark.parametrize(
    ("licence", "dev", "ok"),
    [
        ("MIT", False, True),
        ("BSD-3-Clause", False, True),
        ("Apache-2.0", False, True),
        ("ISC", False, True),
        ("0BSD", False, True),
        ("CC0-1.0", False, True),
        ("BlueOak-1.0.0", False, True),
        ("Python-2.0", False, True),
        ("(MIT OR GPL-3.0-or-later)", False, True),  # dual: take the permissive option
        ("Apache-2.0 OR BSD-2-Clause", False, True),
        ("MIT AND BSD-3-Clause", False, True),
        ("Apache-2.0 WITH LLVM-exception", False, True),
        ("MPL-2.0", True, True),  # dev/test only
        ("MPL-2.0", False, False),
        ("CC-BY-4.0", False, True),
        ("Zlib", False, True),
        ("BSL-1.0", False, True),
        ("GPL-3.0-only", True, False),
        ("GPL-2.0-or-later", False, False),
        ("AGPL-3.0-only", True, False),
        ("LGPL-2.1-only", True, False),
        ("BUSL-1.1", True, False),
        ("SSPL-1.0", True, False),
        ("MIT AND GPL-3.0-only", False, False),
        ("GNU General Public License v3 (GPLv3)", True, False),
        (None, True, False),  # unknown fails
        ("SEE LICENSE IN LICENSE.md", True, False),
        ("Permission is hereby granted...\nfull text", True, False),
        ("UNLICENSED", True, False),
        ("((MIT", True, False),  # unparseable fails, never crashes
    ],
)
def test_judge(licence, dev, ok):
    assert lc.judge(_dep(licence, dev), POLICY).ok is ok


def test_classifiers_are_alternatives():
    expr = lc.classifier_expression(
        [
            "License :: OSI Approved :: Apache Software License",
            "License :: OSI Approved :: BSD License",
        ]
    )
    assert expr == "Apache-2.0 OR BSD-3-Clause"
    gpl = lc.classifier_expression(
        ["License :: OSI Approved :: GNU Affero General Public License v3"]
    )
    assert not lc.judge(_dep(gpl, dev=True, eco="python"), POLICY).ok


def test_override_replaces_metadata():
    policy = {**POLICY, "override": [{"ecosystem": "js", "name": "pkg", "licence": "MIT"}]}
    assert lc.judge(_dep("full text\nhere"), policy).ok


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=REPO
    )


def test_real_tree_passes():
    result = _run()
    assert result.returncode == 0, result.stdout + result.stderr


def test_gpl_test_dependency_fails_the_gate(tmp_path):
    """Acceptance (tasks.md S4): a GPL *test* dependency makes the check fail."""
    extra = tmp_path / "extra.json"
    extra.write_text(
        json.dumps(
            [
                {
                    "ecosystem": "python",
                    "name": "fake-gpl-testtool",
                    "licence": "GPL-3.0-only",
                    "dev": True,
                },
                {"ecosystem": "js", "name": "fake-gpl-widget", "licence": "GPL-2.0", "dev": True},
            ]
        )
    )
    result = _run("--extra", str(extra))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "fake-gpl-testtool" in result.stderr
    assert "fake-gpl-widget" in result.stderr


def test_bundled_instruments_are_listed_and_pass():
    listing, problems = lc.instrument_problems(POLICY)
    assert problems == []
    assert any(line.startswith("phq9: public-domain") for line in listing)
    result = _run("--no-python", "--no-js")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "bundled instrument phq9: public-domain" in result.stdout


def test_non_commercial_instrument_fails_the_gate(tmp_path):
    """A non-commercial (or evidence-free) instrument cannot land unnoticed."""
    (tmp_path / "nc.json").write_text(
        json.dumps({"id": "nc", "licence": {"class": "free-noncommercial", "url": "https://x"}})
    )
    result = _run("--no-python", "--no-js", "--instruments", str(tmp_path))
    assert result.returncode == 1
    assert "nc: licence class 'free-noncommercial' may not be bundled" in result.stderr
    assert "nc: licence evidence missing: statement, evidenceDate" in result.stderr


def test_runtime_exception_only_for_named_package():
    assert lc.judge(_dep("MPL-2.0", eco="python", name="certifi"), POLICY).ok
    assert not lc.judge(_dep("MPL-2.0", eco="python", name="other"), POLICY).ok
    assert not lc.judge(_dep("GPL-3.0-only", eco="python", name="certifi"), POLICY).ok
