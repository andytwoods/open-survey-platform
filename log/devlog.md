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

## 2026-10-17 — P2: builder as separate pages, no sign-in UI (planning/pages-split.md)

- Landed: Vite multi-page build replaces SvelteKit (7 page entries + 8 dev-only entries, shared chunks, `build/manifest.json`); `OspPageConfig` validated at run time (`src/lib/host/config.ts`); one links module with save-queue wait (10 s, then ask) and `beforeunload`; api client takes `apiBase` + host CSRF scheme; login/TOTP/logout, `RequireAuth`, Sign out deleted; `GET /api/me` for header name and lab; 401 banner (reload once, never a loop; writes stop, queue kept), 403 banner; preview frame talks by checked `postMessage` only.
- Numbers: web vitest 539 (was 493); builder e2e 133 (was 126; new `host.spec.ts`); `make check` green; `scripts/check-build.mjs` gates the manifest in `make web-build`.
- Open: e2e sign-in (`e2e/fixtures.ts` `signIn`/`writeHeaders`) and the dev config's CSRF (`X-CSRF-Token` / `__Host-osp_csrf`, `dev-host/pages.ts`) still target cookie sessions; swap when P1 lands. Until then `make dev` has no way to sign in.
