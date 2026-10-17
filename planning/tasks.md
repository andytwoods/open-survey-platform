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
| C3b | Fixtures validate against `osp-spec`; fix drift | fixtures | C2, C3a | Every fixture validates | done | agent:C3b | |
| C4 | `osp-engine`: flow state machine + trace; seeded PRNG; ODK `randomize` reimplementation | L2 | C2, C3b | All fixtures produce expected traces; 1,000-seed `randomize` parity with spike evidence | replaced | | by R1/R3/R4 (own runtime) |
| C5 | `osp-ops`: registry, `(survey, args) → (survey', inverse)`, transactions, fuzz harness | L2 | C2 | Every op has inverse test + hostile-input fuzz test | done | agent:C5 | |
| C6 | `osp-targets/xlsform` + capability table | L3 | C2 | Fixtures export; `pyxform` validates all; diagnostics for unsupported features | done | agent:C6 | |
| C9 | `osp-store`: Postgres + SQLite; drafts, versions, responses; encryption at rest; retention job | L4 | C2 | Tenant isolation tests; retention deletes and is tested | done | | |

### Wave B2 (started 16 Oct 2026; independent of the runtime decision)

| id | title | layer | depends on | acceptance criteria | status | owner | needs human |
|---|---|---|---|---|---|---|---|
| B1 | Property schema format + 7 MVP types (`builder-design.md` §1) in `osp-spec`, exported via OpenAPI | L1 | C2 | Schema validates; every model field of every type has a property entry; completeness test | done | agent:B1 | |
| W1b | Fix flaky `toBeFocused` e2e test in builder shell | web | W1 | `make web-e2e` green 10 runs in a row | done | agent:W1b | |

### Runtime (approved 16 Oct 2026, `runtime-design.md` §9; replaces C4, C7, C8)

| id | title | layer | depends on | acceptance criteria | status | owner | needs human |
|---|---|---|---|---|---|---|---|
| R1 | TS engine `web/engine`: plan types (first commit), state machine, effects, event log, exact decimals, randomize/node_seed port, fixture runner | web L2 | C3b | All non-pending fixtures pass; 10k-seed + hash-vector parity with Python | done | agent:R1 | |
| R2 | `osp-runtime`: plan compiler (after R1 plan types) + session API: start, revisioned snapshot save (409), idempotent quota + submit, save modes, resume tokens | L4 | C9, R1 types | API tests: stale write 409, idempotent retries, end-only stores no answers before submit | done | agent:R2 | |
| R3 | Participant app `web/runtime`: local-first save, lifecycle flush, resume reconciliation, focus/nav rules | web | R1 | Playwright: refresh at every step, tab kill, offline → online, zero lost answers | done | agent:R3 | |
| R4 | Harness: fixture scripts through `web/runtime` on device profiles + interruption tests | qa | R3 | `make harness-quick` < 5 min | done | | |
| R5 | Pilot widgets × responsive/a11y rules (§6) | web | R1 | axe + snapshots per widget × width; keyboard tests | done | | |
| R6 | Adversarial fixtures (§4) | fixtures | C3b | ≥ 15 new fixtures; listed in `fixtures/README.md` | done | | |
| R7 | Researcher hooks: sandbox, events, actions, effects, adversarial gate (§7a) | web | R1, R3 | Adversarial test suite green | done | agent:R7 | |
| R8 | Themes: theme model + tokens, contrast guard, runtime application, theme library storage (§6a); editor UI later | L1 + web | — | Contrast guard tests; all presets AA; tokens applied in runtime | done | agent:R8 | |

### Wave D (started 16 Oct 2026)

| id | title | depends on | status |
|---|---|---|---|
| R8b | Appearance (theme editor) view | R8 | done |
| C2b | Spec/expr gaps: page titles, booleans, Condition, choice codes | C2 | done |
| R2b | Publish compiles the runtime plan + serves it; fix fixture 28 invariant | R1, R2, C10 | done |
| B2 | Builder op client + store + patch applier + undo/redo against the real API | C10 | done |
| B5 | Question cards (families) on the canvas, from property schemas | B1, R5 | done |
| M2 | CSV/JSON export with `__state` columns + codebook | R1, R2 | done |

### Wave C (remaining)

| id | title | layer | depends on | acceptance criteria | status | owner | needs human |
|---|---|---|---|---|---|---|---|
| C7 | `osp-runtime`: publish → XForm → Enketo page; session start injects `cond` + `seed`; submission endpoint | L4 | C6, E1 | Participant completes a fixture survey in Playwright; submission stored and linked to version | replaced | | by R1/R3/R4 (own runtime) |
| C8 | Harness: Playwright plays fixture scripts through Enketo pages; compares with engine traces | qa | C4, C7 | `make harness-quick` green on all fixtures in under 5 min | replaced | | by R1/R3/R4 (own runtime) |
| C10 | `osp-app` + API: auth (password + TOTP), roles, draft CRUD via ops, publish, export | L5–L6 | C5, C9 | Other-user access tests fail closed; OpenAPI regenerated | done | | |

## Phase 3: builder (see `builder-design.md` §9; 3–5 agents)

| id | title | depends on | status |
|---|---|---|---|
| B1 | Property schema format + 6 MVP types | C2 | done |
| B2 | Op client + store + patch applier + undo/redo | C10 | done |
| B3 | Shell + outline tree (drag + keyboard) | B2 | done |
| B4 | Property panel + basic field editors | B1, B2 | done |
| B5 | Question cards (6 families) | B1 | done |
| B6 | Choice list editor | B4 | done |
| B7 | Condition builder | B4, C1 | done |
| B8 | Flow editor | B3, B7 | done |
| B9 | JSON view with Apply | B2 | done |
| B10 | Diagnostics strip + export badges | B1, C6 | done |
| B11 | Enketo preview + debugger panel | C4, C7 | done |

Acceptance criteria for B1–B11: `builder-design.md` §9. B11 shipped as the own-runtime preview + debugger (Enketo dropped).

## Phase 4: MVP completion

| id | title | depends on | status |
|---|---|---|---|
| M1 | Simulator + sampled path coverage report (`osp-qa`) | C4 | done |
| M2 | CSV/JSON export with state columns + codebook | C9 | done |
| M3 | Reproducibility package | M2, C6 | done |
| M4 | LSS exporter (uses spike 1 lessons: reserved names, `{q.shown}`, latched assignment) | C2 | done |
| M5 | Consent-before-collection, deletion, no-IP default (MVP item 12b) | C7, C9 | done |
| M6 | Pilot survey built end to end in the builder by the user | all | todo (needs human: Andy) |

## Wave E (17 Oct 2026): separate pages, host-owned sign-in, builder gaps

Plan P: `planning/pages-split.md`. From here, tasks are also posted to the HubAI board; workers push
branch `agent/<id>` to GitHub (`origin`) with `make check` exit code and test counts in the task note.

| id | title | depends on | acceptance criteria | status |
|---|---|---|---|---|
| P1 | Host-owned identity in osp-api (signed headers, in-process, dev); our accounts removed; migration 0007 | — | pages-split §B1–B2, D2–D6, D12 | done |
| P2 | Builder as separate Vite pages, host config, no sign-in UI | — | pages-split §F1–F3, D1, D7–D10 | done |
| P4 | `docs/hosting.md` + tested proxy example | P1, P2 | doc fields match code; `test_hosting_example.py` | done |
| P5 | Trusted proxies, public origins, participant API prefix, shared nonce store (0008) | P4 | pages-split D13–D16 | done |
| H1 | Harness runs isolated per run (shared-folder flake) | — | 12 consecutive green incl. parallel | done |
| B13 | Question type picker + `change_question_type` | — | all 9 types addable; change type with undo, conflict check | done |
| B14 | Canvas shows real per-type question cards | B13 | matrix shows rows × columns; live update | done |
| R9 | Refresh straight after typing loses an answer when storage is blocked (fixture 30 `storage-blocked` fails ~1 in 20): two keepalive saves can reach the server out of order | — | Root cause confirmed from traces; fix in either arrival order without weakening two-device conflict detection (fixture 25 unchanged); decision recorded in `semantics.md` saving section + `runtime-design.md`; unit tests both sides for both orders + edit-not-append; ≥ 200 repeats of fixture 30 green incl. under parallel load; `make harness-full` green | done |
| B15 | Grid (matrix) rows editor in the properties panel | B14 | Add, rename (incl. translations), reorder (drag + keyboard), delete rows; ops with undo; row ids stable; deleting a row referenced by conditions warns like `delete_question` force; card updates live; e2e incl. 320 px, axe | done |
| B16 | Question-type toolbox in the outline pane (click or drag a type onto a page) | B13 | Click adds to the selected/last page; drag onto a page or between questions inserts there; keyboard alternative; same picker catalogue; e2e + axe | done |
| B17 | Top-bar targets at 320 px are 20 px (axe flags them under dialog overlays) | — | All top-bar targets ≥ 44 px at 320/375 px (overflow menu if needed); axe clean with any dialog open at 320 px; no horizontal scroll | done |
| B18 | Canvas cards show validator error/warning counts | B14 | Cards receive diagnostics per question; counts and click-to-property; e2e | todo |
| R10 | Researcher hooks run in the builder Preview | R7 | Preview frame runs hooks in the same sandbox as the participant app; hook errors visible in the debugger; CSP for preview documented; e2e | review |

## Wave F (17 Oct 2026): results viewer with exportable charts

Plan V: `planning/results-viewer.md` (decisions V-D1–V-D10). V1 publishes the contract first.

| id | title | depends on | acceptance criteria | status |
|---|---|---|---|---|
| V1 | Results aggregation API | — | First commit: request/response schema in `contract/openapi.json` (`make contract`). `osp-app` results module implementing every V-D5 rule; `POST /api/surveys/{id}/results/query`, paginated text endpoint; survey.export only; audit `results.read`; in-memory cache invalidated by new responses; tests with hand-computed expectations for each question type, multi-choice denominators, response states, versions (incl. not-in-version), splits, filters, matrix rows, languages; cross-tenant 403/404; benchmark 10 k responses < 2 s and 100 k < 15 s recorded in devlog | done |
| V2 | Results page (builder page entry `results`) | V1 contract | New page in the Vite multi-page build + manifest + dev host URL `/surveys/{id}/results` + link from the top bar; filter bar, split, denominator toggle, card per question with state counts, statistics and Table view, chart menu per type (wired to V3 component; placeholder until V3 lands); lazy-loaded; 320 px, keyboard, axe light/dark; vitest + e2e against the real API in `make web-e2e` | todo |
| V3 | Charts (Vega-Lite) | V1 contract | `vega`/`vega-lite`/`vega-embed` pass `make licence-check`; one Svelte chart component; spec builders for every chart in the plan's menu table, incl. diverging Likert and split variants; app theme from tokens (light/dark) and export theme (Okabe-Ito, white); SVG renderer with titles/ARIA; unit tests on specs; visual snapshots | todo |
| V4 | Figure export | V3 | Per card: SVG, PNG (85/180 mm/custom, 150/300/600 DPI, real pixels + DPI metadata), aggregate CSV, Vega-Lite spec + manifest; page ZIP; editable auto captions (V-D8); "hide counts below k" option with warning; final-size preview; audit `results.export`; e2e downloads checked (dimensions, files in ZIP, caption text) | todo |
| V5 | Saved results layouts | V1, V2 | Migration 0009 (SQLite + Postgres); CRUD API (owner/editor, lab-shared); default layout; page loads/saves layouts; tests incl. tenant isolation | todo |
| V6 | PDF figure + PDF/HTML report (phase 2) | V4 | Permissive libraries only; fonts/clipping checked; report from one frozen query | todo |
| V7 | Combine compatible versions, numeric split bins, text word frequency (phase 2) | V1–V3 | Per V-D5; word frequency with stop words and PII redaction | todo |

## Wave G (17 Oct 2026): polish

| id | title | depends on | acceptance criteria | status |
|---|---|---|---|---|
| G1 | Favicon, app icons and page metadata for the builder, participant app and docs | — | One source SVG mark (original, no third-party logos) → favicon.svg + PNG 32/180/192/512 + `apple-touch-icon` + web manifest (name, theme colour, icons) for builder pages and the participant app; light/dark-safe; participant app icon overridable by the survey theme/host (documented in `docs/hosting.md`); social preview image (1280×640) for the GitHub repo; `<title>`/`description` per builder page; no new runtime deps beyond permissive; e2e asserts icons and manifest load (no 404s) | todo |

