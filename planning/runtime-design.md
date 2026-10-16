# Participant runtime design

**Status:** v2, 16 Oct 2026. Revised after cross-LLM review (GPT, Gemini, Qwen: all three APPROVE WITH CHANGES; see §10). Pending user approval. **Supersedes** `review.md` §2.6 (Enketo runtime) once approved.
**Decision (user, 16 Oct 2026):** we build our own participant runtime. The survey runs **entirely in the browser, except saving data** (and counts across participants). It must work well on every screen size. Enketo/XLSForm becomes an export target only.

## 1. Goals and non-goals

**Goals**
1. Participants on phones, tablets and desktops get a fast, accessible survey (WCAG 2.2 AA).
2. Behaviour follows `semantics.md` exactly. No lowerings or workarounds: the engine *is* the semantics.
3. One engine implementation for the runtime, the builder preview, the debugger and the simulator.
4. Every response is reproducible: survey version, plan checksum, seed, assignment, realised orders, event history and engine version are recorded.
5. **No lost answers.** Local-first persistence; the server acknowledges every save.
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
   - `every-page` (default): the network saves in steps 3–4 below. Partial responses are kept, and drop-outs are visible.
   - `end-only`: nothing reaches the server until submit. The browser still keeps a local copy, so a refresh resumes; it is deleted on submit or expiry. This suits ethics protocols that say "close the window and nothing is kept". The trade-offs are no cross-device resume and no data from drop-outs. Session start (seed, assignment) is still recorded, as an anonymous session row with no answers, so counts and quotas stay correct.
   - The builder explains the trade-off when the setting is switched. The setting is recorded in every response and in the codebook.
1. **Start.** `POST /s/{slug}/sessions` → `{ sessionId, resumeToken, sessionSeed, assigned, planUrl, planChecksum, revision: 0 }`. The server records seed and assignment *before* replying; the browser writes them to IndexedDB *before* showing the first page. Refreshing can't re-roll anything. URL parameters are recorded, never trusted for assignment.
2. **Local-first save.** Every answer change writes the snapshot to IndexedDB immediately.
3. **Network save.** `PUT /sessions/{id}/snapshot` with `baseRevision`:
   - when: page change, input blur, a debounce of ~3 s while typing, and `visibilitychange`/`pagehide` (with `fetch keepalive`)
   - the server accepts only `baseRevision == current`, increments it and acknowledges; a stale write gets `409` with the server snapshot
   - retries with exponential backoff + jitter; the UI shows a quiet "saved / saving / offline" status
4. **Resume.** On load, compare local and server revisions; never blindly prefer IndexedDB. The newest acknowledged revision wins; a local-only newer revision is sent with its base, and a true conflict (two devices) keeps the server copy and records the other in the audit log. Cross-device resume uses a resume link/code (secret, single-session, expires with the session).
5. **Quota.** `POST /sessions/{id}/quota/{nodeId}` is idempotent per (session, node): repeat calls return the recorded result. Reservation/consumption/expiry rules are research-design decisions (open question R-3).
6. **Submit.** `POST /sessions/{id}/submit` with the `ResponseRecord`, idempotent on `sessionId`. The server validates payload shape, plan checksum and assignment against the session. "Thank you" shows only after the acknowledgement. After submit, further snapshots for that session are rejected and the local copy is deleted.
7. **Private browsing / storage blocked.** Detect at start; fall back to network-only saving and save on every answer.
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

## 7. Security and data

- Researcher HTML in labels sanitised at save (allow-list); participant values HTML-escaped when piped; strict CSP (no inline scripts, no third-party origins).
- No IP stored by default. Paradata (page timings, device class) coarse by default; finer is opt-in per survey.
- Resume tokens are secret, scoped to one session, short-lived after inactivity, and rate-limited. Local copies are deleted after submit.
- Rate limiting on session start; optional bot checks without third-party CAPTCHA.
- Client logic can be bypassed by a determined participant; accepted, and detectable via optional verification.

## 7a. Researcher hooks (custom code on key events)

Researchers can attach their own JavaScript to key events, similar to SurveyJS's `onValueChanged` / `onCurrentPageChanged` / `onComplete`. Examples: computing a score, logging extra paradata, calling a lab's own API at the end, or talking to an embedding page.

**Where it runs:** a **Web Worker inside a sandboxed, opaque-origin iframe**. It has no DOM, no access to the participant page, cookies or storage, and no network by default (the iframe's CSP has `connect-src 'none'`). Network access is an opt-in per survey, with an explicit origin allowlist shown to the researcher at publish.

**Events** (each receives a read-only, structured-clone copy):

| Event | Payload |
|---|---|
| `onStart` | `ctx` + URL parameters |
| `onPageShown` | `ctx` + visible items, realised orders |
| `onAnswer` | `ctx` + item id, new value, old value |
| `onPageNext` | `ctx` |
| `onComplete` | `ctx` + the full `ResponseRecord` (before submit) |


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
- `setEndRedirect(url)`: only for allowlisted origins.
- `postToParent(message)`: for embedded surveys (`window.parent.postMessage` with a declared target origin).

**Rules:**
- **Hooks never decide flow directly.** They can set declared variables, which conditions may then read, so the engine stays the single place where flow happens.
- **Async with timeouts.** The engine waits for `onPageNext`/`onComplete` hooks up to a declared timeout (default 2 s), then continues and records `hook.timeout`. Other events are fire-and-forget.
- **Reproducible.** Every hook action is recorded in the event log with its result, so replay and verification use the recorded actions and don't re-run the code.
- **Errors never break the survey.** A thrown error or timeout is logged in paradata and the survey continues.
- **Versioned with the survey.** The code is part of the published version and its checksum. The builder shows a "this survey runs custom code" badge. Exports to other platforms report hooks as `unsupported` (or map to SurveyJS events where possible).
- **Permissions.** Only `owner`/`editor` roles may add hooks, and adding one is an audited op.

Later (not MVP): custom **expression functions** (sync, pure, usable in conditions), which would need a different sandbox.

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
| — | **R7** researcher hooks: sandbox, event API, actions, timeouts, event-log recording (§7a) |
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

## 11. Open questions (need a human decision)

- **R-1** Default autosave also on every answer when IndexedDB is blocked (private mode). Proposed: yes.
- **R-2** Two-device conflict: proposed rule is "server copy wins, the other is kept in the audit log". OK?
- **R-3** Quotas and balanced assignment: when is a slot consumed (at assignment or at completion), and when does an abandoned session release it (proposed: consumed at assignment, released after 24 h of inactivity)?
- **R-5** Save-mode default: `every-page` (proposed) or `end-only`?
- **R-7** Built-in `$` variables: names OK, and should `$trial` count re-visited pages after back (proposed: no)?
- **R-6** Hooks in the MVP, or straight after the pilot? Proposed: MVP, with network access off by default.
- **R-4** Paradata default: page-level timings + device class (phone/tablet/desktop) on by default. OK?
