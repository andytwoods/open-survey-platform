# osp-ops

**Layer:** L2. Imports `osp-spec` and `osp-expr` only (enforced by `uv run lint-imports`). No I/O: no network, database, clock or global randomness.

**Job:** the survey edit registry. Every survey edit is a named op (AGENTS.md rule 2), dispatched by id from the builder, CLI, REST API and MCP.

```python
from osp_ops import run, apply_transaction, Draft

res = run("set_property", survey, {"target": "q12", "property": "required", "value": True})
res.ok, res.survey, res.inverse, res.patch, res.diagnostics
```

## Contract (enforced once, in `registry.py`)

- An op is `id` + pydantic params model + `run(survey, params) -> OpResult(survey', inverse, patch, diagnostics)`. `enabled(op_id, survey, params)` is a dry run: `True` or the reason.
- Surveys are plain JSON (a `Survey` model is accepted too). Ops never mutate their input.
- Input and output must be **structurally** valid (`osp_spec.parse` succeeds). Semantic problems (forward refs, missing translations) are allowed in a draft and come back as `diagnostics`: the validator's full output for survey'.
- `patch` is RFC 6902 from survey to survey' (`osp_ops.patch`: type-strict diff, single-element moves become one `move`).
- `inverse` is an `Invocation` that restores the input exactly. Undo and redo are just running inverses.
- An op may not add a duplicate id. Nothing raises: errors are `op.*` diagnostics (`OP_CODES`).

## Transactions

`apply_transaction(Draft(survey, revision), [ops], base_revision)` is all or nothing. It returns `status` (`ok` / `rejected` with `failed_index` / `conflict` when `base_revision` is stale, i.e. HTTP 409), the new draft (revision + 1 if anything changed), the concatenated patch and one inverse transaction (the inverses, reversed). Undo is applying that inverse; its inverse is the redo. History storage lives in osp-app.

Each op in a transaction must leave the survey structurally valid. So "move a page's last question, then delete the page" has to be done in the other order (or with `delete_page`).

## Dangling references (delete policy)

Deletes are **rejected by default** when anything still refers to what they delete, with one `op.dangling_ref` diagnostic per referring site (pointers into the survey as it was before the delete). There are two opt-ins:

| flag | effect |
|---|---|
| `cascade: true` | repair the references: clear optional conditions (`showIf`, `constraint`), drop `${id}` pipes, remove `block`/`quotaCheck` flow nodes for a deleted block/quota, clear `quota.onFull.block`, remove the variable from `assign` nodes (and drop empty ones), inline a deleted choice list's choices into its questions. **Required** expressions (branch `if`, quota `when`, computed `expr`) are never rewritten: `op.cascade_blocked`. The inverse is an exact `apply_patch`. |
| `force: true` | delete anyway and leave the references dangling (the validator then reports `ref.unknown` etc.). Inverses use it so undo always restores the prior state exactly. |

The walker in `doc.py` finds the sites. A validator guard backs it up: a delete without `force` may not add any new `ref.unknown*` error. The same rule covers choice codes (`delete_choice`, a code change in `set_choice`, `bulk_paste_choices` in replace mode): conditions comparing an answer with that code (`q == 2`, `contains(q, 2)`) block the change unless `cascade`/`force` is set. `set_languages` dropping a language that still has translations works the same way.

Why this policy: silently clearing a condition changes who sees a question. That's a research-design change, so it must be explicit.

## Ops

| area | ops |
|---|---|
| questions | `add_question`, `delete_question`, `duplicate_question`, `move_question`, `set_property` (any object, or `/metadata`, `/settings`) |
| pages / blocks | `add_page`, `delete_page`, `rename_page`, `move_page`, `add_block`, `delete_block`, `rename_block`, `move_block` |
| choices | `add_choice`, `delete_choice`, `move_choice`, `set_choice`, `bulk_paste_choices` |
| choice lists | `create_choice_list`, `delete_choice_list` |
| conditions | `set_condition` (AST or text, parsed with osp-expr) |
| flow | `insert_flow_node`, `delete_flow_node`, `move_flow_node` |
| variables | `add_variable`, `delete_variable` |
| metadata | `set_title`, `set_languages` |
| survey | `replace_survey` (the JSON view's Apply), `apply_patch` |

`op_catalogue()` and `openapi_components()` export ids, labels and params JSON Schemas for osp-api.

## Adding an op

Write it in an area module (`osp_ops/<area>_ops.py`) with `@op(...)`, and add at least one succeeding params example to `EXAMPLES` in `tests/test_guard.py`. The completeness guard then runs the inverse round-trip and the Hypothesis fuzzers (hostile and near-miss params, hostile surveys) on it automatically. It fails if an op has no examples.

Internal package; not published.
