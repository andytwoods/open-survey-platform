"""The results page's test fixture (task V2) is what the results API (V1) really answers.

`web/builder/src/lib/results/fixtures/results.json` feeds the page's vitest tests; if the
API's shape or numbers change, this fails until the fixture is regenerated with
`uv run --with uvicorn python web/builder/src/lib/results/fixtures/regenerate.py`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "web/builder/src/lib/results/fixtures/regenerate.py"


def test_results_fixture_is_current() -> None:
    spec = importlib.util.spec_from_file_location("osp_results_fixture", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.OUT.read_text(encoding="utf-8") == module.render(), (
        "results.json is stale: run web/builder/src/lib/results/fixtures/regenerate.py"
    )
