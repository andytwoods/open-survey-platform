# Task queue

**The only place work is assigned** (`automation.md` §2). One agent per task, own worktree, branch `agent/<id>`.
Status: `todo → doing → review → done` (or `blocked`). Done = `make check` green + acceptance criteria met by named tests.
**Gate:** passed 16 Oct 2026 (Enketo spike go-with-limits; user approved building).

## Phase 1: scaffold (1 agent, sequential)

| id | title | layer | depends on | acceptance criteria | status | owner | needs human |
|---|---|---|---|---|---|---|---|
| S1 | Repo layout: `python/` uv workspace, `web/` pnpm workspace, `contract/`, `fixtures/`, `spikes/`, `log/` | — | gate | `uv sync` and `pnpm install` succeed from clean checkout | done | agent:scaffold | |
| S2 | Empty packages L0–L6 with READMEs; import-linter layers contract | all | S1 | `uv run lint-imports` passes; a deliberate upward import in a test branch fails | done | agent:scaffold | |
| S3 | Web skeleton: SvelteKit `adapter-static`, Bits UI, dependency-cruiser rules | L6 web | S1 | `pnpm -C web build` emits static files; boundary violation test fails as expected | done | agent:scaffold | |
| S4 | `make check` + CI (GitHub Actions): tests, layers, lint, licence check, contract staleness | — | S2, S3 | CI green on empty project; GPL test dependency makes CI fail | done | agent:scaffold | |
| S5 | Claude Code Stop hook running `make check`; `AGENTS.md` moved to root from `planning/AGENTS.draft.md` | — | S4 | Agent session can't finish with failing check | done | agent:scaffold | |
| S6 | Contract pipeline: FastAPI app → `contract/openapi.json` → generated TS client | L6 | S2, S3 | Changing an endpoint without regenerating fails CI | done | agent:scaffold | |

## Phase 2: core (re-planned 16 Oct 2026 so 4 agents start at once)

Scaffold decisions (16 Oct 2026): stay on SvelteKit 3; `certifi` allowed at runtime as a named exception; CC-BY-4.0, Zlib, BSL-1.0 added to the allowlist; Stop hook also gates `SubagentStop`.

### Wave A (parallel, after S6)

| id | title | layer | depends on | acceptance criteria | status | owner | needs human |
|---|---|---|---|---|---|---|---|
| C1 | `osp-expr`: condition AST, parser/printer for text syntax, evaluator per `semantics.md` §3. **First commit publishes `osp_expr/ast.py`** (the AST types) so C2 can build on it | L0 | S6 | Property tests: print∘parse = id; null semantics fixtures pass | done | agent:C1 | |
| C2 | `osp-spec`: survey model (pydantic), JSON Schema export, semantic validator, `specVersion`. Condition fields typed against C1's AST; use an opaque stand-in until `ast.py` lands | L1 | S6 (C1 `ast.py`) | 30 fixture surveys pass/fail as expected with JSON-pointer diagnostics | done | agent:C2 | |
| E1 | Enketo bundle: build enketo-core + transformer from a pinned enketo/enketo commit into `web/enketo-runtime`; headless-WebKit transform script; patch a11y bugs (`role="page"`, `tabindex` > 0) | L4 web | S6 | Build is reproducible from the pinned commit; transforms the spike XForm; axe reports no role/tabindex violations; licence gate green | dropped | agent:E1 | own runtime chosen 16 Oct 2026 (`runtime-design.md`); branch `agent/E1` kept |
| C3a | Fixtures v0: 20 surveys + answer scripts + expected traces, drafted from `review.md` §2.3 and the spike surveys | fixtures | S6 | 20 fixtures; features covered listed in `fixtures/README.md`; schema validation deferred to C3b | done | agent:C3a | |

### Wave A2 (parallel, added 16 Oct 2026 when the user doubled agents to 8)

| id | title | layer | depends on | acceptance criteria | status | owner | needs human |
|---|---|---|---|---|---|---|---|
| C4a | `osp-engine` randomness: ODK `randomize` port (inside-out Fisher–Yates + Park–Miller), per-node stream derivation `hash(surveyVersion, sessionSeed, nodeId)`, integer-seed rules (semantics §7) | L2 | S6 | 1,000-seed parity with `spikes/spike-enketo/evidence/e5_randomize_all.json`; stream independence property tests | done | agent:C4a | |
| C9 | `osp-store`: model-agnostic (survey JSON stored opaque); tenants, users, drafts, immutable versions + checksum, responses; Postgres + SQLite; encryption at rest; retention job | L4 | S6 | Same tests on SQLite and Postgres; tenant isolation tests; retention deletes and is tested | done | agent:C9 | |
| C10a | `osp-app` auth: password hashing, TOTP, sessions, roles/permissions policy, against a repository Protocol with an in-memory implementation (wired to C9 later) | L5 | S6 | Fail-closed permission matrix tests; TOTP and lockout tests | done | agent:C10a | |
| W1 | Builder shell + `ui-components`: design tokens (light/dark), three-pane layout (outline / canvas / properties), command palette + shortcut infra, mock data only, no survey logic | L6 web | S3 | Playwright: layout + keyboard navigation; axe clean; visual snapshot | done | agent:W1 | |

### Wave B (as Wave A lands)

| id | title | layer | depends on | acceptance criteria | status | owner | needs human |
|---|---|---|---|---|---|---|---|
| C3b | Fixtures validate against `osp-spec`; fix drift | fixtures | C2, C3a | Every fixture validates | doing | agent:C3b | |
| C4 | `osp-engine`: flow state machine + trace; seeded PRNG; ODK `randomize` reimplementation | L2 | C2, C3b | All fixtures produce expected traces; 1,000-seed `randomize` parity with spike evidence | todo | | |
| C5 | `osp-ops`: registry, `(survey, args) → (survey', inverse)`, transactions, fuzz harness | L2 | C2 | Every op has inverse test + hostile-input fuzz test | doing | agent:C5 | |
| C6 | `osp-targets/xlsform` + capability table | L3 | C2 | Fixtures export; `pyxform` validates all; diagnostics for unsupported features | doing | agent:C6 | |
| C9 | `osp-store`: Postgres + SQLite; drafts, versions, responses; encryption at rest; retention job | L4 | C2 | Tenant isolation tests; retention deletes and is tested | done | | |

### Wave B2 (started 16 Oct 2026; independent of the runtime decision)

| id | title | layer | depends on | acceptance criteria | status | owner | needs human |
|---|---|---|---|---|---|---|---|
| B1 | Property schema format + 7 MVP types (`builder-design.md` §1) in `osp-spec`, exported via OpenAPI | L1 | C2 | Schema validates; every model field of every type has a property entry; completeness test | doing | agent:B1 | |
| W1b | Fix flaky `toBeFocused` e2e test in builder shell | web | W1 | `make web-e2e` green 10 runs in a row | doing | agent:W1b | |

### Wave C (runtime tasks R1–R8 replace C4/C7/C8 once `runtime-design.md` is approved)

| id | title | layer | depends on | acceptance criteria | status | owner | needs human |
|---|---|---|---|---|---|---|---|
| C7 | `osp-runtime`: publish → XForm → Enketo page; session start injects `cond` + `seed`; submission endpoint | L4 | C6, E1 | Participant completes a fixture survey in Playwright; submission stored and linked to version | todo | | |
| C8 | Harness: Playwright plays fixture scripts through Enketo pages; compares with engine traces | qa | C4, C7 | `make harness-quick` green on all fixtures in under 5 min | todo | | |
| C10 | `osp-app` + API: auth (password + TOTP), roles, draft CRUD via ops, publish, export | L5–L6 | C5, C9 | Other-user access tests fail closed; OpenAPI regenerated | todo | | |

## Phase 3: builder (see `builder-design.md` §9; 3–5 agents)

| id | title | depends on | status |
|---|---|---|---|
| B1 | Property schema format + 6 MVP types | C2 | todo |
| B2 | Op client + store + patch applier + undo/redo | C10 | todo |
| B3 | Shell + outline tree (drag + keyboard) | B2 | todo |
| B4 | Property panel + basic field editors | B1, B2 | todo |
| B5 | Question cards (6 families) | B1 | todo |
| B6 | Choice list editor | B4 | todo |
| B7 | Condition builder | B4, C1 | todo |
| B8 | Flow editor | B3, B7 | todo |
| B9 | JSON view with Apply | B2 | todo |
| B10 | Diagnostics strip + export badges | B1, C6 | todo |
| B11 | Enketo preview + debugger panel | C4, C7 | todo |

Acceptance criteria for B1–B11: `builder-design.md` §9.

## Phase 4: MVP completion

| id | title | depends on | status |
|---|---|---|---|
| M1 | Simulator + sampled path coverage report (`osp-qa`) | C4 | todo |
| M2 | CSV/JSON export with state columns + codebook | C9 | todo |
| M3 | Reproducibility package | M2, C6 | todo |
| M4 | LSS exporter (uses spike 1 lessons: reserved names, `{q.shown}`, latched assignment) | C2 | todo |
| M5 | Consent-before-collection, deletion, no-IP default (MVP item 12b) | C7, C9 | todo |
| M6 | Pilot survey built end to end in the builder by the user | all | todo |
