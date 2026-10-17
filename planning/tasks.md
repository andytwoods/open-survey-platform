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
| B18 | Canvas cards show validator error/warning counts | B14 | Cards receive diagnostics per question; counts and click-to-property; e2e | done |
| R10 | Researcher hooks run in the builder Preview | R7 | Preview frame runs hooks in the same sandbox as the participant app; hook errors visible in the debugger; CSP for preview documented; e2e | done |

## Wave F (17 Oct 2026): results viewer with exportable charts

Plan V: `planning/results-viewer.md` (decisions V-D1–V-D10). V1 publishes the contract first.

| id | title | depends on | acceptance criteria | status |
|---|---|---|---|---|
| V1 | Results aggregation API | — | First commit: request/response schema in `contract/openapi.json` (`make contract`). `osp-app` results module implementing every V-D5 rule; `POST /api/surveys/{id}/results/query`, paginated text endpoint; survey.export only; audit `results.read`; in-memory cache invalidated by new responses; tests with hand-computed expectations for each question type, multi-choice denominators, response states, versions (incl. not-in-version), splits, filters, matrix rows, languages; cross-tenant 403/404; benchmark 10 k responses < 2 s and 100 k < 15 s recorded in devlog | done |
| V2 | Results page (builder page entry `results`) | V1 contract | New page in the Vite multi-page build + manifest + dev host URL `/surveys/{id}/results` + link from the top bar; filter bar, split, denominator toggle, card per question with state counts, statistics and Table view, chart menu per type (wired to V3 component; placeholder until V3 lands); lazy-loaded; 320 px, keyboard, axe light/dark; vitest + e2e against the real API in `make web-e2e` | done |
| V3 | Charts (Vega-Lite) | V1 contract | `vega`/`vega-lite`/`vega-embed` pass `make licence-check`; one Svelte chart component; spec builders for every chart in the plan's menu table, incl. diverging Likert and split variants; app theme from tokens (light/dark) and export theme (Okabe-Ito, white); SVG renderer with titles/ARIA; unit tests on specs; visual snapshots | done |
| V4 | Figure export | V3 | Per card: SVG, PNG (85/180 mm/custom, 150/300/600 DPI, real pixels + DPI metadata), aggregate CSV, Vega-Lite spec + manifest; page ZIP; editable auto captions (V-D8); "hide counts below k" option with warning; final-size preview; audit `results.export`; e2e downloads checked (dimensions, files in ZIP, caption text) | done |
| V5 | Saved results layouts | V1, V2 | Migration 0009 (SQLite + Postgres); CRUD API (owner/editor, lab-shared); default layout; page loads/saves layouts; tests incl. tenant isolation | todo |
| V6 | PDF figure + PDF/HTML report (phase 2) | V4 | Permissive libraries only; fonts/clipping checked; report from one frozen query | done |
| V7 | Combine compatible versions, numeric split bins, text word frequency (phase 2) | V1–V3 | Per V-D5; word frequency with stop words and PII redaction | todo |

## Wave G (17 Oct 2026): polish

| id | title | depends on | acceptance criteria | status |
|---|---|---|---|---|
| F1 | Builder lost typed consent text (whole-value `set_consent` built from a stale survey while an op was in flight) | — | Proven from op patches; DOM test fails before the fix; publish spec 30/30 | done |
| F2 | `LanguagesField` has the same whole-value pattern: two quick add/remove clicks can drop the first | F1 | Build on the last-sent value while an op is in flight (as F1's ConsentEditor), keep the reject/cascade flow; DOM test that fails before the fix; e2e quick double add/remove | done |
| G1 | Favicon, app icons and page metadata for the builder, participant app and docs | — | One source SVG mark (original, no third-party logos) → favicon.svg + PNG 32/180/192/512 + `apple-touch-icon` + web manifest (name, theme colour, icons) for builder pages and the participant app; light/dark-safe; participant app icon overridable by the survey theme/host (documented in `docs/hosting.md`); social preview image (1280×640) for the GitHub repo; `<title>`/`description` per builder page; no new runtime deps beyond permissive; e2e asserts icons and manifest load (no 404s) | done |
| CI1 | GitHub Actions CI on the public repo | — | Workflow on push + PR: `make install` + `make check` on ubuntu (cache uv + pnpm + Playwright browsers); `make web-e2e` and `make harness-quick` as separate jobs; Windows job running `make check` minus browser suites; badge in README; runs green on main; under 20 min wall clock; no secrets needed | done |
| W2 | Builder e2e on native Windows and Linux (CI) | CI1 | The 22 builder e2e failures seen on Windows (card/preview/widget snapshots, shell palette) fixed: per-platform snapshots or font pinning for visual tests, platform-safe keyboard shortcuts in tests; `make web-e2e` green on Windows locally and in the CI Windows job | done |
| V5a | Saved results layouts: backend | V1 | Migration 0009 (SQLite + Postgres); layout model (name, default flag, settings JSON validated by a schema: chart choice per question, filters, split, denominator, order, hidden, bins, captions — never data); CRUD under `/api/surveys/{id}/results/layouts` (owner/editor; lab-shared; viewer read-only later), audit, tenant-isolation tests, `make contract` | done |
| D2 | Docs site for Open Survey Platform | — | MkDocs Material site from `docs/` (getting started, building a survey, question types, logic, publishing, results, hosting, API reference from OpenAPI), deployed by GitHub Pages workflow; screenshots generated by a Playwright script against `make dev`; `mkdocs build --strict` in CI | done |
| DM1 | Scripted demo videos of the tools in use | — | Re-runnable Playwright scripts (`make demo-videos`, not part of `make check`) against a fresh `make dev`-style stack with an invented demo survey (no real personal data); slowed down, visible cursor/click highlight and short on-screen captions; videos: (1) build a survey: add questions of several types, choices, a grid, a display condition, flow/randomiser; (2) appearance + settings + consent + publish; (3) a participant answering on phone and desktop sizes, incl. refresh and resume; (4) results viewer + figure export (once V2–V4 land); (5) researcher host sign-in flow optional; MP4 (H.264) 1080p + a short GIF per video, chapters/timestamps listed in `docs/demos.md`; output in `.build/demo/` (gitignored); total < 6 min | done |
| DS1 | Fake responses for local dev | — | `osp-cli fake-responses <survey id or slug> --n --seed --partial --days` (refused unless `OSP_ENV=dev`): sessions started by the participant SessionService, played through the real engine (`web/engine-sim` `dist/fake.js`), saved/quota-checked/submitted through the same service calls; realistic shapes per question type; deterministic by seed; drop-outs not submitted; `dev-seed` fills each seeded survey on first run (150, `DEV_FAKE_RESPONSES`); `make dev-fake N=200`; pytest: validation + replay, results states sum to N, partials not-reached after their stop, determinism, refusal | done |
| R11 | Researcher hooks can be authored, stored and published | R10 | Survey-level `hooks` in `osp-spec` (the manifest shape in `web/hooks-sandbox/src/manifest.ts`: code + event handlers + params, size-capped), JSON Schema + validator; op `set_hooks` (inverse, fuzz; audited as code change; owner/editor only); publish passes it to `compile_plan(hooks=…)` so it is inside the checksum; builder: a Hooks editor (CodeMirror, as the condition text view) under Settings or its own view, with the sandbox's event list, `ctx` reference and errors from a dry run; preview uses the draft's hooks (R10); exports (XLSForm, LSS) emit a "hooks not exported" diagnostic; tests across spec/ops/publish/builder e2e (a hook that sets a value on `pageEnter` works in preview and in a published run) | done |
| W3 | Python tests on native Windows | CI1 | The 26 Windows-only py-test failures CI1 found pass: node sidecar started with `SYSTEMROOT` in its env, POSIX 0600 permission checks skipped or adapted on Windows for dev-keys/dev-seed, bash-only stop-hook tests skipped on Windows; remove `py-test` from the Windows job's `CHECK_SKIP` | done |
| H2 | Hosting friction found while writing the tutorial's deploy chapter | — | (a) `OSP_DATABASE_URL` accepts `postgres://` / `postgresql://` (maps to pg8000) with tests; (b) an official `Dockerfile` for `osp-api` (+ built builder pages and participant app), non-root, pinned base, documented in `docs/hosting.md`; (c) the host signing helper published as a tiny standalone package (`osp-host-signing`, stdlib only, MIT) so hosts `pip install` instead of copying `signing.py`; (d) participant app sends no snapshot PUT after a successful submit (today: 409 SessionSubmitted); (e) builder preview iframe stops combining `allow-scripts` with `allow-same-origin` (or documents why it must, with the CSP that contains it) | done |
| V5b | Results page uses saved layouts | V5a, V4 | Results page loads the default layout on open; "Save layout" / "Save as…" / rename / delete / set default (owner/editor); a layout holds the filter bar state, split, denominator, intervals, per-card chart + split layout + hidden + bins + caption, order (drag + keyboard reorder of cards), and V4's export settings; unknown/unsuitable chart ids fall back with a notice; unsaved-changes indicator; e2e: save, reload, layout restored, switch layouts, delete; 320 px + axe | done |
| B19 | Drag a question type (or an existing card) onto the canvas, exactly where it should go | B16 | Drag from the toolbox onto the canvas: a clear insertion line between cards (and on empty pages) shows where it lands; drop inserts that type at that page + index (`add_question` with index) and selects it; dragging an existing card on the canvas reorders it (same move op as the outline); auto-scroll near edges; Escape cancels; works with mouse and touch (pointer events); keyboard alternative stays (B16's Shift+Enter "choose where"); screen-reader announcements; e2e: drag each way, drop between cards 1 and 2, onto an empty page, cancel; 320 px falls back to tap-to-place | done |
| B20 | Add, rename, duplicate and delete pages and blocks in the builder | — | The `add_page` / `add_block` ops (and existing rename/delete/move ops) get UI: "Add page" under each page's last card and in the outline, "Add block" in the outline and Flow view, page/block context menus (rename, duplicate, delete with the reference warning like questions), palette commands; new items selected and focused; undo; e2e incl. keyboard and 320 px; axe | done |
| B21 | Customisable property panel (labs choose which properties researchers see, add their own) | B4 | Clean-room, idea only. A lab-level "property panel profile" stored server-side (migration, CRUD, owner only): hide properties, reorder, rename group headings, set defaults for new questions, and define custom properties (text / number / boolean / choice, per question type) stored under a reserved `custom` object on questions, validated by the property schema, included in exports (codebook column) and the JSON; builder applies the profile; a profile editor page; tests across spec/ops/API/builder; docs | done |
| V6 | Results presentation: own theme, hide all UI, export all as SVG or PNG | V4, V5b | Results page theme chosen independently of the survey (theme library + "use the survey's theme" option; contrast-checked) applied to charts in the app and in exports; a "presentation mode" that hides all builder/filters UI and shows only the cards (Escape or a small floating button to exit; URL flag so it can be shared/printed); "Export all" offers SVG-only ZIP, PNG-only ZIP (with the size/DPI settings) or the full bundle; saved in the layout (V5b); e2e + axe | done |
| UI1 | Purple colour scheme for the builder (replace the blue) | — | Owner dislikes the current blue. New accent/primary scale in purple (match the new 8-bit icon's indigo/violet) in `web/ui-components/src/tokens.css` for light and dark; every text/background pair still WCAG AA (existing contrast tests); focus rings visible; charts' app theme follows; social-preview bar colour; update visual snapshots for all three platforms (darwin locally, linux/win32 via the snapshots workflow per web/builder/README.md); before/after screenshots in the task note | done |
| QB1 | Question bank: plan + licence audit of common psychology instruments | — | Write `planning/question-bank.md`: features (save any question/block to a lab bank, search/tag, insert into a survey keeping provenance, versioning, sharing between labs) and a curated library of validated instruments **only where the licence allows redistribution** (e.g. IPIP items: public domain; check each: PHQ-9, GAD-7, PSS, Rosenberg, TIPI, SUS, PANAS, BFI-2, WEMWBS…), with source, citation, licence, scoring notes, translations available; list instruments that must NOT be bundled (proprietary e.g. BDI-II) and how researchers can add their own licensed copy privately; review the plan with GPT/Gemini/Qwen before posting it to the board | todo |

## Wave H (17 Oct 2026): growth features, queued for the HubAI workers

| id | title | depends on | acceptance criteria | status |
|---|---|---|---|---|
| EX1 | End-of-survey options: explore and plan (done; `planning/end-of-survey.md`) | — | Research only (clean-room: public docs of SurveyJS, Qualtrics, LimeSurvey; never their code): what each offers at the end (completion message, per-branch end messages, redirect with/without delay, URL with piped values, show/hide a summary, screen-outs, quota-full endings, "close survey" behaviour). Write `planning/end-of-survey.md`: what we have today, gaps, recommended set with semantics (piping, encoding, security of redirect targets, delay accessibility), then follow-up build tasks | review |
| IM1 | Import surveys from Qualtrics (.qsf), LimeSurvey (.lss) and SurveyJS JSON | — | Clean-room parsers from the public formats; map question types, choices, display logic, blocks, randomisation, languages where possible; every unsupported feature reported as a diagnostic, never silently dropped; import creates a draft; round-trip tests from invented sample files (no real surveys or personal data); builder "Import…" dialog with a preview of what will and won't carry over | done |
| EX2 | External task step + Prolific integration | R11, EN1, EN2 | A flow node that sends the participant to an external URL (PsychoJS/jsPsych/Gorilla) with signed, expiring return token and piped values, and resumes the survey on return (storing returned values as variables); Prolific: capture PROLIFIC_PID/STUDY_ID/SESSION_ID, completion codes per ending (incl. screen-out), docs; security tests (token tamper/replay/expiry) | todo |
| AI1 | AI survey drafting via the MCP server | — | `osp-mcp` tools cover drafting (create survey, add pages/blocks/questions/choices/conditions by op id, validate, preview link); a docs page with a worked example ("describe your study → draft"), guardrails (draft only, never publish; ops validated; no participant data exposed); tests with a scripted MCP client | done |
| OS1 | Preregistration export (OSF-ready) | — | Export bundle: survey spec + version checksum, codebook, randomisation/assignment description, planned exclusions from settings, reproducibility package, a human-readable PDF/HTML summary; optional OSF upload via user-supplied token (never stored); docs; tests | done |
| DEMO1 | Public demo instance | live server (owner) | Deploy the official image (deploy/Dockerfile) on the owner's server with Dokku, seeded with invented demo surveys + fake responses, reset nightly, banner "demo, data deleted daily", signed-in as a demo researcher via a tiny host; documented runbook | todo |
| XP1 | Exporters to Qualtrics (.qsf) and SurveyJS JSON (to match IM1's importers) | — | Today we export XLSForm and LimeSurvey (.lss). Add QSF and SurveyJS JSON targets in `osp-targets` with capability tables like `xlsform`/`lss` (every feature mapped or reported as a `loss` diagnostic, completeness guard covers both), golden files from the fixtures, round-trip tests through IM1's importers where they exist (export → import → same survey modulo reported losses), validation against each format's public schema/structure (clean-room: public docs only), builder Publish dialog download buttons + export badges per target; `make check` + web-e2e | todo |
| MD1 | Participant app on real mobile browsers (emulators + device cloud) | — | Runs on a worker PC, not the lead Mac. Extend `web/harness` (the fixture harness that plays all 40 fixtures through the participant app) to: (1) **Android Emulator** (Android SDK, a Pixel API 34+ image, Chrome) driven by Playwright's Android support or Appium + chromedriver, running `harness-quick`'s fixtures in real Chrome for Android; (2) optionally **iOS Simulator** Safari if a Mac worker exists (else skip and say so); (3) a **device-cloud** job (BrowserStack/Sauce Labs/LambdaTest have free open-source plans; credentials come from a GitHub secret the owner adds, never committed) running a nightly matrix of real iPhone/Android devices; (4) checks beyond the fixtures: orientation change mid-page, soft keyboard covering inputs (focused field stays visible), backgrounding the tab during save then resuming, slow 3G + offline toggling, large text / zoom 200%, VoiceOver/TalkBack labels via axe on device; report table per device; docs `docs/device-testing.md`; nothing added to `make check` (separate `make harness-devices`) | todo |
| LV1 | Live results: explore and plan (done; `planning/live-results.md`) | V1, V4 | Research + plan only: `planning/live-results.md`. Goal: the Results page (and presentation mode, V6) updates as responses arrive. Compare (a) polling V1's cheap `watermark` and re-querying only when it changes, (b) Server-Sent Events from osp-api (new "responses changed" stream per survey, through the host proxy — check signed-identity + proxies + timeouts in `docs/hosting.md`), (c) WebSockets, (d) **htmx** (owner suggested it: server-rendered fragments with `hx-trigger="every 5s"` / SSE extension — evaluate honestly against our architecture: builder pages are static Svelte bundles mounted by a host, results are computed as JSON + Vega specs client-side, CSP `script-src 'self'`, and the host owns HTML; say where htmx would or wouldn't fit). Cover: cost of recomputing aggregates (V1 benchmark: 10 k = 0.4 s, cache by watermark), incremental aggregation option, rate limiting/debounce, many viewers, audit log volume (`results.read` per refresh?), privacy (live small-n leaks during collection), UX (a "live" toggle, "N new responses" badge, animation off for reduced motion), presentation mode on a lab screen. Recommend one approach with phases and effort; propose build tasks (branch agent/34: `planning/live-results.md`, decisions LV-D1–D8, build tasks LV2–LV6 proposed, 4 open questions for the owner) | done |
| F3 | Flaky: structure.spec "keyboard only: context menu … duplicates" sometimes gets an extra page | B20 | Seen once on the Mac (expected [p1, p2, p2_copy…], received one more item): likely a double-activated menu item or a duplicate op sent twice; find the cause, fix in app or test (no retries), 30 repeats green | todo |
| EN1 | Endings per outcome: spec, engine view, participant screen | EX1 | See `planning/end-of-survey.md` §6 EN1 | done |
| EN2 | Declarative end redirects with an accessible delay | EN1 | §6 EN2 (security tests mandatory) | review |
| EN3 | Closing, availability windows and response limit | EX1 | §6 EN3 | todo |
| EN4 | Outcome column + quota place release on non-complete outcomes | EN1 | §6 EN4, with lead decision 5 | todo |
| EN5 | Show the participant's answers after submit | EN1 | §6 EN5 | todo |
| EN6 | Quota editor in the builder | — | §6 EN6 | todo |
| QB2 | Question bank: spec, `source`, `metadata.instruments`, osp-instruments package + verified bundle | QB1 | `planning/question-bank.md` §8 item 1 + lead decision 7 (verify every class A/B row online, URL + date; draft letter for the owner) | done |
| QB3 | Question bank ops | QB2 | §8 item 2 | todo |
| QB4 | Question bank store, API, permissions (migration 0011) | QB2 | §8 item 3 | todo |
| QB5 | Question bank in the builder | QB3, QB4 | §8 item 4 | todo |
| QB6 | Bundled translations | QB2 | §8 item 5 | todo |
| MM1 | Images, audio and video in surveys (by URL + a pluggable host media library) | — | **Plan first** (`planning/media.md`, post for lead review before coding). Media on question text/help, notes, choices (image choices) and matrix columns: `Media {kind: image/audio/video, url, alt (required for images), caption, transcript/captions URL (required for audio/video), width/height hint}`; added by **URL** in the builder; plus a **media provider contract** so a host backend can serve a list: `GET <host>/media?query=&cursor=` (via the same signed host proxy as the API, documented in `docs/hosting.md`) returning items {id, kind, url, thumbUrl, alt, …}, with the builder's media picker using it when the host config provides `links.mediaLibrary`, else URL-only; validation (https only, allowed origins list per deployment, CSP `img-src`/`media-src` generated from it, size/duration hints); participant rendering responsive + accessible (alt, captions track, transcript link, no autoplay with sound, reduced motion); research features: "must play to the end before Next", play/pause/seek counts + time-to-first-play recorded as paradata in the event log (inside the reproducibility package), preload next page's media; offline/slow network behaviour; exports (XLSForm `image`/`audio`/`video` columns; LSS where possible; loss diagnostics otherwise); tests across spec/engine/runtime/builder/e2e incl. 320 px and axe | todo |
| RT1 | Rich-text editor (WYSIWYG) for every text field in the builder | — | **Plan first** (`planning/rich-text.md`, post for lead review). Owner wants a GUI for text instead of typing raw text: question text and help, notes, choice labels, consent, endings, closed messages. Pick a permissive editor (e.g. ProseMirror/Tiptap MIT, Lexical MIT; `make licence-check`), clean-room. Define (or extend) the spec's rich-text model: a safe subset (paragraphs, bold, italic, underline, links with https-only + rel, lists, headings for notes, line breaks), stored as structured JSON or sanitised Markdown, never raw HTML; piping `${var}` shown as non-editable chips with a picker of available variables (and validation of references); per-language editing with the other language as reference; paste from Word/Google Docs cleaned to the subset; keyboard shortcuts and a toolbar that is fully keyboard/screen-reader accessible; renders identically in preview, participant app (never `{@html}` of untrusted input) and exports (XLSForm/LSS mapping + loss diagnostics); character counts; works at 320 px; tests across spec/ops/builder/runtime/e2e + axe; media embeds come from MM1 later. Plan merged, lead decisions 1–7 folded into the plan body; the build is RT2–RT6 | done |
| LV2 | Live results backend (watermark endpoint, live flag, coalesced audit, single-flight cache) | LV1 | `planning/live-results.md` §8 LV2 + lead decisions | done |
| LV3 | Live results page (poller, Live toggle, new-responses badge, layouts) | LV2 | §8 LV3 | todo |
| LV4 | Presentation mode live (batched, suppressed by default) | LV3, V6 | §8 LV4 + lead decision 1 | todo |
| F4 | Flaky: toolbox.spec "keyboard: arrows through the types, Shift+Enter chooses the page and position" (expected decimal, got text; ~1 in 24) | B16, B19 | Root-cause (likely Shift+Enter acting before the arrow-key selection settles, or the last-used type winning), fix in app or test without retries, 30 repeats green | todo |
| RT2 | Rich text: model end to end (spec, validation on write, rendering, traces unchanged) | RT1 | `planning/rich-text.md` RT2 + lead decisions | todo |
| RT3 | Rich text: the editor (Tiptap/ProseMirror, toolbar, pipe chips, paste) | RT2 | RT3 | todo |
| RT4 | Rich text: exports (XLSForm Markdown with escaping, LSS HTML) | RT2 | RT4 | todo |
| RT5 | Rich text: choice and row editors | RT3 | RT5 | todo |
| RT6 | Rich text: translations pane | RT3 | RT6 | todo |
| F5 | Flaky (residual): results-layouts.spec "drag a card by its handle to reorder" still fails ~1 per full `make web-e2e` run on a loaded Mac (passes 8/8 alone) after CI2's fix | CI2 | Root-cause the remaining race (native HTML5 drag under load: dragstart/dragover timing, or Save racing the reorder), fix without retries; 30 repeats in a full parallel run green | todo |

