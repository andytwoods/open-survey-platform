# Live results: the Results page updates as responses arrive (plan LV)

Status: **proposed** 17 Oct 2026 (task LV1, research and plan only; nothing built). The owner
likes the idea of the Results page (and presentation mode, V6) showing live data and
suggested htmx. This document compares polling, Server-Sent Events, WebSockets and htmx
against the architecture we have, and recommends one approach with phases and build tasks.

Related: `results-viewer.md` (plan V, decisions V-D1–V-D10), `pages-split.md` (static pages
mounted by a host, signed identity), `docs/hosting.md` (the proxy a host writes).

## 1. What we have today (the constraints)

Everything below is on `main` and shapes the options.

| Fact | Where | Why it matters here |
|---|---|---|
| The Results page is a **static Svelte bundle** (`results` entry) that the host's HTML mounts behind its own sign-in. The host owns the HTML; osp-api never renders a page. | `web/builder/src/pages/results.ts`, hosting §2 | A server-rendered-fragment design has no server that renders |
| Pages run under **`script-src 'self'`**, no inline script, no eval. Charts use Vega's interpreter (`ast: true`) for that reason. | hosting §5, `charts/ResultsChart.svelte` | Anything we add must be in our bundle and eval-free |
| Every API call goes **through the host's proxy**, which signs each request (`X-OSP-*`, HMAC over method, path, query, body hash, time, nonce). A signature is valid 60 s and a nonce is single-use, kept in the **database** in production so several workers can run. | hosting §3, `osp_host_signing` | Every poll is a signed request plus one nonce write. A long-lived stream is signed once, at connect |
| The documented Django proxy **buffers** the whole upstream response (`r.content`, `timeout=60`) and returns it. | hosting §6 | SSE and WebSockets need a host that streams; ours doesn't by default |
| Aggregates are computed server-side by `survey.results_query`: one streaming decrypt pass over every response, every card at once. **LRU cache** (32 entries, per process) keyed by (tenant, survey, versions, **watermark**, query hash). | `osp_app/results.py` | A re-query is cheap when nothing changed and a full scan when something did |
| The **watermark** is a hash of per-version `(response count, newest submitted_at)`, read by one `COUNT`/`MAX` query that reads and audits **no answers**. Any new or deleted response changes it. | `ParticipantStore.response_watermark` | A cheap "did anything change?" already exists; it just has no endpoint of its own |
| Benchmark (SQLite, 10 cards, split, intervals): **10 k responses 0.40 s first / 4 ms cached; 100 k 5.3 s / 38 ms**. | `test_results_bench.py`, devlog V1 | Live refresh of a 10 k survey is sub-second; of a 100 k survey it is not |
| Every query writes a `results.read` audit row (query, versions, `cached`), and an uncached scan writes a `responses.read` row as well. | `results.py`, `stream_responses` | Naive auto-refresh multiplies audit rows |
| The page's `ResultsController.load()` already supersedes an older request, supports cancel, and shows elapsed time. Charts are **re-embedded** (old view finalised, new SVG drawn) on every spec change. | `results.svelte.ts`, `ResultsChart.svelte` | A refresh is one `load()`; redraws are instant swaps, not animations |
| Presentation mode is a URL flag (`?present=1`, `?layout=<id>`), shareable and printable. | `presentation.ts`, docs/results.md | A lab screen can already open a frozen view; it needs to stay fresh |
| Owners and editors see exact counts in the app; suppression ("hide counts below k") exists for exports only. A viewer role with forced suppression is phase 3 of plan V. | V-D3, V-D4 | Live small-n is a new disclosure channel (section 4) |
| Route handlers are plain `def` (run in Starlette's thread pool, 40 threads by default); the API is FastAPI on uvicorn, possibly several workers. | `osp_api/routes/*.py`, hosting §1 | A long-lived connection per viewer must not hold a pool thread; cross-worker fan-out needs the database, not process memory |

## 2. The options

### (a) Poll the watermark, re-query only on change

The page asks a new, cheap endpoint for the survey's watermark every *n* seconds. When it
differs from the one in the last `ResultsResponse`, the page runs its normal `load()`; the
server's cache makes identical queries from several viewers one computation.

- **Fits everything above.** Plain signed GETs through any proxy, no streaming, no new
  dependency, no CSP change, same-origin cookies as today, nothing new for hosts.
- **Cost per viewer per interval:** one HMAC verification, one nonce insert (production),
  one indexed `COUNT`/`MAX`. At 10 s and 20 viewers that is 2 requests/s: negligible for
  Postgres; fine for SQLite (reads).
- **Latency:** the poll interval (5–10 s). Good enough for "watch responses come in"; not
  for "see each click".
- **Weakness:** the signed-request overhead is per poll, so the interval cannot be tiny.
  Mitigated by pausing in hidden tabs and backing off when idle (section 5).

### (b) Server-Sent Events: a "responses changed" stream per survey

`GET /api/surveys/{id}/results/events` returns `text/event-stream`; the server sends a
`watermark` event when it changes (plus a heartbeat). The page still re-queries through the
normal endpoint; the stream only says *when*.

- **Server side is straightforward:** an async route with a `StreamingResponse` (Starlette
  has it; `sse-starlette` is BSD but not needed). One per-process watcher per survey polls
  `response_watermark` every 1–2 s in the thread pool and fans out to its subscribers with an
  `asyncio.Event`, so 50 viewers cost one DB query per tick, not 50. Several uvicorn workers
  each watch the database, so they agree without a message bus. `submit` can wake the
  watcher in its own process for sub-second latency; the DB poll stays the source of truth.
- **The host proxy is the problem.** The browser's `EventSource` opens one long GET. The
  host must (1) forward it *streaming* (Django: `StreamingHttpResponse` over
  `httpx.stream`; nginx: `proxy_buffering off`, `proxy_read_timeout` above the heartbeat),
  (2) not time it out at 60 s, and (3) have a server that can hold connections open: a WSGI
  host on sync gunicorn workers burns one worker per viewer for the life of the stream. The
  in-process ASGI host (hosting §3) is fine. So SSE is **opt-in per host**, never the default.
- **Signed identity:** the signature is checked once at connect. To re-check roles (the
  host is the source of truth on every request), the server closes each stream after at
  most 5 minutes; `EventSource` reconnects by itself (`retry:` 3 s). `EventSource` cannot set
  headers and does not need to: same-origin cookies carry the host session, the request is
  a GET (no CSRF), and the host signs it like any other.
- **Failure handling:** `EventSource` reports a bare `error` (no status), so the page cannot
  tell 401 from a proxy that buffered the stream until timeout. Rule: any stream error or
  a stream that produced no heartbeat within 30 s drops to polling (a), which surfaces the
  real status through the normal path.
- **Gain over polling:** one signed request per 5 minutes instead of one per 10 s per
  viewer, and 1–2 s latency. Worth having for hosts that can stream; not worth blocking on.

### (c) WebSockets

Everything SSE needs, plus: the host proxy must speak the WebSocket upgrade (a WSGI Django
host cannot; it needs Daphne/uvicorn or a separate route at the reverse proxy), the signing
scheme would need a WebSocket variant (the upgrade is a GET, so `sign_identity_headers`
technically applies, but the host's proxy code would be new and un-reusable), and a second
channel for the client to send messages we have no use for: the page only needs to be told
"changed". Bidirectional transport buys nothing here. **Rejected.**

### (d) htmx (the owner's suggestion), evaluated honestly

htmx replaces JavaScript with HTML attributes: `hx-get` fetches **HTML fragments** from the
server and swaps them into the DOM; `hx-trigger="every 5s"` makes that polling; the SSE
extension swaps fragments pushed by the server. It is a good fit for a server that renders
pages and wants small, declarative interactivity without a bundle. Against our architecture:

1. **There is no server that renders.** osp-api returns JSON and never HTML; the host owns
   the HTML and only mounts our bundle (pages-split, hosting §2). An htmx results card would
   need a *new* HTML-rendering path in osp-api for tables and statistics, and a server-side
   chart renderer: our charts are Vega-Lite specs built in TypeScript from the JSON
   aggregates (`charts/spec.ts`, V-D1), so the fragment would either carry a `<svg>` drawn by
   Vega in the Node sidecar on every refresh for every viewer (heavy, and a second
   implementation of every chart) or carry JSON for the page's own JS to draw, which is
   polling (a) with an HTML envelope.
2. **Two owners of one DOM.** Svelte 5 renders the results view from state. htmx swaps DOM
   it does not own; the next Svelte update overwrites the swap, and htmx would re-process
   nodes Svelte created. Making them coexist means fencing off a region that Svelte never
   touches, which is exactly the region that holds the data Svelte already models (filters,
   splits, chart choices, captions, saved layouts, export).
3. **CSP.** The htmx core runs under `script-src 'self'` when bundled with our build and
   licence-checked (a BSD-family licence; `make licence-check` would confirm). Its
   `hx-on:*` attributes and `js:` values use
   `eval`-like execution; we would set `htmx.config.allowEval = false`, losing those.
   Workable, but it removes much of what makes htmx terse.
4. **The "every 5s" trigger is polling**, and the SSE extension is (b) with the same proxy
   requirements. htmx adds no transport we do not already have from `fetch` and
   `EventSource`; the part of htmx the owner likes (declarative "refresh every 5 s / on
   server push") is about 100 lines in `ResultsController` (section 5).
5. **Where htmx *would* fit:** a host's own pages around our mount, rendered by the host's
   templates (a lab dashboard listing surveys with response counts, a progress widget on a
   departmental intranet page). That is host code polling a tiny JSON or text endpoint of
   ours, and nothing in this plan stops it; the watermark endpoint (LV2) is the endpoint
   such a widget would call. Inside our bundle, it does not fit.

**Decision proposed: no htmx in the platform.** The owner's goal (a live page with no fuss)
is met by (a) now and (b) later, in code we already own.

### Comparison

| | (a) Poll watermark | (b) SSE | (c) WebSocket | (d) htmx |
|---|---|---|---|---|
| Works through the documented host proxy unchanged | yes | no (streaming proxy needed) | no (WS proxy + signing variant) | polling: yes; SSE ext: no |
| Strict CSP, no eval, no inline | yes | yes | yes (`connect-src 'self'` covers same-origin `wss:` in CSP 3) | with `allowEval=false` |
| New dependency | none | none | none | htmx (BSD) |
| Latency | 5–10 s | 1–2 s | 1–2 s | as the transport |
| Signed requests per viewer per hour | 360 at 10 s | 12 | 12 | as the transport |
| Fits Svelte-owned DOM | yes | yes | yes | no |
| Host work to enable | none | streaming passthrough, longer timeouts | ASGI host or proxy route | a server renderer we don't have |

## 3. Cost of refreshing aggregates

A refresh is one `results_query`. What it costs depends on what changed:

- **Nothing changed** (the common tick): the page never calls `results_query`; it polls the
  watermark only. Cost: one small SQL query.
- **Something changed, same query as another viewer:** cache hit (4 ms at 10 k) after the
  first viewer's computation. Today two viewers who ask in the same instant both compute:
  **LV2 adds single-flight** to `ResultsCache` (a per-key lock: the second waiter gets the
  first's result). The cache's `put` already evicts older watermarks of the survey, so memory
  does not grow with the response rate.
- **Something changed, different query per viewer** (different filters/splits): one scan per
  distinct query. 10 k responses: 0.4 s each; 100 k: 5 s each. With responses arriving faster
  than one scan, the page must not queue scans: it re-queries at most once per
  **`minRefreshMs`** (default 5 s) and never while a request is in flight; a change seen
  mid-flight schedules one more refresh after it completes (coalescing).
- **Server-side guard:** the watermark endpoint returns `pollAfterMs`, the interval the
  server wants (`OSP_LIVE_POLL_MS`, default 10 000; the operator raises it under load), and
  the existing per-actor rate limiting pattern (starts/resumes) is reused for the watermark
  route (burst 5, then 1/s).

### Incremental aggregation (not now)

`Acc` state per (variable, group) is additive: counts, state tallies, value lists. A delta
scan could keep the accumulators of a cached result and feed only responses newer than the
cached newest `submitted_at`, re-reading the boundary second by id. Deletions (withdrawals,
retention runs) break additivity, but the watermark's count exposes them: a count lower
than cached + new rows forces a full scan. Decrypting each new response still dominates, so
the saving is the re-decrypt of old rows. Worth building only when live viewing of surveys
above ~50 k responses is a real need (first view would then still be a full scan). Listed
as LV6, after the measurements LV3 will give us. Up to 10 k the full scan is 0.4 s and the
cache is per watermark anyway.

## 4. Privacy: live small *n*

V-D4 says owners and editors see exact counts because they can download the raw rows anyway.
Live refresh adds something the raw export does not: **a stream of single-response deltas
with timestamps**. The card that moved between two ticks shows one respondent's answers to
every question at once, and in a room (a lab session, a classroom, a conference demo) the
person who just pressed Submit is identifiable. On a projected screen the audience sees it
too, and the audience has no export right.

Rules proposed:

- **LV-D4 In the app (owner/editor, not presenting):** exact counts, as V-D4. The "N new
  responses" badge and a `results.read`-audited refresh are the same disclosure as pressing
  *Show results* twice, which they can already do.
- **LV-D5 Presentation mode live defaults to batched refresh with suppression.** The
  projected view refreshes when at least *k* new responses have arrived (default 5) *or*
  10 minutes have passed since the last refresh, whichever first, and draws with "hide
  counts below *k*" on (the V4 suppression, now applied on screen, with the hidden-cell
  look). The footer shows "n responses · updated 14:32", never the size of the last delta.
  The presenter can turn both off, deliberately, in the Present dialog; the choice is in the
  URL (`?live=batched|every|off`) so a link shared to a lab screen carries it.
- **LV-D6 The viewer role (plan V phase 3) gets live only batched and suppressed**, with no
  way to turn either off. Nothing to build now; recorded so LV3's code puts the switches
  behind one `livePolicy()` function from the start.
- Text answers (`results_text`) are never auto-refreshed: a new verbatim appearing on a
  screen is the clearest leak and the page is paginated anyway. The text card shows
  "new answers: Reload".

Needs human (product): whether LV-D5's *k* = 5 and 10 minutes are right, and whether the
owner wants exact live counts in presentation mode at all (my recommendation: keep the
batched default; a researcher presenting to their own lab can switch it off).

## 5. UX

- **Live toggle** in the summary bar next to *Show results* ("Live: off / on"), off by
  default, remembered for the page in the URL (`?live=…`) and, as a setting, in a saved
  layout (LV3 adds `live` to `LayoutSettings`, additive; older layouts open with it off).
  Needs human: whether a layout should carry it (recommended yes: "the lab screen layout").
- **Badge, not yank.** When the watermark changes while the researcher is working (filters
  open, a card's menu open, a text page open, an export dialog open, or any pointer/keyboard
  activity in the last 3 s), the page shows "3 new responses · Refresh" in the summary bar
  and does nothing else. When idle, or in presentation mode, it refreshes by itself. The
  manual *Show results* flow is unchanged.
- **Stable layout:** a card keeps its current height while its chart is re-embedded
  (`min-height` from the last render), so a refresh never scrolls the page. Changed cards get
  a short outline pulse; under `prefers-reduced-motion: reduce` there is no pulse, only the
  badge text, and the spinner stays off as now.
- **Screen readers:** one `aria-live="polite"` line, "Results updated: 142 responses",
  rate-limited to once per refresh; never per card.
- **Tab hidden:** polling stops on `visibilitychange`; on return it polls at once.
- **Errors:** a failed poll backs off (10 s → 20 s → 40 s, cap 2 min) and keeps the last
  results; a 401 ends live mode (the session banner already handles it); a 403 ends it
  with the access message.
- **Lab screen (presentation):** `?present=1&live=batched&layout=<id>`; footer with
  responses and time; the Present dialog offers **Fullscreen** (Fullscreen API, no CSP
  implication) and keeps the screen awake while presenting live (`navigator.wakeLock`,
  ignored where unsupported). The host session's lifetime is the host's: when it expires the
  page shows the sign-in banner and stops; documented in `docs/results.md`.

## 6. Audit volume

Today one `results.read` row per query (even cached) and one `responses.read` row per
uncached scan. With live on, rows would scale with new responses × viewers. Proposed:

- **The watermark endpoint is not audited.** It reads no answers (the store method already
  says so); it is a presence check like `GET /api/surveys/{id}`.
- **Automatic refreshes write `results.live`, not `results.read`, coalesced:** the first
  automatic refresh of a (actor, survey, queryHash) writes a `results.live` row with the
  query; later ones within 15 minutes with the same hash write nothing but bump an
  in-memory tally; the next row (after 15 minutes, or when the hash changes, or at process
  exit on a best-effort basis) carries `refreshes` and the first/last watermark. A manual
  *Show results* or *Refresh* click stays `results.read`. The request marks itself with
  `live: true` in the query body (a new optional field, left out of the query hash).
- `responses.read` stays as it is: it is written by the store per decrypt pass and is the
  honest record that answers were read.

Needs human (audit policy): coalescing turns "every read is a row" into "every *kind* of
read is a row per quarter hour". I recommend it; an auditor reading the log still sees who
watched which survey with which filters and how often.

## 7. Recommendation

**Build (a) now, as the only transport, with the privacy rules of section 4; add (b) as an
opt-in transport for hosts that can stream; no WebSockets; no htmx.** Phases:

| Phase | What | Effort |
|---|---|---|
| 1 | LV2 + LV3: watermark endpoint, single-flight cache, audit coalescing; live toggle, badge, auto-refresh when idle, a11y, docs | ~3 agent-days |
| 2 | LV4: presentation mode live (batched + suppressed defaults, footer, fullscreen, wake lock) | ~1.5 agent-days |
| 3 | LV5: SSE transport behind a host opt-in with automatic fallback to polling; hosting docs with nginx and ASGI examples; dev host streams | ~2 agent-days |
| later | LV6: incremental aggregation if 50 k+ live surveys appear; viewer-role live under LV-D6 when the viewer role lands | measure first |

Decisions proposed (to be confirmed by the owner, then copied into `results-viewer.md`'s
style of numbered decisions):

- **LV-D1 Transport:** watermark polling is the baseline every host gets; SSE is a host
  opt-in (`OspPageConfig.live = { transport: 'sse' }`), and the page falls back to polling
  on any stream failure. No WebSockets. No htmx.
- **LV-D2 The page re-queries only on a watermark change**, at most once per `minRefreshMs`,
  never concurrently; the server advertises `pollAfterMs`.
- **LV-D3 Cache single-flight**: identical concurrent queries compute once.
- **LV-D4–D6** as in section 4.
- **LV-D7 Audit:** watermark reads unaudited; automatic refreshes coalesced as
  `results.live` (section 6).
- **LV-D8 Text answers never auto-refresh.**

## 8. Proposed build tasks (for the lead to add to `tasks.md` / HubAI)

| id | what | depends on | acceptance criteria |
|---|---|---|---|
| LV2 | Live backend | V1 | `GET /api/surveys/{id}/results/watermark` (`survey.export`; `{watermark, responses, pollAfterMs}`; no audit; per-actor rate limit; 404/403 matrix); `ResultsQuery.live: bool` (excluded from the hash) → `results.live` coalesced audit per LV-D7 with tests for the 15-minute window and hash change; `ResultsCache` single-flight with a concurrency test; `OSP_LIVE_POLL_MS`; `make contract`; bench: 20 concurrent identical queries scan once |
| LV3 | Live results page | LV2, V2, V5 | `LivePoller` in `ResultsController` (visibility pause, backoff, idle detection, coalescing, `minRefreshMs`); *Live* toggle, "N new responses · Refresh" badge, auto-apply when idle; stable card heights, reduced-motion pulse off, one polite live region; `?live=` URL flag; `live` in `LayoutSettings` (additive); text card "new answers: Reload" (LV-D8); vitest on the poller with a fake clock; e2e: a response seeded mid-test appears without a click, badge path while a menu is open, 320 px + axe light/dark; `docs/results.md` |
| LV4 | Presentation mode live | LV3, V6 | Batched refresh (k new or 10 min) with on-screen suppression by default, overridable in the Present dialog and the URL; footer "n responses · updated hh:mm"; Fullscreen; wake lock; e2e incl. the suppressed look and that the delta size is never shown; docs |
| LV5 | SSE transport (opt-in) | LV2, LV3 | `GET /api/surveys/{id}/results/events` (async route, per-process per-survey watcher, heartbeat 15 s, max 5 min, `retry`); submit wakes the local watcher; `OspPageConfig.live.transport`; `EventSource` client with fallback to polling after error or 30 s without heartbeat; dev host streams the route; `docs/hosting.md` section (Django ASGI/in-process example, nginx `proxy_buffering off`, timeouts, "not for WSGI sync workers"); e2e through the dev host; load test: 200 subscribers, one DB poll per tick |
| LV6 | Incremental aggregation (if needed) | LV3 measurements | Delta scan from cached accumulators keyed by the cache key; full-scan fallback on count mismatch; equality tests against the full scan on every fixture; bench 100 k + 1 k new < 1 s |

## 9. Open questions (needs human)

1. LV-D5 defaults for presentation mode (k = 5, 10 minutes) and whether exact live counts
   on a projected screen should be allowed at all.
2. Audit coalescing (LV-D7) as policy.
3. Whether *Live* belongs in saved layouts.
4. Default poll interval: 10 s (recommended, because every poll is a signed request with a
   nonce write in production) or 5 s.

## Lead decisions (17 Oct 2026)

1. **Presentation mode defaults:** batched refresh at k = 5 new responses or 10 minutes, with on-screen small-cell suppression. Exact live counts on a projected screen are allowed only when an owner/editor switches suppression off in the Present dialog, which shows a warning; never via the URL alone.
2. **Audit coalescing (LV-D7) is policy:** one `results.live` row per actor + query hash per 15-minute window, plus a new row whenever the query changes.
3. **Live belongs in saved layouts** (additive `live` field), so a lab screen layout opens live.
4. **Default poll interval 10 s**, server-advertised (`pollAfterMs`), configurable by the deployment.
Build order: LV2 → LV3 → LV4 now; LV5 (SSE) and LV6 (incremental) only if measurements or hosts ask for them.

