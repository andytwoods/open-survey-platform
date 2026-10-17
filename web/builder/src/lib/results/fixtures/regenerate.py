"""Regenerate `results.json`, the results page's test fixture (task V2).

It is what the real API answers for V1's hand-checked fixture survey
(`python/osp-app/tests/results_data.py`, seeded as `e2e/api_server.py` does): the plain
query, a query split by condition with every submitted response, and the first page of
the text question's answers. Random ids and times are replaced by fixed ones so the file
is stable. Run after changing the results API:

    uv run --with uvicorn python web/builder/src/lib/results/fixtures/regenerate.py

`--check` exits 1 when the committed file is stale (no write).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

OUT = Path(__file__).with_name("results.json")
SERVER = Path(__file__).resolve().parents[4] / "e2e" / "api_server.py"
ORIGIN = {"Origin": "http://127.0.0.1"}


def _server() -> Any:
    spec = importlib.util.spec_from_file_location("osp_e2e_api_server", SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stable(body: Any, survey_id: str, ids: dict[str, str]) -> Any:
    if isinstance(body, dict):
        out = {}
        for k, v in body.items():
            if k == "surveyId":
                v = "fixture-survey"
            elif k == "generatedAt":
                v = "2026-10-17T12:00:00Z"
            elif k == "watermark":
                v = "fixture-watermark"
            elif k == "responseId":
                v = ids.setdefault(v, f"response-{len(ids) + 1}")
            out[k] = _stable(v, survey_id, ids)
        return out
    if isinstance(body, list):
        return [_stable(v, survey_id, ids) for v in body]
    return body


def render() -> str:
    server = _server()
    with tempfile.TemporaryDirectory(prefix="osp-results-fixture-") as tmp:
        app = server.build(Path(tmp))
        try:
            c = TestClient(app, base_url="http://127.0.0.1")
            survey = c.get("/api/e2e/results-fixture").json()
            created = c.post(
                "/api/surveys", json={"title": "Results", "survey": survey}, headers=ORIGIN
            )
            created.raise_for_status()
            sid = created.json()["id"]
            c.post(f"/api/e2e/results-seed/{sid}", headers=ORIGIN).raise_for_status()
            url = f"/api/surveys/{sid}/results/query"
            plain = c.post(url, json={}, headers=ORIGIN)
            split = c.post(
                url, json={"split": {"condition": "arm"}, "status": "all"}, headers=ORIGIN
            )
            text = c.get(f"/api/surveys/{sid}/results/text/why", params={"limit": 2})
            for r in (plain, split, text):
                r.raise_for_status()
            body = {"plain": plain.json(), "split": split.json(), "text": text.json()}
        finally:
            # Close the SQLite connections before the temp dir (and e2e.db) is removed:
            # Windows can't delete a file another handle still has open.
            app.state.engine.dispose()
    return json.dumps(_stable(body, sid, {}), indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT} is stale; run without --check to regenerate", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
