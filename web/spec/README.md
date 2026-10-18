# @osp/spec

The `osp-spec` validator in TypeScript (task CE4, `planning/client-edits.md` decision 5):
instant diagnostics in the builder and the serverless demo. The server's Python validator
stays authoritative on save; parity vectors keep the two equal.

```ts
import { validate, type Diagnostic } from '@osp/spec';

const diagnostics: Diagnostic[] = validate(doc); // [{severity, code, message, pointer}, ...]
```

`validate(doc)` takes any value (a parsed JSON document) and never throws. It returns what
`osp_spec.validate(doc)` returns: the same codes, severities, messages and RFC 6901 pointers,
in the same order. `parse(doc)` also returns the parsed survey (defaults filled, dicts as
`Map`) or `null`. `CODES` lists every code with its severity.

| File | Port of |
|---|---|
| `src/model.ts`, `src/schema.ts` | `model.py`, `hooks.py`/`theme.py` models, `osp_expr/ast.py`, and the pydantic-core behaviour they rely on (error types, messages, locations, order; smart and tagged unions; strict and lax scalars; aliases; `extra="forbid"`; validators) |
| `src/validate.ts` | `validate.py` (stage 1 error mapping, stage 2 checks) |
| `src/expr.ts` | `osp_spec/expr.py` and `osp_expr/static.py` (`references`, `code_tests`, `typecheck`) |
| `src/richtext.ts`, `src/hooks.ts`, `src/reserved.ts`, `src/diagnostics.ts` | the modules of the same name |
| `src/decimal.ts` | the `decimal` behaviour used (Python's `Decimal(str)` grammar, 28-digit context, `%`), `canonical_decimal` |
| `src/py.ts`, `src/pyregex.ts` | Python `len`/`strip`/`isspace`/`repr`/sorting, Unicode digits, and the `re` dialect of redirect param patterns |

`panel_profile.py` and `property_schema.py` are not used by the validator, so they are not ported.

## Parity

`make spec-test` (part of `make check`): `scripts/build_vectors.py` writes every fixture,
every validator test case, every input the osp-spec test suite passes to the validator
(`test/vectors/spec-test-inputs.json`, re-recorded by `make spec-harvest`), 5,000 seeded
mutations of the fixtures and valid cases, hand-picked edge cases (patterns, origins,
decimals, dates, reprs) and random JSON, with Python's diagnostics, into `.build/vectors.json`;
`test/parity.test.ts` asserts identical diagnostics for every document. A longer soak:
`OSP_SPEC_SEED=7 OSP_SPEC_MUTANTS=50000 make spec-test`.

## Differences

Messages are exact, including pydantic's. What cannot match:

- **Numbers.** A JavaScript number that is an integer is a Python `int`, anything else a
  `float`: JSON `1.0` is an int here (Python: a float, so `int_type` on an integer field), and
  integers that are not exactly a double, or of 1e21 and more, are not Python's. `NaN`/`Infinity` do not exist in JSON. The vectors
  leave such documents out.
- **Key order.** JavaScript objects list array-index keys (`"1"`, `"10"`) first, so
  diagnostics about such keys come in that order. The vectors are put in JavaScript order
  before Python validates them.
- **Redirect param patterns** are Python `re` patterns, translated to JavaScript
  (`src/pyregex.ts`). Not translated: `\N{name}` escapes and conditionals `(?(1)…)` (Python
  accepts them, here they are refused as a bad pattern), and Python's rule that a look-behind
  has a fixed width (`(?<=a+)` is refused by Python, accepted here). Case-insensitive
  matching uses JavaScript's case folding.
- **Values only JavaScript has** (`undefined`, functions, `Map`, `Date`, class instances,
  `BigInt`) are treated as values of the wrong type; a throwing getter, or a cycle the
  validator walks into, gives
  `internal.error` (Python's message names its exception, here `RecursionError` or
  `Exception`).
