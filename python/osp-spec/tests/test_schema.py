"""The committed JSON Schema must match the model."""

from __future__ import annotations

import json
from pathlib import Path

from osp_spec import SPEC_VERSION, json_schema
from osp_spec.model import FLOW_NODE_TYPES, QUESTION_TYPES
from osp_spec.schema import json_schema_text

COMMITTED = Path(__file__).resolve().parents[1] / "schema" / "survey.schema.json"


def test_committed_schema_is_current() -> None:
    assert COMMITTED.read_text(encoding="utf-8") == json_schema_text(), (
        "python/osp-spec/schema/survey.schema.json is stale; regenerate with "
        "`uv run python python/osp-spec/scripts/export_schema.py`"
    )


def test_schema_shape() -> None:
    schema = json_schema()
    assert schema["$schema"].endswith("2020-12/schema")
    assert schema["properties"]["specVersion"]["const"] == SPEC_VERSION
    assert set(schema["required"]) == {"specVersion", "id", "metadata"}
    assert schema["additionalProperties"] is False
    text = json.dumps(schema)
    for tag in (*QUESTION_TYPES, *FLOW_NODE_TYPES):
        assert f'"const": "{tag}"' in text
    # Python-keyword fields are exported under their JSON names.
    branch = schema["$defs"]["BranchNode"]["properties"]
    assert "if" in branch and "else" in branch and "if_" not in branch
