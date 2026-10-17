# Participant runtime design

**Status:** v2, 16 Oct 2026. Revised after cross-LLM review (GPT, Gemini, Qwen: all three APPROVE WITH CHANGES; see §10). **Approved by the user 16 Oct 2026**, with R-1 to R-8 as proposed. **Supersedes** `review.md` §2.6 (Enketo runtime).
**Decision (user, 16 Oct 2026):** we build our own participant runtime. The survey runs **entirely in the browser, except saving data** (and counts across participants). It must work well on every screen size. Enketo/XLSForm becomes an export target only.

## 1. Goals and non-goals

**Goals**
1. Participants on phones, tablets and desktops get a fast, accessible survey (WCAG 2.2 AA).
2. Behaviour follows `semantics.md` exactly. No lowerings or workarounds: the engine *is* the semantics.
3. One engine implementation for the runtime, the builder preview, the debugger and the simulator.
4. Every response is reproducible: survey version, plan checksum, seed, assignment, realised orders, event history and engine version are recorded.
5. **No lost answers in `every-page` mode.** Local-first persistence; the server acknowledges every save. (`end-only` trades this away by design, §5.0.)
7. **Easy to make it look like your lab's survey** (§6a), without breaking accessibility.
6. Small and boring: a single static bundle; the server only stores and counts.

**Non-goals (MVP)**
- Full offline data collection (days without a connection). We tolerate drops, tab kills and refreshes.
- Custom question *widgets* from researchers (custom event hooks are in scope, §7a). Media capture (audio, photo).
- Real-time collaboration on a single response.

## 2. What runs where

| Concern | Browser | Server (Python) |
|---|---|---|
| Page order, branching, randomisers, show-if, required, constraints | ✅ TS engine | — |
| Piping (values HTML-escaped at render), text trimming, missing-value states | ✅ | — |
| Question/block/choice shuffles | ✅ seeded by `sessionSeed` | — |
| `sessionSeed` | — | ✅ generated at session start (positive integer, 1…2^53−1) |
| Condition assignment | ✅ simple random, from seed (`assign` node) | ✅ balanced or quota-based (needs counts across participants), atomic |
| Quotas | — | ✅ atomic counter at the `quotaCheck` node (one API call) |
| Autosave, resume (same or another device), final submit | sends | ✅ stores (encrypted), acknowledges, rejects stale writes |
| Verify a submission | — | ✅ **optional** per survey: replays the event history through the same TS engine (Node sidecar) and flags inconsistencies |
| Survey validation, ops, exports, storage, auth | — | ✅ (existing Python packages) |

## 3. Packages and engine

```text
web/engine/        pure TypeScript, no DOM, no I/O, no Math.random, no Date.now (injected clock)
                   state machine + expression evaluator + randomize port + event log + trace
web/runtime/       participant app: Svelte 5 + Vite, static, own small bundle (not SvelteKit)
web/ui-components/ shared tokens + Bits UI–based accessible primitives (combobox, slider…)
python/osp-runtime publish: validated survey → "runtime plan" JSON; session/save/quota/submit API
```

- **Runtime plan.** At publish, Python compiles the survey into plain JSON: ids resolved, expressions as AST (the browser never parses text syntax), checksum + plan version. Served immutable from a cacheable URL.
- **Engine API (effects are explicit, so async steps survive retries and resume):**
  ```ts
  start(plan, { sessionSeed, assigned, clock }) → State
  view(state) → PageView                  // items, resolved pipes, errors, focus target
  answer(state, itemId, value) → State    // live show-if within the page
  next(state) → { state, effect? }        // effect: { kind: "quota", nodeId } | { kind: "end", outcome }
  resolve(state, effect, result) → State  // quota result recorded in state; replay uses the recorded result
  back(state) → State
  snapshot(state) → Snapshot              // includes event log, realised orders, revision
  restore(plan, snapshot) → State | { error }
  result(state) → ResponseRecord          // values + per-question state + orders + event log + versions
  ```
- **Event log.** Every answer, next, back and effect result is appended (with injected timestamps). Final answers alone can't reconstruct erased answers or earlier paths; the log can, and it is what verification replays.
- **Realised orders** are computed at first reach and stored in state *before* the page renders; every snapshot carries them.
- **Decimals.** Exact decimal arithmetic via a small audited library (`big.js` or `decimal.js-light`, MIT), with rounding rules fixed in `semantics.md`. Never JS floats for answers or expressions.
- **SHA-256** for `node_seed`: a small audited sync implementation (WebCrypto is async), with test vectors shared with Python.
- **Bundle budget (target, not a gate):** engine ≤ 30 KB gzip, runtime app ≤ 90 KB gzip. Correctness libraries win over kilobytes.

## 4. The existing Python code

- `osp-expr` (C1) parses and type-checks at save/publish; the TS engine evaluates the same AST.
- `osp_engine.random` (C4a) stays for server-side assignment and as the parity reference. Shared vectors include seed-hash inputs and safe-integer boundary seeds.
- The planned Python flow engine (C4) is **dropped**. Simulator and debugger run the TS engine (browser in the builder; Node sidecar on the server).
- Fixtures are the contract. Expand from 20 with **adversarial transition fixtures**: back-and-change cascades, irrelevant-value clearing chains, refresh at every step, quota pending/retry, resume on a second device, decimal/whitespace edge cases, and the four Enketo spike workarounds as regression scenarios.

## 5. Session protocol and data safety

0. **Save mode (per survey, researcher's choice).**
   - `every-page` (default): network saves as in steps 2–4. Partial responses are kept, and drop-outs are visible.
   - `end-only`: **no response data is uploaded before submit**. This covers answers, hook output, paradata and URL parameters such as Prolific IDs, which stay in the browser until submit. The server still sees session start (seed, assignment) and quota checks. This is disclosed in the consent-text template, because a session row may still be pseudonymous data under GDPR.
     - A local copy option is available: `browser` (IndexedDB, so a refresh resumes; deleted on submit and cleaned up on the next load after expiry) or `memory` (closing or refreshing the window loses everything, which is the strict "nothing is kept" promise).
     - If storage is blocked, it falls back to `memory`, disclosed on screen. It never falls back to network saving.
     - The trade-offs are no cross-device resume, no drop-out data (attrition is invisible), and loss on crash or storage eviction. The builder spells these out when the setting is switched.
   - The mode is recorded in every response and in the codebook.
1. **Start.** `POST /s/{slug}/sessions` → `{ sessionId, resumeToken, sessionSeed, assigned, planUrl, planChecksum, revision: 0 }`. The server records seed and assignment *before* replying; the browser writes them to IndexedDB *before* showing the first page. Refreshing can't re-roll anything. URL parameters are recorded, never trusted for assignment.
2. **Local-first save.** Every answer change writes the snapshot to IndexedDB immediately.
3. **Network save.** `PUT /sessions/{id}/snapshot` with `baseRevision`:
   - when: page change, input blur, a debounce of ~3 s while typing, and `visibilitychange`/`pagehide` (with `fetch keepalive`)
   - the server accepts `baseRevision == current`, increments it and acknowledges; a stale write gets `409` with the server snapshot, with two exceptions judged by event log inside the write's transaction: a late save that the server copy already contains is acknowledged as `superseded` (nothing written), and a save whose log strictly extends the server copy's is a **fast-forward**, written on the current revision whatever its base (R9-1, below)
   - retries with exponential backoff + jitter; the UI shows a quiet "saved / saving / offline" status
4. **Resume.** On load, compare local and server revisions; never blindly prefer IndexedDB. The newest acknowledged revision wins; a local-only newer revision is sent with its base, and a true conflict (two devices) keeps the server copy and records the other in the audit log. Cross-device resume uses a resume link/code (secret, single-session, expires with the session).
5. **Quota.** `POST /sessions/{id}/quota/{nodeId}` is idempotent per (session, node): repeat calls return the recorded result. Reservation/consumption/expiry rules are research-design decisions (open question R-3).
6. **Submit.** `POST /sessions/{id}/submit` with the `ResponseRecord`, idempotent on `sessionId`. The server validates payload shape, plan checksum and assignment against the session. "Thank you" shows only after the acknowledgement. After submit, further snapshots for that session are rejected and the local copy is deleted.
7. **Private browsing / storage blocked.** Detect at start; fall back to network-only saving and save on every answer.
   - **Refresh straight after typing (R9-1, 17 Oct 2026).** The server is the only copy, so the dying page's last saves must land. At `pagehide` a save is often already on the wire (base *b*); the page also sends its newest snapshot on *b + 1*. The two can reach the store in either order: even sent in order they run on concurrent server threads. Seen in fixture 30 `storage-blocked` (1 in 40 runs, server save log): the wire save (base 5, best = "a") entered first, the chained one (base 6, "a long novel") entered 3 ms later but reached the store first and was refused `409` (a conflict row), then the wire save landed as revision 6; the reload resumed "a". Two further holes, from reading the code: (b) the reloaded page's resume can overtake both keepalive saves, show the older copy, and the participant's next action then diverges from the server's newer copy and becomes a conflict; (c) the service's "superseded" check read the server copy before the write's transaction, so a concurrent write in between turned a harmless late save into a conflict row. And when the page was hidden while a save waited out a backoff (not on the wire), only that older body was sent, never the newest.
   - Fix, server side: the fast-forward rule above, decided inside the store's transaction (the service passes a `judge`; `osp-store` calls it against the copy it holds right then, and reads and judges again, up to 3 times, if a concurrent write moved the revision before the fast-forward could land). Safe because a log that extends the server's contains everything the server has: nothing is overwritten. Two devices that diverged (neither log a prefix of the other) still get `409`, the server copy wins and the other is kept (R-2, R6-6; fixture 25 unchanged).
   - Fix, client side: `flushKeepalive` sends the pending body if nothing is on the wire, and always chains the newest snapshot on *b + 1* when it is newer than that body (once per engine revision, since a refresh fires both `visibilitychange` and `pagehide`). An edit is an appended answer event, so it extends the wire copy like any keystroke. As the page is hidden with a save unacknowledged, the session pointer (`localStorage`/`sessionStorage`, not the URL fragment) records that snapshot's engine revision: a number, never answers, so the "no local copy" promise holds. A reload from the pointer that resumes an older server copy asks again (50 ms doubling, ~3 s at most) until the server reaches it; a save that never lands only delays the reload. The page clears that number once the server acknowledges everything (hidden, then shown again). With IndexedDB available nothing changes: the local copy and the pagehide backup already hold the newest snapshot, and the reload pushes it.
   - Rejected: a client-only fix (send the newest snapshot on both *b* and *b + 1*) logs a spurious conflict in one of the orders and still loses to (b); keeping the snapshot in `sessionStorage` would break the private-mode promise of no answers on the device.
8. **Optional verification** replays the event log through the engine and stores `verified` plus differences. It proves consistency, not truthful participation.

## 6. Screen sizes, input and accessibility

Mobile-first. Test at 320, 375, 768, 1024 and 1440 CSS px, portrait and landscape, plus 400% zoom on desktop, 200% text enlargement, long translations (German) and RTL.

| Topic | Rule |
|---|---|
| Layout | Single column, max reading width ~42rem, fluid type. No horizontal scroll at 320 px or 400% zoom (WCAG 1.4.10). Use `dvh`/`svh`, never `100vh` |
| Text inputs | Font size ≥ 16 px (stops iOS auto-zoom); pinch zoom never disabled |
| Touch | Targets ≥ 44×44 px even when labels wrap; whole choice row is the hit area; no hover-only affordances |
| Matrix | Table only when the content fits (breakpoint chosen by measuring, not a fixed 640 px). Otherwise each row is a `<fieldset>` with the row label as `<legend>`, and each option is labelled with its scale label. **One DOM**, restyled; never duplicate desktop and mobile controls |
| Sliders | Start **unanswered**, with no thumb shown until touched; the midpoint is never a silent answer. Visible value, keyboard steps, and a numeric-input alternative |
| Long choice lists | Radio list by default; a searchable combobox is a per-question option for the researcher, not automatic |
| Date | Three labelled fields (day / month / year) in locale order, with strict validation; native picker not used (inconsistent across iOS and Android) |
| On-screen keyboard | `inputmode` per type, `enterkeyhint="next"`. The sticky nav bar hides or docks below the content while an input is focused; `visualViewport` keeps the focused input visible. Test iOS Safari specifically |
| Navigation | Sticky bottom Next/Back bar with `env(safe-area-inset-bottom)`; it must never obscure the focused element (WCAG 2.4.11) |
| Focus | After next/back, focus moves to the page heading; after a failed next, to the error summary. Conditional reveals are announced once (polite live region) |
| Errors | Inline under the question + summary at the top with links; no duplicate announcements |
| Language and themes | `lang` per text; RTL via logical CSS properties; `prefers-reduced-motion`; per-survey theme checked for AA contrast at publish |
| Primitives | Combobox, slider, dialog and others come from Bits UI–based `ui-components`; no hand-rolled ARIA widgets |
| Slow devices | One page rendered at a time; target < 1 s to interactive on a mid-range Android over 4G |

**Testing:** Playwright device profiles (iPhone SE, Pixel 7, iPad, desktop Chrome/Firefox/WebKit), axe-core per widget × width, visual snapshots per widget × width, network-interruption and tab-kill tests. **Real-device** VoiceOver (iOS) and TalkBack (Android) passes are acceptance gates before the pilot; Playwright and axe don't replace them.

## 6a. Appearance: easy customisation

Researchers style a survey **by editing design tokens in the builder, not by writing CSS**. Every survey page is drawn from the same tokens (`ui-components`), so a theme can't break the layout or accessibility rules in §6.

**Theme editor (builder):**
1. **Start from a preset:** 4–6 calm presets (e.g. Clean, Warm, High contrast, Dark, Compact).
2. **Brand:** logo (uploaded and served from our origin), accent colour, background colour or image, and header text.
3. **Type:** a system font stack or one of a few bundled open-licence fonts (OFL), base size, and line spacing.
4. **Shape and density:** corner radius, spacing (comfortable / compact), button style (filled / outline), and choice style (list / cards / buttons).
5. **Mode:** light, dark, or follow the participant's device.

- **Live preview** shows phone, tablet and desktop side by side, plus any question type picked from the survey.
- **Guard rails:** every colour pair is checked for WCAG AA contrast as you edit. A failing pair shows the nearest passing colour with a one-click fix, and publishing is blocked until it passes. Text size can't go below 16 px on inputs.
- **Reuse:** themes are saved to the lab (tenant) theme library. One click applies a theme to any survey, and a lab default applies to new surveys.
- **Per page:** pages use the survey theme. A page can switch to a "full-bleed" layout for stimuli (e.g. a centred image or video).

**Advanced: custom CSS** (opt-in, owner/editor, clearly labelled "may break accessibility"):
- It is applied after the tokens and scoped to the survey container.
- It is sanitised at save: no `@import`, and no `url()` except assets uploaded to the survey. Those rules block CSS-based data leaks. There is also a size limit.
- The preview runs axe on save and shows any new violations.

**Export:** themes map to the closest equivalent in each export target (e.g. SurveyJS theme JSON, LimeSurvey theme options), and anything that doesn't map is reported as `approximated`.

## 7. Security and data

- Researcher HTML in labels sanitised at save (allow-list); participant values HTML-escaped when piped; strict CSP (no inline scripts, no third-party origins).
- No IP stored by default. Paradata (page timings, device class) coarse by default; finer is opt-in per survey.
- Resume tokens are secret, scoped to one session, short-lived after inactivity, and rate-limited. Local copies are deleted after submit.
- Rate limiting on session start; optional bot checks without third-party CAPTCHA.
- Client logic can be bypassed by a determined participant; accepted, and detectable via optional verification.

## 7a. Researcher hooks (custom code on key events)

Researchers can attach their own JavaScript to key events, similar to SurveyJS's `onValueChanged` / `onCurrentPageChanged` / `onComplete`. Examples: computing a score, logging extra paradata, calling a lab's own API at the end, or talking to an embedding page.

**Where it runs:**
- **The sandbox:** a Web Worker inside an iframe with `sandbox="allow-scripts"` only. That means no same-origin, popups, navigation, forms or downloads.
- **CSP:** the iframe and worker CSP is `default-src 'none'`, with the hook script loaded only from the published version (no `importScripts` from elsewhere, no nested workers).
- **Messaging:** the host and the worker talk only over a dedicated `MessagePort`. Origin `"null"` is never treated as authentication.
- **Host validation:** the host checks every action (type, size, nesting depth, rate, allowed variable ids).
- **Deadlines:** the host enforces deadlines from outside and **terminates and respawns** the worker on timeout or flooding. That also bounds CPU and memory.
- **Deterministic inside:** `Math.random` and `Date` inside the worker are replaced by `ctx.random()` (seeded per hook) and `ctx.now()` (injected clock), and both are logged.

**Events** (each receives a read-only, structured-clone copy):

| Event | Payload |
|---|---|
| `onStart` | `ctx` + URL parameters |
| `onResume` | `ctx` (after refresh or cross-device resume) |
| `onPageInit` | `ctx`, before the page renders; can set variables used on that page |
| `onPageShown` | `ctx` + visible items, realised orders |
| `onAnswer` | `ctx` + item id, new value, old value |
| `onPageNext` | `ctx`; may `rejectPage` |
| `onBack` | `ctx` |
| `onValidationError` | `ctx` + failed items and messages |
| `onBeforeSubmit` | `ctx` + the full `ResponseRecord` |
| `onSubmitted` | `ctx`, after the server acknowledges; side effects to external systems belong here |


**Context object (`ctx`), passed to every hook** (read-only, always up to date):

| Field | Meaning |
|---|---|
| `ctx.trial` | 1-based number of the current page/trial in this participant's path (counts only pages actually shown; back then next doesn't increase it) |
| `ctx.trialId`, `ctx.blockId` | ids of the current page and block |
| `ctx.position` | position within the enclosing randomiser or loop (`{ randomiserId, index, of }`), e.g. trial 3 of 12 stimuli |
| `ctx.pagesDone`, `ctx.pagesEstimated` | progress (the estimate assumes current answers) |
| `ctx.conditions` | assigned conditions, e.g. `{ framing: "loss" }` |
| `ctx.language`, `ctx.device` | current language; `phone` / `tablet` / `desktop` |
| `ctx.elapsedMs`, `ctx.trialElapsedMs` | time since start / since this page was shown (injected clock) |
| `ctx.results` | values + per-question states, exactly as exported |
| `ctx.vars` | declared embedded/hook variables |
| `ctx.sessionId` | pseudonymous session id (never participant identity) |

The same position fields are **built-in variables in expressions and piping**: `$trial`, `$position.index`, `$position.of`, `$pagesDone`, `$language`, `$device`. Example: `"Trial ${$trial} of ${$position.of}"`. Timing fields are available **only in hooks**, because expressions stay pure and reproducible (`semantics.md` §3). A hook can copy a time into a declared variable when a condition needs it.

**What a hook may return** (a short list of actions; anything else is ignored with a logged diagnostic):
- `setVariable(id, value)`: only for `embedded`/`hook`-kind variables declared in the survey (typed and validated), never for questions.
- `addParadata(key, value)`: stored with the response.
- `rejectPage({ itemId?, message })`: from `onPageNext` only; it blocks advancing with a custom validation error (e.g. "must sum to 100"). The message is shown as a validation error.
- `setEndRedirect(templateId, params)`: picks one of the redirect URL templates declared at publish (e.g. Prolific completion URL). Only declared placeholders may be filled, and there is no free-form URL.
- `postToParent(type, payload)`: only message types declared at publish, with a typed schema, to the declared parent origin.

**Data-export capabilities.** Network access, redirects and parent messages can all carry participant data off the platform, so they are treated as data exports:
- owner-only
- listed in the codebook and the consent-text template
- audited
- re-confirmed by an owner whenever hook code changes

**Rules:**
- **Declared reads.** Each hook declares which questions and variables it reads; `ctx.results` contains only those.
- **Hooks never decide flow directly.** They can set declared variables, which conditions may then read, so the engine stays the single place where flow happens.
- **Ordered engine effects.** Every hook call is an engine effect with an invocation id and the state revision it saw. Results that arrive after the state has moved on are rejected and logged. Actions never trigger further hooks, so there are no loops.
- **Timeouts and failure.**
  - The default timeout is 2 s.
  - If a hook's variable is read by any condition or branch (flow-critical, detected at publish), a timeout or error shows a retry prompt. After that it ends with outcome `hook-failed`. It **never silently takes a different path**, because that would create device-speed bias.
  - Non-critical hooks (paradata, logging) fail open.
- **Reproducible.** Every hook action is recorded in the event log with its result, so replay and verification use the recorded actions and don't re-run the code.
- **Hook-set text is untrusted.** It's always HTML-escaped and can't be piped into consent text, platform UI or error banners. It is visually just answer-style text.
- **Versioned with the survey.** The code is part of the published version and its checksum. The builder shows a "this survey runs custom code" badge. Exports to other platforms report hooks as `unsupported` (or map to SurveyJS events where possible).
- **Permissions.** Only `owner`/`editor` roles may add hooks, and adding one is an audited op.

- **Acceptance gate (before hooks ship):** adversarial tests for:
  - egress bypasses, forged port messages, floods, infinite loops, oversized allocations
  - stale results, refresh during a hook, duplicate submit
  - `end-only` mode with blocked storage

**In the participant app (R3b).** The manifest is the plan's optional `hooks` field (`contract/runtime-plan.schema.json`; `compile_plan(survey, hooks=…)`), so it is inside the plan checksum. When it is present, `web/runtime` loads `@osp/hooks-sandbox` as a separate chunk and drives the session through `HookRunner` (`src/lib/hooks.ts`); surveys without hooks never download it. An invalid manifest stops the session with a message rather than running without its hooks. The built `index.html` carries the page CSP: `script-src 'self'` plus the frame script's hash, and `worker-src blob:` (a `srcdoc` iframe inherits the page CSP; its own CSP then narrows it to `default-src 'none'`).

**Production: a separate sandbox origin.** Build with `OSP_HOOKS_FRAME_URL=https://<sandbox-site>/hooks-frame.html` and serve `dist/hooks-frame.html` (written by the build) at that URL, on a different *site* from the app, so site isolation puts a hook that exhausts memory in its own process. The build adds that origin to the CSP's `frame-src`; the sandbox host should serve the file with the same `default-src 'none'` CSP as a header. Without the variable the frame is a `srcdoc` iframe on the app's origin (fine for development and tests).

Later (not MVP): custom **expression functions** (sync, pure, usable in conditions), and jsPsych-style trial timing (stimulus onset, response latency at frame accuracy), which needs its own design. Qualtrics-style DOM manipulation is deliberately unsupported.

## 8. Scope for the pilot (acceptance gates)

**Pilot widgets only:** integer, decimal, text (short/long), single (radio), multi (checkbox), date (3-field), note, matrix (single-choice rows), slider. Everything else waits.

Gates before the pilot:
1. All fixtures (incl. adversarial) pass in the TS engine and through the runtime in Playwright on every device profile.
2. Network-interruption, tab-kill, refresh-at-every-step and two-device resume tests show zero lost or duplicated answers.
3. axe clean; real-device VoiceOver + TalkBack pass on every pilot widget.
4. Python ⇄ TS parity on 10,000 seeds and the shared hash vectors.

## 9. Task changes

| Old | New |
|---|---|
| E1 Enketo bundle | **Dropped** (branch kept) |
| C4 Python flow engine | **R1** TS engine `web/engine` (effects, event log, decimals) + fixture runner |
| C6 XLSForm target | Stays as an **export** (off the critical path) |
| C7 Enketo runtime | **R2** plan compiler + session API in `osp-runtime` (revisions, idempotent quota/submit); **R3** participant app `web/runtime` (local-first save, focus, nav) |
| C8 Enketo harness | **R4** Playwright harness: fixtures through `web/runtime` on device profiles + interruption tests |
| — | **R5** pilot widgets × responsive/a11y rules (§6), axe + snapshots |
| — | **R6** adversarial fixtures (§4) |
| — | **R7** researcher hooks: sandbox, event API, actions, effects, timeouts, adversarial gate (§7a) |
| — | **R8** theme tokens + theme editor + contrast guard + theme library (§6a); custom CSS sanitiser later |
| B11 Enketo preview | Preview embeds `web/runtime` with the draft plan; debugger steps the same engine |

## 10. Review log (16 Oct 2026)

All three reviewers: **APPROVE WITH CHANGES**. They agreed on one TS engine, plain Svelte + Vite, and that autosave was under-specified.

Adopted:
- local-first IndexedDB on every change
- `visibilitychange`/`pagehide` flush
- revisioned conditional writes with server ACK
- seeds/orders committed before first render
- explicit async effects
- event log
- idempotent atomic quotas
- matrix `fieldset`/`legend` with one DOM
- slider unanswered state
- 16 px inputs, `dvh`, safe-area
- nav bar vs keyboard
- focus rules
- no automatic combobox
- 3-field dates (Gemini; GPT asked for date testing)
- Bits UI primitives
- exact decimals
- narrowed pilot scope with gates
- real-device AT testing
- escaping piped values
- resume-token protection

Not adopted: none rejected. The bundle budget became a target, per GPT.

**Second review (save mode + hooks), 16 Oct 2026:** all three reviewers said APPROVE WITH CHANGES on both.

Adopted:
- the full sandbox spec (iframe flags, CSP, `MessagePort`, host-side validation, terminate/respawn)
- redirects as declared templates
- typed parent messages
- network, redirect and parent messages treated as data exports
- ordered effects with invocation ids and stale-result rejection
- flow-critical hooks that never silently change path
- seeded `ctx.random`/`ctx.now`
- declared reads
- `rejectPage` for custom validation
- `onPageInit`, `onResume`, `onBack`, `onValidationError`, `onBeforeSubmit`/`onSubmitted`
- an adversarial acceptance gate
- `end-only` redefined as "no response data before submit", with a memory-only option, no network fallback, URL identifiers kept local, and GDPR disclosure

GPT suggested shipping hooks after the pilot; the design now gates them (R-6).

## 11. Decisions (approved 16 Oct 2026, as proposed)

- **R-1** In `every-page` mode, when IndexedDB is blocked (private mode), save to the server on every answer. Proposed: yes. (`end-only` never does this; it falls back to memory.)
- **R-2** Two-device conflict: proposed rule is "server copy wins, the other is kept in the audit log". OK?
- **R-3** Quotas and balanced assignment: when is a slot consumed (at assignment or at completion), and when does an abandoned session release it (proposed: consumed at assignment, released after 24 h of inactivity)?
- **R-5** Save-mode default: `every-page` (proposed) or `end-only`?
- **R-7** Built-in `$` variables: names OK, and should `$trial` count re-visited pages after back (proposed: no)?
- **R-6** Hooks in the MVP, or straight after the pilot? Proposed: build them in the MVP, but enable them for the pilot only if the adversarial gate passes; network access stays off by default.
- **R-8** Custom CSS in the MVP? Proposed: no; token-based themes first, custom CSS after the pilot.
- **R-4** Paradata default: page-level timings + device class (phone/tablet/desktop) on by default. OK?
