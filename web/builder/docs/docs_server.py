"""Throwaway `osp-api` for the docs screenshots (`make docs-screenshots`, task SHOW1).

The builder e2e server (``../e2e/api_server.py``: a fresh SQLite store in a temp directory,
the dev researcher, the participant app at ``/s/{slug}``) plus one docs-only helper:

- ``POST /api/e2e/docs-fake/{survey_id}?n=150`` fills the survey's latest published version
  with invented responses through ``osp-cli fake-responses`` (``osp_cli.fake_responses``:
  the participant service and the real engine, ``make sim-build``), so the Results
  screenshot shows charts over a realistic number of answers. Every answer is made up
  (AGENTS.md rule 7).

Test-only: never import this, never point it at real data.

    uv run --locked --with uvicorn python web/builder/docs/docs_server.py --port 4618
"""

from __future__ import annotations

import argparse
import importlib.util
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from osp_cli.fake_responses import FakeError, fake_responses
from osp_store import Keyring, Store

E2E_SERVER = Path(__file__).resolve().parents[1] / "e2e" / "api_server.py"


def _e2e_server() -> Any:
    spec = importlib.util.spec_from_file_location("osp_docs_e2e_server", E2E_SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(db_dir: Path, host: str = "127.0.0.1") -> FastAPI:
    e2e = _e2e_server()
    # The e2e server makes its keyring inside build(); keep a handle on it so the fake
    # responses are encrypted with the same key the API reads them with.
    keyrings: list[Keyring] = []
    real_keyring = e2e.Keyring

    def keyring(*args: Any, **kwargs: Any) -> Keyring:
        ring = real_keyring(*args, **kwargs)
        keyrings.append(ring)
        return ring

    e2e.Keyring = keyring
    app: FastAPI = e2e.build(db_dir, host)
    engine = app.state.engine

    def open_store(clock: Callable[[], datetime]) -> Store:
        return Store(engine, keyrings[0], clock)

    @app.post("/api/e2e/docs-fake/{survey_id}", include_in_schema=False)
    def docs_fake(survey_id: str, n: int = 150) -> dict[str, Any]:
        try:
            report = fake_responses(open_store, survey_id, n=n, environ={"OSP_ENV": "dev"})
        except FakeError as exc:
            return {"error": str(exc)}
        return report.summary()

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4618)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="osp-docs-") as tmp:
        uvicorn.run(build(Path(tmp), args.host), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
