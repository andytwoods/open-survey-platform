"""Record every document python/osp-spec's own tests pass to the validator, as validator
parity inputs for @osp/spec (task CE4):

    uv run python web/spec/scripts/harvest_spec_tests.py

Runs the osp-spec test suite (without the Hypothesis fuzz test: build_vectors.py makes its
own random JSON) with `osp_spec.validate._parse` wrapped, and writes the distinct inputs to
web/spec/test/vectors/spec-test-inputs.json (committed: the suite takes seconds, too slow to
rerun on every `make check`). build_vectors.py adds Python's diagnostics for each at build
time, so only the inputs can go stale; rerun this after adding validator tests.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "web" / "spec" / "test" / "vectors" / "spec-test-inputs.json"


class Recorder:
    def __init__(self) -> None:
        self.seen: dict[str, Any] = {}

    def pytest_configure(self, config: pytest.Config) -> None:
        import osp_spec  # noqa: F401

        v = sys.modules["osp_spec.validate"]

        original = v._parse

        def recording(data: Any) -> Any:
            try:
                text = json.dumps(data, sort_keys=False, ensure_ascii=True, allow_nan=False)
            except TypeError, ValueError:
                text = None
            if text is not None and text not in self.seen:
                self.seen[text] = copy.deepcopy(data)
            return original(data)

        v._parse = recording


def main() -> int:
    rec = Recorder()
    tests = str(ROOT / "python" / "osp-spec" / "tests")
    code = pytest.main([tests, "-q", "-p", "no:cacheprovider", "-k", "not fuzz"], plugins=[rec])
    if code != 0:
        print("osp-spec tests failed; nothing written", file=sys.stderr)
        return int(code)
    docs = list(rec.seen.values())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(docs, ensure_ascii=True, indent=None) + "\n", encoding="utf-8")
    print(f"{len(docs)} distinct validator inputs -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
