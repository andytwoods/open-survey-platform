#!/usr/bin/env python3
"""Contract pipeline: FastAPI app -> contract/openapi.json -> web/api-client/src/schema.d.ts.

    uv run python scripts/contract.py generate   # `make contract`: write both files
    uv run python scripts/contract.py check      # `make contract-check`: exit 1 if stale

The OpenAPI dump is deterministic: sorted keys, 2-space indent, LF line endings on every
platform, trailing newline, no timestamps. `check` regenerates both artefacts in a temp
dir from the *current* app and compares them byte for byte with the committed files, so
changing an endpoint without running `make contract` fails `make check`.

`--app module:attr` (a FastAPI app or a factory) and `--openapi/--ts` exist for tests.
"""

from __future__ import annotations

import argparse
import difflib
import importlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_APP = "osp_api.app:create_app"
OPENAPI_PATH = REPO / "contract" / "openapi.json"
TS_PATH = REPO / "web" / "api-client" / "src" / "schema.d.ts"
API_CLIENT_DIR = REPO / "web" / "api-client"


def load_app(ref: str):
    module_name, _, attr = ref.partition(":")
    obj = getattr(importlib.import_module(module_name), attr or "app")
    return obj() if callable(obj) and not hasattr(obj, "openapi") else obj


def openapi_text(app_ref: str) -> str:
    spec = load_app(app_ref).openapi()
    return json.dumps(spec, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def generate_ts(openapi_file: Path, out_file: Path) -> None:
    cmd = [
        shutil.which("pnpm") or "pnpm",  # pnpm.cmd on Windows: a bare name isn't found
        "-C",
        str(API_CLIENT_DIR),
        "exec",
        "openapi-typescript",
        str(openapi_file),
        "--output",
        str(out_file),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"openapi-typescript failed:\n{result.stderr or result.stdout}")


def _diff(committed: Path, fresh: str, label: str) -> list[str]:
    old = committed.read_text() if committed.exists() else ""
    if old == fresh:
        return []
    lines = list(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            fresh.splitlines(keepends=True),
            f"{label} (committed)",
            f"{label} (regenerated)",
        )
    )
    return lines[:60] + (["... (diff truncated)\n"] if len(lines) > 60 else [])


def cmd_generate(args) -> int:
    args.openapi.parent.mkdir(parents=True, exist_ok=True)
    args.openapi.write_text(openapi_text(args.app), encoding="utf-8", newline="\n")
    generate_ts(args.openapi, args.ts)
    print(f"contract: wrote {args.openapi.relative_to(REPO, walk_up=True)}")
    print(f"contract: wrote {args.ts.relative_to(REPO, walk_up=True)}")
    return 0


def cmd_check(args) -> int:
    with tempfile.TemporaryDirectory(prefix="osp-contract-") as tmp:
        fresh_openapi = Path(tmp) / "openapi.json"
        fresh_openapi.write_text(openapi_text(args.app), encoding="utf-8", newline="\n")
        fresh_ts = Path(tmp) / "schema.d.ts"
        generate_ts(fresh_openapi, fresh_ts)
        problems = {
            "contract/openapi.json": _diff(args.openapi, fresh_openapi.read_text(), "openapi.json"),
            "web/api-client/src/schema.d.ts": _diff(args.ts, fresh_ts.read_text(), "schema.d.ts"),
        }
    stale = {name: diff for name, diff in problems.items() if diff}
    if not stale:
        print("contract-check: openapi.json and TS client are up to date")
        return 0
    for name, diff in stale.items():
        print(f"contract-check: {name} is STALE", file=sys.stderr)
        sys.stderr.writelines(diff)
    print("contract-check: run `make contract` and commit the result.", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["generate", "check"])
    ap.add_argument("--app", default=DEFAULT_APP, help="module:attr of a FastAPI app or factory")
    ap.add_argument("--openapi", type=Path, default=OPENAPI_PATH)
    ap.add_argument("--ts", type=Path, default=TS_PATH)
    args = ap.parse_args(argv)
    try:
        return cmd_generate(args) if args.command == "generate" else cmd_check(args)
    except RuntimeError as exc:
        print(f"contract: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
