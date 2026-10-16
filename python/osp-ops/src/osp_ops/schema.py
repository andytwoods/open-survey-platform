"""The op catalogue as data, for osp-api to expose in OpenAPI (no endpoints here)."""

from __future__ import annotations

from typing import Any

from .registry import OP_CODES, REGISTRY, Invocation


def op_catalogue() -> list[dict[str, Any]]:
    """One entry per op, sorted by id: id, label, area, description and the params
    JSON Schema (draft 2020-12, as pydantic emits it)."""
    return [
        {
            "id": spec.id,
            "label": spec.label,
            "area": spec.area,
            "description": spec.description,
            "paramsSchema": spec.params.model_json_schema(),
        }
        for spec in sorted(REGISTRY.values(), key=lambda s: s.id)
    ]


def openapi_components() -> dict[str, Any]:
    """OpenAPI `components.schemas` entries: `<OpId>Params` per op, plus `OpId` (an enum
    of every op id) and `Invocation`. `$defs` are hoisted so `$ref`s resolve under
    `#/components/schemas/`."""
    schemas: dict[str, Any] = {}
    for spec in sorted(REGISTRY.values(), key=lambda s: s.id):
        name = "".join(part.title() for part in spec.id.split("_")) + "Params"
        schema = spec.params.model_json_schema(ref_template="#/components/schemas/{model}")
        schemas.update(schema.pop("$defs", {}))
        schemas[name] = schema
    schemas["OpId"] = {"type": "string", "enum": sorted(REGISTRY)}
    inv = Invocation.model_json_schema(ref_template="#/components/schemas/{model}")
    schemas.update(inv.pop("$defs", {}))
    schemas["Invocation"] = inv
    schemas["OpErrorCode"] = {"type": "string", "enum": sorted(OP_CODES)}
    return schemas
