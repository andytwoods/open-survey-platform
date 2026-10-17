# Separate pages, host-owned sign-in (plan P, v2)

Status: **approved** (the owner asked for it; GPT, Gemini and Qwen all "approve with
changes"; their changes are folded in as §Decisions, which override the draft text below).

## Goal

The project stops dealing with researcher sign-in. A **host backend** (not this project:
a university's Django or Rails app, a reverse proxy with single sign-on, etc.) owns
accounts, passwords, two-factor and sessions. This project ships:

1. **Builder pages as separate JS bundles.** Each page (survey list, editor, flow,
   settings, survey appearance, lab theme library, preview frame) is its own entry with
   its own URL. The host serves each page at whatever URL it likes, behind its own login.
2. **The participant app** (`web/runtime`), unchanged. Participants never sign in.
3. **The survey backend logic** (spec, validation, publish, quotas, assignment, saving,
   encryption, exports) as the Python library plus `osp-api`, which trusts the host for
   *who* the researcher is.

Today the builder is one SvelteKit SPA with a login page, `RequireAuth`, password + TOTP,
and `osp-api` owns sessions (`__Host-osp_session` cookie, CSRF token derived from it).

## Front end

### F1. One page = one entry
- Replace the SvelteKit app with a **Vite multi-page build** in `web/builder`. One entry per
  page: `list`, `editor`, `flow`, `settings`, `appearance` (survey), `themes` (lab
  library), `preview-frame`. Dev-only gallery pages (`dev/*`) become dev-only entries.
- Each entry exports `mount(el, config)` and also auto-mounts from a
  `<script type="application/json" id="osp-config">` tag, so a host page is just:
  ```html
  <div id="osp"></div>
  <script type="application/json" id="osp-config">{"apiBase": "/osp/api", "surveyId": "…", "links": {…}}</script>
  <script type="module" src="/static/osp/editor.js"></script>
  ```
- Shared code (Svelte runtime, ui-components, sync, engine) goes into shared chunks, so the
  pages don't each carry their own copy. A `manifest.json` maps page names to their JS and
  CSS files so a host can write the tags.
- Same output works as plain static files: no Node at run time.

### F2. Host config contract (`OspPageConfig`, typed, versioned)
```ts
interface OspPageConfig {
  version: 1;
  apiBase: string;                 // where the osp API lives, e.g. "/osp/api"
  surveyId?: string;               // survey-scoped pages
  tenantId?: string;               // which lab, if the user is in several
  links: {                         // URL templates; {id} is replaced
    list: string; editor: string; flow: string; settings: string;
    appearance: string; themes: string; previewFrame: string;
  };
  csrf?: { header: string; token?: string; cookie?: string }; // host's CSRF scheme
  onUnauthenticated?: { redirect: string } | 'reload';        // after a 401
  user?: { displayName?: string };  // shown in the header, if the host wants
}
```
- All navigation goes through one `links` module (today: `Shell.svelte`, `SurveyList`,
  `SurveyEditor`, `PreviewPanel`, `RequireAuth` use `$app/navigation` / `resolve`).
  Moving between pages is a normal full page load.
- Unsaved edits: the editor already flushes on `pagehide`; navigation waits for the save
  queue to drain (as today) before `location.assign`.

### F3. No sign-in UI
- Delete `routes/login`, `RequireAuth`, the login/TOTP/logout parts of `auth.svelte.ts`,
  and the "Sign out" button (the host puts its own header/sign-out around the page).
- A 401 means "the host session ended": follow `onUnauthenticated` (default: reload, so
  the host's own login kicks in).
- CSRF: the pages send whatever the host's scheme asks for (`csrf.header` with a token
  given in config or read from a named cookie). No CSRF of our own.

## Back end

### B1. Pluggable identity in `osp-api`
- New port `IdentityProvider`: `identify(request) -> Actor | None` (Actor is already a
  plain dataclass: `user_id` + `{tenant_id: role}`). `create_app(..., identity=...)`.
- Shipped providers:
  1. **TrustedHeaders** (for a host or reverse proxy in front of osp-api): the host
     authenticates the request, then forwards it with `X-OSP-User`, `X-OSP-Roles`
     (`tenant:role,…`), `X-OSP-Timestamp` and `X-OSP-Signature` = HMAC-SHA256 over those
     plus method and path with a shared secret `OSP_IDENTITY_SECRET`. Max clock skew 60 s.
     Unsigned or stale → 401. The host does CSRF before forwarding.
  2. **InProcess**: a Python host that mounts the ASGI app passes a callable
     `identify(request)` (e.g. reading the Django user). No headers, no secret.
  3. **Dev** (only when `OSP_ENV=dev`, refuses to start otherwise): everyone is the dev
     researcher, owner of the dev lab. `make dev` uses it, so no login at all.
- Labs (tenants) are created on first sight of a tenant id (just-in-time); roles come
  from the host on every request, so the host is the single source of truth.

### B2. Remove our own accounts
- Delete `osp_api/routes/auth.py`, the session cookies/CSRF in `routes/common.py`, and in
  `osp-app` the password policy, common-password list, TOTP, session repo and account
  creation. Migration 0007 drops `user_mfa`, `auth_sessions` and the password columns;
  `users`/`memberships` go too if nothing else needs them (audit log keeps the host's
  user id as a string).
- `osp-cli dev-seed` seeds surveys for the dev lab and prints links, no password.
- The OpenAPI contract loses `/api/auth/*`; `/api/me` (who the host says you are, your
  labs) stays for the pages.

### B3. Participant side
Unchanged: public, bearer resume tokens, `OSP_PARTICIPANT_URL_TEMPLATE` for links.

## Reference host and tests
- `make dev`: Vite dev server serves the pages at the current URLs (`/`, `/surveys/{id}`,
  `/surveys/{id}/flow`, …) with a dev config; API with the Dev provider. No login.
- Builder e2e (126 tests): drop the login steps; same URLs, so specs barely change. Add
  tests: each page mounts from a config tag; links follow the templates; a 401 follows
  `onUnauthenticated`; a host CSRF header is sent on writes.
- API tests: TrustedHeaders (good, unsigned, stale, wrong path, tampered roles),
  InProcess, Dev refuses outside dev; every builder route still enforces roles.
- `docs/hosting.md`: how a host serves the pages and forwards identity, with a minimal
  Django example (a view per page rendering the config tag, and a proxy view that signs
  headers). A full Django adapter package is a later, separate task.

## Tasks (agents, worktrees)
- **P1** backend identity port + providers + remove accounts + migration 0007 + dev-seed.
- **P2** front-end config + links module + remove sign-in UI + 401/CSRF handling.
- **P3** Vite multi-page build, entries, manifest, dev host, e2e updates (after P2).
- **P4** docs/hosting.md + contract regeneration + licence check (after P1–P3).

## Decisions (after review, 17 Oct 2026)

All three reviewers: Vite MPA, one package, remove our accounts. Folded in:

- **D1 Build.** Vite multi-page app replaces SvelteKit entirely (dev and prod use one
  build). One package (`@osp/builder`), per-page entries, shared chunks, `manifest.json`
  (page -> js + css, hashed). Entries, chunks and the config contract version together.
- **D2 Identity = signed headers (HMAC), v1.** Signature covers a canonical string:
  method, path + sorted query, SHA-256 of the body, user id, roles, display name,
  timestamp, nonce (`X-OSP-Nonce`, 128-bit). Skew 60 s; nonces remembered for 120 s
  (in-memory LRU, one process; documented limit). Keyring `OSP_IDENTITY_KEYS=kid:secret,…`
  with `X-OSP-Key-Id`, so a key rotates without downtime. Constant-time compare. Role
  names must be one of our roles; tenant/user ids are opaque strings, length-capped.
  JWT/JWKS (asymmetric, several hosts) is a later option (P5), not now.
- **D3 Direct exposure.** `osp-api serve` binds 127.0.0.1 by default; docs say the host
  must strip any incoming `X-OSP-*` headers and be the only route to the API. Without a
  valid signature a request is 401, whatever headers it carries.
- **D4 CSRF.** The host checks CSRF before signing/forwarding (TrustedHeaders) or before
  calling in (InProcess). osp-api keeps its Origin / Sec-Fetch-Site check on unsafe
  requests as defence in depth, and requires `application/json` bodies.
- **D5 Accounts.** Remove passwords, TOTP, sessions, memberships, account creation.
  Keep a minimal `principals` table (host user id, last display name, first/last seen),
  upserted on each request, for audit display; audit rows also snapshot the display name.
  Migration 0007 drops `user_mfa`, `auth_sessions`, `memberships` and password columns
  (no production data exists yet; downgrade recreates empty tables).
- **D6 Labs.** Tenants are created on first sight (`OSP_AUTO_CREATE_LABS`, default on:
  the signature already proves the host sent it); off means `osp-cli lab create` first.
  `tenantId`/`surveyId` from page config are selectors only; every route still checks
  the resource's tenant against the actor's roles.
- **D7 Config safety.** Pages validate the config at run time (types, lengths). `apiBase`
  and every link must be same-origin (relative paths, or the page's own origin) unless
  listed in `allowedOrigins` in the config. Docs give the safe JSON embedding rule
  (escape `<` as `\u003c`) and a Django `json_script` example.
- **D8 Navigation.** Page changes are full loads. Before leaving, the page waits for the
  save queue to be acknowledged (max 10 s, then asks); `beforeunload` warns while edits
  are unsaved. Undo history is per page and resets on navigation (documented).
- **D9 Session ended.** 401: stop sending writes, keep the pending edits in the save
  queue, show a banner "Your session ended. Sign in again" linking to
  `onUnauthenticated.redirect` (with `?next=`) or reloading once; never a reload loop.
  403: a "you don't have access to this lab" message, distinct from 401.
- **D10 Preview.** The preview frame keeps its sandboxed iframe; messages are checked for
  origin, source window and schema. It never gets the API base or CSRF token.
- **D11 Cross-origin.** Default and documented setup is same-origin (the host proxies
  `/osp/api`). Cross-origin API is opt-in: `OSP_ALLOWED_ORIGINS` (exact origins,
  credentials allowed, no wildcard). Docs cover CSP (`script-src 'self'`) and
  `frame-ancestors` for the preview frame.
- **D12 Dev.** The Dev provider only starts with `OSP_ENV=dev` and a 127.0.0.1 bind;
  otherwise osp-api refuses to start.

## Decisions (deployment, P5, 17 Oct 2026)

Four gaps found while writing `docs/hosting.md` (P4). These override D2's "in-memory, one
process" nonce cache and refine D4.

- **D13 Participant address behind a proxy.** `OSP_TRUSTED_PROXIES` (comma-separated IPs
  or CIDRs, default empty). Only when the direct peer is in that list does osp-api read
  `X-Forwarded-For` (all header lines, in order), walking from the right past trusted hops
  and taking the first untrusted one; the client-written left part is never used, and a
  malformed hop stops the walk at the last address a trusted proxy vouched for (fail to
  the shared, not the spoofed, key). Chains are cut at 32 hops. IPv4-mapped IPv6 is treated
  as IPv4. The rate-limit key is the IPv4 address or the IPv6 **/64** (a host picks any
  address in its /64, so per-address keys limit nothing). Still memory-only, never stored
  or logged; uvicorn's `proxy_headers` stays off, so nothing else reads forwarded headers.
  Code: `osp_api/client_address.py`.
- **D14 Origin check behind a proxy.** Two settings, two meanings. `OSP_PUBLIC_ORIGINS`:
  the host's public origin(s), accepted by the unsafe-request Origin check as same-site;
  **no CORS**. `OSP_ALLOWED_ORIGINS`: the cross-origin CORS opt-in (D11), also accepted, and
  the only origins that pass with `Sec-Fetch-Site: cross-site` (before, a CORS-allowed
  origin on another site was refused by the Sec-Fetch-Site check). Otherwise the `Origin`
  must be osp-api's own scheme+Host or a public origin, and `Sec-Fetch-Site` not
  `cross-site`; `Origin: null` is refused; no `Origin` checks `Sec-Fetch-Site` only. Unset:
  as before. The documented proxy forwards `Origin` and `Sec-Fetch-Site`, so the check is
  live behind a host. In-process mounts behind TLS termination pass `public_origins=` to
  `create_app` instead of trusting a forwarded scheme. Both lists are exact origins (no
  wildcard, no path), checked at start-up and in `create_app`.
- **D15 Participant API prefix.** The participant app reads `data-api-base` on its mount
  (`<div id="app" data-api-base="/osp/api">`), default `/api`. A data attribute rather than
  a config tag: the host serves one static `index.html` for every `/s/{slug}` and needs one
  attribute edit, with no JSON to escape. Same-origin only (a path, or a URL on the page's
  origin; no query, fragment or credentials; max 512 chars); there is no cross-origin
  allowlist because the participant CSP is `connect-src 'self'` and participants never need
  one. A bad value is a visible boot error, never a silent fallback. Server-returned URLs
  under `/api/` (`planUrl`) are mapped onto the prefix by the client, so the server needs
  no knowledge of the host's prefix. `make dev` and the harness keep the default.
- **D16 Shared nonce store.** `OSP_NONCE_STORE=memory|database`. `database` keeps each
  nonce in `identity_nonces` (migration 0008: nonce PK, `expires_at` indexed) for 120 s:
  one transaction deletes an expired row for the same nonce, then `INSERT ... ON CONFLICT
  DO NOTHING` (SQLite and Postgres), so exactly one of concurrent claims wins; expired rows
  are purged at most once a minute per worker. A database error refuses the request (fail
  closed). Default: **`database` with `OSP_ENV=production`, `memory` in dev**. Production
  always has a real database (it is required) and may run several workers, and a builder
  request costs one extra small write, which is negligible for researcher traffic; dev is
  one process on SQLite, and tests construct `TrustedHeaders` directly with an in-memory
  cache. `memory` stays available for single-process deployments. Code:
  `osp_store/nonces.py` (`NonceLedger`), `osp_api/identity.py` (`DatabaseNonces`).

## Review log
- GPT: approve with changes (canonical signing, replay, key rotation; audit identity;
  config injection; preview isolation; 401 loops; migration care).
- Gemini: approve with changes (nonce; bind localhost; safe JSON; JIT tenant flag;
  beforeunload; manifest helper; frame-ancestors). Preferred HMAC + JWT both.
- Qwen: approve with changes (prefers JWT; nonce; config validation; sessionStorage
  drafts; display-name snapshot in audit rows).

## Open questions for review (answered in §Decisions)
1. Vite MPA replacing SvelteKit, or keep SvelteKit only as a dev host and add a separate
   library build of page entries?
2. One package with per-page entries and shared chunks, or one npm package per page?
3. TrustedHeaders with HMAC: enough, or prefer a signed JWT from the host (JWKS)?
4. Remove our accounts entirely (users, memberships, audit actor) or keep a minimal
   users table for audit display names?
5. Anything that breaks when moving between pages is a full page load (undo history,
   the preview iframe, unsaved edits)?
6. Anything missing for a host to embed safely (CSP, CORS if the API is on another
   origin, cookie scope)?
