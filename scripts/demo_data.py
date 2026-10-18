#!/usr/bin/env python3
"""Static data for the serverless Pages demo (task DEMO2, `make docs-demo`).

The demo builder (web/builder/demo-site/) runs with no server: every API call is answered
in the browser (web/builder/src/lib/demo/). What the builder fetches that is not about the
survey itself (property schemas, themes and presets, retention options, version, health,
the panel profile, the bank list with the bundled instruments) comes from
the real Python packages, through the real API, here: a throwaway osp-api on a fresh
SQLite store in a temp directory, called in-process as the dev researcher, with the demo
study created through ``POST /api/surveys``. Nothing is served and nothing is kept.

    uv run python scripts/demo_data.py [--out web/builder/demo-site/public/data/demo-data.json]

The output is generated (gitignored), never edited by hand.
"""

from __future__ import annotations

import argparse
import base64
import json
import secrets
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
STUDY = REPO / "web" / "builder" / "demo-site" / "study.json"
OUT = REPO / "web" / "builder" / "demo-site" / "public" / "data" / "demo-data.json"


def collect(db_dir: Path, study: dict[str, Any]) -> dict[str, Any]:
    from fastapi.testclient import TestClient
    from osp_api.app import create_app
    from osp_api.identity import Dev
    from osp_app import build_services
    from osp_spec.theme import PRESETS
    from osp_store import Keyring, Store, create_engine, migrate

    engine = create_engine(f"sqlite:///{db_dir / 'demo.db'}")
    migrate(engine)
    key = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    store = Store(engine, Keyring({"k1": key}, active="k1"))
    app = create_app(builder=build_services(store), identity=Dev(env="dev", host="127.0.0.1"))
    out: dict[str, Any] = {"version": 1, "get": {}}
    try:
        with TestClient(app) as client:

            def get(path: str) -> Any:
                r = client.get(path)
                if r.status_code != 200:
                    raise SystemExit(f"demo_data: GET {path} -> {r.status_code}: {r.text[:300]}")
                return r.json()

            created = client.post(
                "/api/surveys", json={"title": "Coffee and focus", "survey": study}
            )
            if created.status_code != 201:
                msg = f"demo_data: create -> {created.status_code}: {created.text[:500]}"
                raise SystemExit(msg)
            # Static GETs, served verbatim by the demo (keyed by path + query).
            for path in (
                "/api/health",
                "/api/version",
                "/api/me",
                "/api/meta/property-schemas",
                "/api/meta/retention",
                "/api/themes",
                "/api/panel-profile",
                "/api/panel-profile/schemas",
                "/api/bank/library",
                "/api/bank/stubs",
            ):
                out["get"][path] = get(path)
            out["bankList"] = get("/api/bank?pageSize=200")
            items: dict[str, Any] = {}
            for s in out["get"]["/api/bank/library"]:
                items[s["id"]] = get(f"/api/bank/{s['id']}")
            out["bankItems"] = items
            out["presets"] = {
                name: p.model_dump(mode="json", by_alias=True) for name, p in PRESETS.items()
            }
    finally:
        engine.dispose()
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    study = json.loads(STUDY.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="osp-demo-") as tmp:
        data = collect(Path(tmp), study)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
    args.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"demo_data: wrote {args.out} ({len(text.encode('utf-8')) // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
