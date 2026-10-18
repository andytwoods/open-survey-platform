# @osp/ops

Every survey edit op of `python/osp-ops` in TypeScript (task CE2, `planning/client-edits.md`):
the same op names, params, error codes and messages, resulting documents, JSON Patches,
inverses and transaction semantics. The builder will apply its edits with this package and
send the patch to the server, which validates and stores it (CE5). Pure: no DOM, no I/O,
no clock, no randomness. Imports only `@osp/engine` (its canonical JSON and SHA-256).

```ts
import { run, applyTransaction, type OpsEnv } from '@osp/ops';

const env: OpsEnv = { validator };   // see "The validator" below
const res = run('set_property', survey, { target: 'q12', property: 'required', value: true }, env);
res.ok, res.survey, res.inverse, res.patch, res.diagnostics

const tx = applyTransaction({ survey, revision: 7 }, [op1, op2], 7, env);
tx.status /* ok | rejected | conflict */, tx.failedIndex, tx.draft, tx.patch, tx.inverse
// undo: applyTransaction(tx.draft, tx.inverse, tx.draft.revision, env); its .inverse is the redo
```

Also exported: `enabled`, `invoke`, `REGISTRY`, `opIds`, `opCatalogue`, `OP_CODES`,
`applyPatch` / `diffPatch` (RFC 6902, as `osp_ops.patch`), `same`, `deepCopy`,
`canonicalJson`, `normaliseText`, `isRich`, `pipesOf`, `fragmentChecksum`, `RESERVED_NAMES`,
`KEYWORDS`, `NO_VALIDATOR`.

## The validator (injected)

The Python ops call the survey validator (`osp_spec.parse` / `validate`, the bank's
`check_fragment`) and the expression parser (`osp_expr.parse`). Those are separate tasks
in TypeScript (CE4, CE1), so `OpsEnv.validator` supplies them:

| hook | used for | without it |
|---|---|---|
| `parse(doc) -> {valid, diagnostics}` | input/output structural check, the duplicate-id, dangling-reference and rich-text guards, every result's `diagnostics` | every document is valid, no diagnostics, so those guards never fire |
| `validate(doc)` (default `parse(doc).diagnostics`) | `change_question_type`'s conflict check | no conflicts are found |
| `checkFragment(fragment)` | `insert_bank_item` | only "exactly one of question, page, block" and the 200-item limit |
| `parseExpression(text)` | `set_condition` with text | text is refused (`op.expr_syntax`); an AST is accepted |

`DEFAULT_ENV` uses `NO_VALIDATOR`. Everything else the ops validate themselves is ported:
the params models, `Ending`, `RedirectTemplate`, `Source`, the hook manifest, the theme and
the expression AST, with pydantic's error types, locations and messages (`src/pyd.ts`,
`src/models.ts`).

## Parity (`make ops-parity`, part of `make check`)

`scripts/build_vectors.py` runs Python's osp-ops and writes vectors into `.build/`
(gitignored); `test/parity.test.ts` replays them and requires byte-identical JSON (in key
order) for every document, patch, inverse and diagnostic:

- every op on every fixture survey (3 generated params each, undo and redo of each
  success), the guard's EXAMPLES and 30 near misses per op, hostile surveys;
- every `run` / `invoke` / `apply_transaction` call the osp-ops test suite makes (the
  hand-written cases and the Hypothesis fuzzers, seeded);
- 400 seeded random sequences (15-45 steps: runs, transactions of 1-4 ops, stale
  revisions, invalid ops, undo and redo through the TS's own inverses);
- pydantic vectors for every params model and the models above; Python's `repr`, `strip`,
  `splitlines`, `Decimal` and float text.

The validator in the replay is an oracle: what Python's validator answered for each
document (keyed by the SHA-256 of its JSON). Asking about a document Python never
validated fails the test, so a TS op that builds a different document is caught even
before the hashes are compared. The vectors are rebuilt only when osp-ops, osp-spec,
osp-expr, their tests, the fixtures or the script change (`.build/stamp.txt`).

## What cannot match

- **`1` vs `1.0`.** JavaScript has one number type: an integral number is an `int`. Python
  rejects `1.0` where a strict `int` is required, keeps `2.0` in a theme's `lineSpacing`,
  and tells `1` from `1.0` in `same()`; the port cannot. The vectors write integral floats as
  ints, and keep other floats to plain notation (`2.5`, not `1e-07`).
- **Integer-like object keys** (`"1"`, `"42"`) come first in a JS object whatever their
  position, so patches and diagnostics over such keys can come out in another order. Ids,
  language tags, outcomes and custom keys cannot look like that; free-form maps
  (`metadata.ddi`, redirect param names) can.
- **Integers beyond 2^53** lose precision in JS.
- **Unexpected exceptions.** `op.internal` names the Python exception type; the port
  reproduces the ones the ops can raise on valid input (`AssertionError`, `KeyError`,
  `ValueError`, `UnicodeEncodeError`) and otherwise names the JS error.
- **Unicode corner cases.** Python's `Decimal` and JSON Patch indices read any Unicode
  digit; the port reads ASCII digits in decimals and Unicode decimal digits (`\p{Nd}`)
  in patch indices only. `repr()` printability, `lower()` and `\p{Nd}` follow Node's
  Unicode tables, which can differ from Python's by a Unicode version.
- **Inputs that are not JSON** (a pydantic `Survey`, sets, NaN, lone surrogates in a
  document) are out of scope: the builder only has JSON.

## Map

| Python (`osp_ops`) | TypeScript (`src/`) |
|---|---|
| `registry.py`, `schema.py` | `registry.ts`, `catalogue.ts` |
| `patch.py` | `patch.ts` |
| `transaction.py` | `transaction.ts` |
| `doc.py` | `doc.ts`, `loc.ts` |
| `question_ops.py` | `ops/question.ts` |
| `page_ops.py` | `ops/page.ts` |
| `property_ops.py` | `ops/property.ts` |
| `choice_ops.py`, `choice_list_ops.py` | `ops/choice.ts`, `ops/choiceList.ts` |
| `matrix_row_ops.py` | `ops/matrixRow.ts` |
| `condition_ops.py`, `flow_ops.py` | `ops/condition.ts`, `ops/flow.ts` |
| `consent_ops.py`, `ending_ops.py`, `redirect_ops.py`, `hooks_ops.py`, `theme_ops.py`, `survey_ops.py` | `ops/survey.ts` |
| `variable_ops.py`, `metadata_ops.py`, `custom_property_ops.py`, `duplicate_ops.py` | `ops/misc.ts` |
| `question_type_ops.py` | `ops/questionType.ts` |
| `bank_ops.py` | `ops/bank.ts` |
| pydantic, `osp_spec` / `osp_expr` models and helpers | `pyd.ts`, `models.ts`, `spec.ts`, `py.ts` |
