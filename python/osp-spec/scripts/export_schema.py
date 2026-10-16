"""Write the committed JSON Schema: `uv run python python/osp-spec/scripts/export_schema.py`."""

from pathlib import Path

from osp_spec.schema import json_schema_text

OUT = Path(__file__).resolve().parents[1] / "schema" / "survey.schema.json"

if __name__ == "__main__":
    OUT.write_text(json_schema_text(), encoding="utf-8")
    print(f"wrote {OUT}")
