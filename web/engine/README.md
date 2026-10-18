# @osp/engine

The participant engine (planning/runtime-design.md §3): pure TypeScript, no DOM, no I/O.
The runtime app, the builder preview, the debugger and the simulator all run it.

## Plan compile (`compilePlan`)

`src/compile.ts` is a port of `python/osp-runtime/src/osp_runtime/plan.py` (task CE3): it
turns an `osp-survey` document (raw JSON, as stored) into the runtime plan, with the same
canonical JSON and checksum as Python.

```ts
import { compilePlan, compileSurvey, runtimeConfig } from '@osp/engine';

const { plan, diagnostics } = compileSurvey(survey, { validate }); // never throws
const plan2 = compilePlan(survey, { validate, hooks }); // throws PlanError on errors
const config = runtimeConfig(plan2, { saveMode: 'end-only' });
```

- `validate` is the survey validator (`(data) => PlanDiagnostic[]`, the TS port of
  `osp_spec.parse`, task CE4). With it the TS refuses exactly what Python refuses, with
  Python's diagnostics. Without it the document is trusted. A document too broken to
  compile gives an `internal.error` diagnostic, never an exception.
- `hooks` replaces the survey's own hook manifest, as `compile_survey(..., hooks=...)` does.
  The manifest's shape check (`plan.hooks_invalid`) is left to the validator.
- Helpers, all byte-identical to Python: `segments`, `blocks`, `exprJson`, `pyDecimalText`,
  `consentVersion`, `seedVersion`, `seedNode`, `runtimeConfig`, `embedTheme`, `checksum`.
- Parity: `make engine-fixtures` runs `scripts/build_plan_vectors.py`, which writes every
  fixture, every osp-spec case, every other committed survey, hand-written edge cases and
  seeded mutations, with Python's plan, checksum and runtime config, to
  `.build/plan-vectors.json`. `test/compile-parity.test.ts` checks the TS matches.
- What JSON parsing loses (not the compiler) cannot match: an integer beyond 2^53 read by
  `JSON.parse`, and an integral float (`1.0`) in a hook manifest's number schema, which
  Python prints as `1.0` and JS as `1`.

Publish still compiles on the server (the authoritative checksum). The builder Preview does
not call `compilePlan` yet.
