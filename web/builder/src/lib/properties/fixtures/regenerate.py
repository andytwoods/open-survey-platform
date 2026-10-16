"""Regenerate `property-schemas.json`, the property panel's test fixture.

It is exactly what `GET /api/meta/property-schemas` serves (`property_schemas_json()`).
Run after editing `python/osp-spec/src/osp_spec/properties/*.yaml`:

    uv run python web/builder/src/lib/properties/fixtures/regenerate.py

`--check` exits 1 when the committed file is stale (no write).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from osp_spec.property_schema import property_schemas_json

OUT = Path(__file__).with_name("property-schemas.json")


def render() -> str:
    return json.dumps(property_schemas_json(), indent=2, ensure_ascii=False) + "\n"


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
