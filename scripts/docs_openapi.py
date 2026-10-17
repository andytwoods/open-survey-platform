#!/usr/bin/env python3
"""API reference page for the docs site, generated from `contract/openapi.json` (task D2).

Two ways in:

- As an MkDocs hook (`hooks:` in /mkdocs.yml): `on_files` adds `reference/api.md` to the
  site at build time, so the page is never committed and can never go stale against the
  contract (`make contract-check` keeps the contract itself fresh).
- As a script, for a look at the output: `uv run python scripts/docs_openapi.py > api.md`.

Standard library only (plus MkDocs when run as a hook). Everything is rendered from the
contract: one section per tag, one heading per operation (id = `operationId`, so other
pages can link `reference/api.md#applyOps`), then every schema with its properties.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
CONTRACT = REPO / "contract" / "openapi.json"
PAGE = "reference/api.md"

# Tags in the order they read best; any other tag follows alphabetically.
TAG_ORDER = ["me", "meta", "surveys", "ops", "themes", "results", "participant"]
TAG_TITLES = {
    "me": "Who am I",
    "meta": "Metadata and schemas",
    "surveys": "Surveys",
    "ops": "Editing (ops, undo, redo)",
    "themes": "Themes",
    "results": "Results",
    "participant": "Participant sessions",
}
TAG_INTROS = {
    "me": "Who the host says the researcher is, and their labs.",
    "meta": (
        "Catalogues the builder reads at start-up: the op registry, property schemas, "
        "the survey JSON Schema, export targets, retention options, and the expression "
        "parser and printer."
    ),
    "surveys": (
        "Drafts, history, publishing, exports and the reproducibility package. Every "
        "route checks the researcher's role in the survey's lab; a survey in a lab you have "
        "no role in is a 404."
    ),
    "ops": (
        "Every survey edit is an op applied to a draft at a known `baseRevision`. A stale "
        "revision is a 409 with `currentRevision`; a rejected edit is a 422 with "
        "diagnostics. Undo and redo replay the op history."
    ),
    "themes": "The lab's theme library.",
    "results": (
        "Aggregated results per question (never raw answers, except the audited verbatim "
        "text pages) and the export audit. Needs the `survey.export` role (owner or editor)."
    ),
    "participant": (
        "Public endpoints for the participant app. No sign-in: a session holds a bearer "
        "resume token. Hosts forward these unsigned and rate-limit by client address."
    ),
}
METHODS = ["get", "post", "put", "patch", "delete"]


def load_spec(path: Path = CONTRACT) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# --- Markdown helpers ---------------------------------------------------------------


def _cell(text: str) -> str:
    """One table cell: no pipes or line breaks."""
    return " ".join(text.replace("|", "\\|").split())


def _code(text: str) -> str:
    return f"`{text}`"


def _ref_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def _anchor(name: str) -> str:
    return f"[{name}](#{name})"


def type_str(schema: dict[str, Any] | None) -> str:
    """A short, human type for a schema: `string`, `integer`, `array of X`, `A | B`…"""
    if not schema:
        return "any"
    if "$ref" in schema:
        return _anchor(_ref_name(schema["$ref"]))
    for key in ("anyOf", "oneOf"):
        if key in schema:
            parts = [type_str(s) for s in schema[key]]
            return " \\| ".join(dict.fromkeys(parts))
    if "allOf" in schema:
        return " + ".join(type_str(s) for s in schema["allOf"])
    if "enum" in schema:
        return " \\| ".join(_code(json.dumps(v)) for v in schema["enum"])
    if "const" in schema:
        return _code(json.dumps(schema["const"]))
    t = schema.get("type")
    if isinstance(t, list):
        return " \\| ".join(str(x) for x in t)
    if t == "array":
        return f"array of {type_str(schema.get('items'))}"
    if t == "object":
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict) and extra and not schema.get("properties"):
            return f"object of {type_str(extra)}"
        return "object"
    if t is None:
        return "any"
    fmt = schema.get("format")
    return f"{t} ({fmt})" if fmt else str(t)


def _constraints(schema: dict[str, Any]) -> list[str]:
    out = []
    for key, label in (
        ("minimum", "min"),
        ("maximum", "max"),
        ("exclusiveMinimum", "greater than"),
        ("exclusiveMaximum", "less than"),
        ("minLength", "min length"),
        ("maxLength", "max length"),
        ("minItems", "min items"),
        ("maxItems", "max items"),
        ("pattern", "pattern"),
    ):
        if key in schema:
            out.append(f"{label} {_code(str(schema[key]))}")
    if "default" in schema:
        out.append(f"default {_code(json.dumps(schema['default']))}")
    return out


def _describe(schema: dict[str, Any] | None) -> str:
    """Description plus constraints, for a table cell."""
    if not schema:
        return ""
    bits = []
    if schema.get("description"):
        bits.append(schema["description"].rstrip(". "))
    # Constraints that live inside anyOf branches (e.g. `string | null` with maxLength).
    nested = [s for s in schema.get("anyOf", []) if isinstance(s, dict)]
    for s in [schema, *nested]:
        bits.extend(_constraints(s))
    return _cell("; ".join(dict.fromkeys(bits)))


# --- Rendering --------------------------------------------------------------------


def _operations(spec: dict[str, Any]) -> dict[str, list[tuple[str, str, dict[str, Any]]]]:
    by_tag: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for path, item in spec.get("paths", {}).items():
        for method in METHODS:
            op = item.get(method)
            if not op:
                continue
            tags = op.get("tags") or ["other"]
            by_tag.setdefault(tags[0], []).append((method, path, op))
    return by_tag


def _tag_sort_key(tag: str) -> tuple[int, str]:
    return (TAG_ORDER.index(tag) if tag in TAG_ORDER else len(TAG_ORDER), tag)


def _params_table(params: list[dict[str, Any]]) -> list[str]:
    lines = ["| Parameter | In | Type | Required | Notes |", "|---|---|---|---|---|"]
    for p in params:
        schema = p.get("schema", {})
        notes = _describe({**schema, "description": p.get("description", "")})
        lines.append(
            f"| {_code(p['name'])} | {p.get('in', '')} | {type_str(schema)} | "
            f"{'yes' if p.get('required') else 'no'} | {notes} |"
        )
    return lines


def _body_type(content: dict[str, Any] | None) -> str:
    if not content:
        return "none"
    parts = []
    for media, body in content.items():
        t = type_str(body.get("schema"))
        parts.append(t if media == "application/json" else f"{t} ({media})")
    return ", ".join(dict.fromkeys(parts))


def render_operation(method: str, path: str, op: dict[str, Any]) -> list[str]:
    op_id = op.get("operationId") or f"{method}-{path}".replace("/", "-")
    lines = [f"### {method.upper()} `{path}` {{ #{op_id} }}", ""]
    # FastAPI's `summary` is the handler's name in title case, so the operation id (what
    # the generated client calls the method) is the useful name.
    lines += [f"Operation id: `{op_id}`.", ""]
    description = op.get("description")
    if description:
        lines += [description.strip(), ""]
    params = op.get("parameters") or []
    if params:
        lines += _params_table(params) + [""]
    body = op.get("requestBody")
    if body:
        required = " (required)" if body.get("required") else ""
        lines += [f"Request body{required}: {_body_type(body.get('content'))}", ""]
    responses = op.get("responses") or {}
    if responses:
        lines += ["| Status | Body | Meaning |", "|---|---|---|"]
        for status, r in responses.items():
            lines.append(
                f"| {status} | {_body_type(r.get('content'))} | {_cell(r.get('description', ''))} |"
            )
        lines.append("")
    return lines


def render_schema(name: str, schema: dict[str, Any]) -> list[str]:
    lines = [f"### {name} {{ #{name} }}", ""]
    if schema.get("description"):
        lines += [schema["description"].strip(), ""]
    props = schema.get("properties") or {}
    if props:
        required = set(schema.get("required") or [])
        lines += ["| Property | Type | Required | Notes |", "|---|---|---|---|"]
        for prop, ps in props.items():
            lines.append(
                f"| {_code(prop)} | {type_str(ps)} | {'yes' if prop in required else 'no'} | "
                f"{_describe(ps)} |"
            )
        if schema.get("additionalProperties") is False:
            lines.append("")
            lines.append("No other properties are accepted.")
        lines.append("")
    elif "enum" in schema or schema.get("type") != "object":
        lines += [f"Type: {type_str(schema)}", ""]
    else:
        lines += ["An object with no fixed properties.", ""]
    return lines


def render(spec: dict[str, Any]) -> str:
    info = spec.get("info", {})
    by_tag = _operations(spec)
    n_ops = sum(len(v) for v in by_tag.values())
    schemas = spec.get("components", {}).get("schemas", {})
    lines = [
        "---",
        "title: API reference",
        "---",
        "",
        f"# {info.get('title', 'API')}",
        "",
        "This page is generated from [`contract/openapi.json`]"
        "(https://github.com/andytwoods/open-survey-platform/blob/main/contract/openapi.json) "
        "when the site is built, so it always matches the committed contract "
        f"({n_ops} operations, {len(schemas)} schemas). The TypeScript client the builder "
        "uses (`web/api-client`) is generated from the same file.",
        "",
        '!!! note "Reading the paths"',
        "    Paths are as `osp-api` sees them. A host usually forwards them under its own "
        "prefix (for example `/osp/api`) and signs the researcher's identity on the way "
        "through; see [Hosting](../hosting.md). Participant endpoints (`/api/s/…` and "
        "`/api/sessions/…`) are forwarded unsigned.",
        "",
        "Errors are JSON `{code, message}` ([ErrorBody](#ErrorBody)). A stale `baseRevision` "
        "is a 409 with the current revision; a rejected edit is a 422 with diagnostics. In "
        "development, `make dev` also serves the interactive Swagger UI at "
        "`http://localhost:8000/api/docs`.",
        "",
    ]
    for tag in sorted(by_tag, key=_tag_sort_key):
        title = TAG_TITLES.get(tag, tag.capitalize())
        lines += [f"## {title} {{ #tag-{tag} }}", ""]
        if tag in TAG_INTROS:
            lines += [TAG_INTROS[tag], ""]
        ops = sorted(by_tag[tag], key=lambda t: (t[1], METHODS.index(t[0])))
        lines += ["| Method | Path | Operation |", "|---|---|---|"]
        for method, path, op in ops:
            op_id = op.get("operationId", "")
            lines.append(f"| {method.upper()} | `{path}` | [{op_id}](#{op_id}) |")
        lines.append("")
        for method, path, op in ops:
            lines += render_operation(method, path, op)
    lines += ["## Schemas", ""]
    for name in sorted(schemas):
        lines += render_schema(name, schemas[name])
    return "\n".join(lines).rstrip() + "\n"


# --- MkDocs hook ------------------------------------------------------------------


def on_files(files, config):  # noqa: ANN001  (MkDocs hook signature)
    """Add the generated page to the build (MkDocs 1.6 `File.generated`)."""
    from mkdocs.structure.files import File

    content = render(load_spec())
    files.append(File.generated(config, PAGE, content=content))
    return files


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    path = Path(args[0]) if args else CONTRACT
    sys.stdout.reconfigure(encoding="utf-8")  # the page has "…"; Windows consoles are cp1252
    sys.stdout.write(render(load_spec(path)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
