"""JSON Schema export of the `osp-survey` model.

The committed copy is `python/osp-spec/schema/survey.schema.json`; a test fails when it is
stale. Regenerate with `uv run python python/osp-spec/scripts/export_schema.py`.
"""

from __future__ import annotations

import json
from typing import Any

from .model import SPEC_VERSION, Survey

SCHEMA_ID = f"urn:osp:schema:{SPEC_VERSION.replace('/', ':')}:survey"


def json_schema() -> dict[str, Any]:
    """The JSON Schema (draft 2020-12) for an `osp-survey` document."""
    schema = Survey.model_json_schema(by_alias=True, mode="validation")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        **schema,
    }


def json_schema_text() -> str:
    """`json_schema()` serialised exactly as the committed file is."""
    return json.dumps(json_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
