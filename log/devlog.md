## 2026-10-16 — Spike 1 (LimeSurvey end to end), stopped early

- Landed `spikes/spike-1/`: pinned compose (LimeSurvey 6.17.18 apache + MariaDB 11.4.13, native arm64), hand-written `.lss`, httpx RC2 client, 7 Playwright participants, one-command runner (`make -C spikes/spike-1 run`). Full run: 53 s.
- Result: go-with-limits. Deploy/export/version via API work. Order not recorded (seed only). URL prefill is overwritten on re-entry. `rand()` equations re-evaluate. Irrelevant answers cleared to NULL. `{q}` pipes codes, not labels.
- Open: checks.py is a stub; last .lss edits (latch, JS order capture) untested; 3 "Needs human" items in FINDINGS.md. Stopped because the runtime moved to Enketo.

## 2026-10-16 — Enketo spike (participant runtime)

- Landed `spikes/spike-enketo/`: XLSForm (md) → pyxform 4.5.0 → enketo-transformer 4.2.0 (browser build in headless WebKit) → enketo-core 9.0.1 on a stdlib Python server; 11 Playwright participants + 1,000-seed E5 + axe + license-checker; `make -C spikes/spike-enketo run` (~48 s clean).
- Result: go-with-limits. Standalone render, submit capture, server injection of cond/seed, resume (ours) all work. Python `randomize` matches Enketo on 900/1,000 seeds (all integer seeds; Enketo throws on decimal/string seeds, against the spec). Question/block order lowered via server order + DOM reorder.
- Differs from semantics: non-relevant values cleared only at final submit (lowered: `clearNonRelevant()` on page flip); `${choice}` pipes codes (lowered: `jr:choice-name`); whitespace-only text → empty and pruned output trims (needs human).
- Open: transformer Node build needs native libxslt (fails on Node 24); Chromium 156 injects an XSLT deprecation banner; npm releases lag the monorepo; axe flags Enketo's `role="page"`/tabindex; 6 "Needs human" items in FINDINGS.md.

## 2026-10-16 — Phase 1 scaffold (S1–S6), branch agent/scaffold

- Landed: uv workspace (12 empty L0–L6 packages, root pyproject) + pnpm workspace (SvelteKit 3 adapter-static builder, api-client, ui-components); import-linter layers + no-I/O contracts; dependency-cruiser boundaries; licence gate (Python + JS, `licence-policy.toml`); `make check`; CI workflow; Stop hook; FastAPI `osp-api` (`/api/health`, `/api/version`) → `contract/openapi.json` → openapi-typescript client + openapi-fetch wrapper; `AGENTS.md` at root.
- Numbers: `make check` 19 s from a clean `git clean -xdf` + `make install` (2 s from cache), ~15 s warm; 54 pytest + 11 vitest; 309 deps licence-checked (39 Python, 270 JS), 0 violations, MPL-2.0 only in lightningcss (dev).
- Each guard has a test that injects a violation in a temp copy: upward/sibling/I/O imports, web boundaries (incl. markup-only Svelte imports), synthetic GPL dep, stale contract, Stop hook (block, skip-when-unchanged, 3-block loop cap).
- Open: CI never run on GitHub (no remote); `harness-quick` is a stub; 4 "Needs human" items in tasks.md (Kit 3 peer warnings, certifi MPL-2.0 at runtime, allowlist gaps, SubagentStop).

## 2026-10-17 — P1: host-owned identity in osp-api (plan P back end)

- Landed: `IdentityProvider` port (`osp_api/identity.py`): `TrustedHeaders` (HMAC-SHA256 over method, path, sorted query, body SHA-256, user, roles, name, timestamp, nonce; keyring `OSP_IDENTITY_KEYS`, 60 s skew, 120 s nonce LRU), `InProcess`, `Dev` (OSP_ENV=dev + loopback only); `osp_api/signing.py` (`sign_identity_headers`, one canonical form for host and server). `osp-api serve` picks `OSP_IDENTITY=trusted-headers|dev`, binds 127.0.0.1. `/api/auth/*`, cookies, CSRF token, passwords, TOTP, sessions and account creation removed; `principals` table + `audit_log.actor_name` snapshot; migration `0007_host_identity` (up/down tested on SQLite and Postgres). Labs created on first sight (`OSP_AUTO_CREATE_LABS`, `osp-cli lab create`). `dev-seed` needs no password.
- Numbers: make check green; 2511 pytest passed (SQLite), osp-store on Postgres 326 passed; 43 provider tests, builder-security matrix re-run under signed identities.
- Open: builder still has the login page / RequireAuth (P2); `web/builder/src/lib/auth.svelte.ts` is a stub reading `/api/me`; builder e2e specs still log in via UI; `docs/hosting.md` is P4; nonce cache is per process.

## 2026-10-17 — P2: builder as separate pages, no sign-in UI (planning/pages-split.md)

- Landed: Vite multi-page build replaces SvelteKit (7 page entries + 8 dev-only entries, shared chunks, `build/manifest.json`); `OspPageConfig` validated at run time (`src/lib/host/config.ts`); one links module with save-queue wait (10 s, then ask) and `beforeunload`; api client takes `apiBase` + host CSRF scheme; login/TOTP/logout, `RequireAuth`, Sign out deleted; `GET /api/me` for header name and lab; 401 banner (reload once, never a loop; writes stop, queue kept), 403 banner; preview frame talks by checked `postMessage` only.
- Numbers: web vitest 539 (was 493); builder e2e 133 (was 126; new `host.spec.ts`); `make check` green; `scripts/check-build.mjs` gates the manifest in `make web-build`.
- Merged with P1: e2e sign-in is a no-op (Dev identity) in `e2e/fixtures.ts`; the dev config sends no CSRF (P1 has none; Origin check + JSON bodies stay). P1's `auth.svelte.ts` stub deleted.
- Open: `docs/hosting.md` (P4) should copy the config/manifest section of `web/builder/README.md`.
- Seen twice under the Stop hook: `harness-quick` flakes about 1 run in 5 (`apiRequestContext: Target page, context or browser has been closed`, a different fixture each time: 26 trailing-zeros, 16 assign/control; web/harness/src/player.ts `storedResponse`). Passes on rerun (3/3); not touched by P2.

## 2026-10-17 — P4: docs/hosting.md (planning/pages-split.md)

- Landed: `docs/hosting.md` (pieces and env vars, serving a page from `manifest.json`, `OspPageConfig` copied from `config.ts`, safe JSON / `json_script`, signed proxy + key rotation, `InProcess`, participant routes, 10-item checklist, minimal Django views/urls/template). Linked from `README.md`, `python/osp-api/README.md`, `web/builder/README.md` (also fixed its `<` escape text). Top-level README no longer mentions a dev password.
- Numbers: `tests/test_hosting_example.py` 6 tests: the doc's proxy over `TestClient` with real `TrustedHeaders` (create + list, forged `X-OSP-*` stripped, unsigned direct call 401, host 401/CSRF before forwarding, signed query, forwarded Origin with `OSP_ALLOWED_ORIGINS`).
- Open: participant start/resume rate limits key on the client address and osp-api reads no forwarded address, so behind a host every participant shares one budget; the participant app hardcodes `/api` (no `apiBase`); osp-api's Origin check sees `http://127.0.0.1:8000`, so it only adds defence if the host forwards `Origin` and sets `OSP_ALLOWED_ORIGINS`.

## 2026-10-17 — P5: deployment fixes behind a host (planning/pages-split.md D13–D16)

- Landed: `OSP_TRUSTED_PROXIES` (X-Forwarded-For only from trusted peers, right-most untrusted hop, IPv6 keyed per /64; `osp_api/client_address.py`) for participant rate limits; `OSP_PUBLIC_ORIGINS` (Origin check without CORS) separate from `OSP_ALLOWED_ORIGINS` (CORS, now also passes `Sec-Fetch-Site: cross-site`); participant app `data-api-base` on `#app` (same-origin only, default `/api`, `planUrl` mapped); shared nonce store `OSP_NONCE_STORE=memory|database` (default `database` in production) on new table `identity_nonces` (migration 0008, `osp_store.NonceLedger`). `docs/hosting.md` caveats removed; the tested proxy now forwards `Origin`/`Sec-Fetch-Site`.
- Numbers: pytest 2550 passed; new `test_deployment.py` 22, `test_store_nonces.py` 7 tests (SQLite; Postgres via `make test-postgres`: 346 passed); `test_hosting_example.py` 7; runtime vitest 43 (+12, `api-base.test.ts`); runtime e2e 13 on desktop (+1: `/hosted/` page with `data-api-base` behind a prefix rewrite in `e2e/server.py`).
- Open: the participant app still assumes it is served at `/s/{slug}` or `?s=` on the origin root (resume link uses `/s/`); harness-quick "Target page … closed" flake seen once (passed on rerun).
