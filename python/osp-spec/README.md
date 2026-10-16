# osp-spec

**Layer:** L1. Imports only packages in lower layers (enforced by `uv run lint-imports`). No I/O: no network, database, clock or global randomness.

**Job:** The `osp-survey` model (pydantic), JSON Schema export, property schema, migrations, semantic validator, `specVersion`. Pure data.

| Module | What |
|---|---|
| `model.py` | `Survey` and its parts. `specVersion: "osp-survey/0.1"` |
| `expr.py` | `Expression = osp_expr.ast.Expr`: the one alias every condition field uses; `references()`; `typecheck()` adapter (active once `osp_expr.static` is merged) |
| `validate.py` | `validate(any) -> list[Diagnostic]`, `parse(any) -> (Survey \| None, diagnostics)`. Never raises |
| `diagnostics.py` | `Diagnostic(severity, code, message, pointer)` and the `CODES` registry |
| `reserved.py` | Reserved variable names (spike-1 Q2) |
| `schema.py` | `json_schema()`; committed copy in `schema/survey.schema.json` |

Regenerate the committed schema after a model change:
`uv run python python/osp-spec/scripts/export_schema.py` (a test fails while it is stale).

Fixture cases: `tests/cases/{valid,invalid}/*.json`, each `{description, expect: [{code, pointer}], survey}`.

Internal package; not published.
