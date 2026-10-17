# Open Survey Platform: one entry point for humans, agents, the Stop hook and CI.
#
#   make install        uv sync + pnpm install (from lockfiles)
#   make check          everything that must be green before a task is done
#   make contract       regenerate contract/openapi.json + the TS client
#
# `make check` steps are independent targets, so `make -j4 check` also works.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := check

# A VIRTUAL_ENV from the calling shell (e.g. the main checkout's) must not leak in.
unexport VIRTUAL_ENV

UV_RUN := uv run --locked
PNPM := pnpm

# Fixtures, goldens and generated files are UTF-8; Python on Windows would otherwise read
# them in the console code page (cp1252) and fail on the first non-ASCII character.
export PYTHONUTF8 := 1

CHECKS := py-test py-layers py-lint web-check web-test web-build contract-check licence-check harness-quick engine-test hooks-test sim-test

# `make check CHECK_SKIP="harness-quick"` leaves targets out: CI runs the browser suites as
# their own jobs (.github/workflows/ci.yml), and the Windows job skips what needs a POSIX
# shell. A finished task still needs the whole of `make check` green somewhere.
CHECK_SKIP ?=

.PHONY: install check $(CHECKS) contract

install:
	uv sync --locked
	$(PNPM) -C web install --frozen-lockfile

check: $(filter-out $(CHECK_SKIP),$(CHECKS))
	@echo "make check: all green$(if $(CHECK_SKIP), (without $(CHECK_SKIP)))"

py-test: sim-build engine-bundle
	$(UV_RUN) pytest

py-layers:
	$(UV_RUN) lint-imports

py-lint:
	$(UV_RUN) ruff check .
	$(UV_RUN) ruff format --check .

web-check:
	$(PNPM) -C web check

web-test:
	$(PNPM) -C web test

# Builder pages (Vite multi-page build): one JS entry per page + build/manifest.json; the
# check fails unless exactly the production pages are listed, their files exist and each
# entry exports mount (web/builder/scripts/check-build.mjs).
web-build:
	$(PNPM) -C web --filter @osp/builder exec vite build --logLevel warn
	$(PNPM) -C web --filter @osp/builder exec node scripts/check-build.mjs

# FastAPI app (osp-api) -> contract/openapi.json -> web/api-client/src/schema.d.ts
contract:
	$(UV_RUN) python scripts/contract.py generate

# Fails if either generated file differs from what the current app produces.
contract-check:
	$(UV_RUN) python scripts/contract.py check

licence-check:
	$(UV_RUN) python scripts/licence_check.py

# Fixture harness (task R4, web/harness): every fixture script played through the real
# participant app (web/runtime) in a real browser against osp-api on a fresh SQLite store
# (web/harness/server.py), compared with the expected traces. Pending traces are reported,
# never failed; known runtime bugs are expected failures (web/harness/src/known.ts).
# Report: .build/harness/report.md. Needs Playwright browsers:
#   pnpm -C web/harness exec playwright install chromium            (quick)
#   pnpm -C web/harness exec playwright install chromium webkit firefox   (full)
#
# harness-quick: fixtures touched since main's merge base (committed, staged, unstaged or
# untracked), or all of them if none; desktop Chromium only. Override with
# OSP_HARNESS_FIXTURES=06,25 (folder names or number prefixes).
HARNESS_BASE = $(shell git merge-base HEAD main 2>/dev/null || git merge-base HEAD origin/main 2>/dev/null)
HARNESS_TOUCHED = $(shell { $(if $(HARNESS_BASE),git diff --name-only $(HARNESS_BASE) -- fixtures;) \
	git ls-files --others --exclude-standard -- fixtures; } 2>/dev/null \
	| sed -n 's|^fixtures/\([0-9][0-9]-[^/]*\)/.*|\1|p' | sort -u | paste -sd, -)

.PHONY: harness-full
# A free port per run unless OSP_HARNESS_PORT is set, so parallel worktrees never collide.
HARNESS_FREE_PORT = $$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')

harness-quick:
	@fx="$${OSP_HARNESS_FIXTURES-$(HARNESS_TOUCHED)}"; \
	echo "harness-quick: fixtures: $${fx:-all}"; \
	OSP_HARNESS_PORT="$${OSP_HARNESS_PORT:-$(HARNESS_FREE_PORT)}" OSP_HARNESS_FIXTURES="$$fx" \
		$(PNPM) -C web/harness exec playwright test --project=desktop-chromium

# Every fixture × every device project (iPhone SE/WebKit, Pixel 7/Chromium, desktop Firefox,
# desktop Chromium). engine-test first, so the report can tell runtime divergences (engine
# passes, app fails) from fixture or engine failures.
harness-full: engine-test
	OSP_HARNESS_PORT="$${OSP_HARNESS_PORT:-$(HARNESS_FREE_PORT)}" OSP_HARNESS_FIXTURES= \
		$(PNPM) -C web/harness exec playwright test $(HARNESS_ARGS)

# osp-store tests against a throwaway Postgres container (task C9). Needs Docker
# (Colima); skips with a message if Docker isn't running. `make check` runs the
# same tests on SQLite only. Or set OSP_TEST_POSTGRES_URL to use an existing server.
.PHONY: test-postgres
test-postgres:
	OSP_TEST_POSTGRES=1 $(UV_RUN) pytest python/osp-store -rs

# Builder end-to-end (Playwright): layout, keyboard, axe-core in both themes, visual
# snapshots. Not part of `make check` (needs Playwright browsers: `pnpm -C web/builder exec
# playwright install chromium`). Update snapshots: `make web-e2e E2E_ARGS=--update-snapshots`.
.PHONY: web-e2e
web-e2e:
	$(PNPM) -C web --filter @osp/builder exec playwright test $(E2E_ARGS)

# Participant engine (task R1). Python compiles every fixture survey to a runtime plan and
# writes the Python/TS parity vectors into web/engine/.build/ (gitignored); vitest then runs
# every fixture script, the parity checks and the property tests. Report of realised
# "<engine>" values: web/engine/.build/fixture-report.json.
.PHONY: engine-fixtures engine-test engine-size
engine-fixtures:
	$(UV_RUN) python web/engine/scripts/build_fixtures.py

engine-test: engine-fixtures
	$(PNPM) -C web/engine exec vitest run

# Engine records (task M2/M3 inputs): every fixture script played through web/engine,
# `result(state)` written to python/osp-targets/tests/data/records/ (committed, so py-test
# needs no node). python/osp-targets/tests/test_records.py fails when a scripted fixture has
# no records or a record's planChecksum is not the current plan's. Then regenerate the
# goldens: OSP_UPDATE_GOLDEN=1 uv run pytest python/osp-targets/tests/test_data_export.py
.PHONY: engine-records
engine-records: engine-fixtures
	node --experimental-transform-types --no-warnings=ExperimentalWarning \
		python/osp-targets/tests/data/dump_records.ts

# Simulator (task M1, web/engine-sim). `sim-build` bundles dist/cli.js, the Node sidecar
# osp_runtime.sim_sidecar runs (py-test needs it); `sim-test` runs the simulator's vitest
# suite on the fixture plans (built by engine-fixtures).
.PHONY: sim-build sim-test engine-bundle
sim-build:
	$(PNPM) -C web/engine-sim exec vite build --logLevel warn

sim-test: engine-fixtures
	$(PNPM) -C web/engine-sim exec vitest run

# Engine bundle (task M3): web/engine/dist/engine.js, the whole engine (with big.js) as one
# ES module. The reproducibility package ships it with replay.mjs (osp_app.repro reads it;
# OSP_ENGINE_BUNDLE overrides the path); py-test needs it for the replay.mjs tests.
engine-bundle:
	$(PNPM) -C web/engine exec vite build --config bundle.config.ts --logLevel warn

# Engine bundle size (minified + gzip), informational: the budget is a target, not a gate.
engine-size:
	$(PNPM) -C web/engine exec node scripts/size.mjs

# Participant app (task R3) end to end: builds web/runtime, starts osp-api on a fresh SQLite
# store (web/runtime/e2e/server.py, uvicorn via `uv run --with`), publishes the test surveys
# and runs Playwright on iPhone SE, Pixel 7 and desktop. Not part of `make check` (needs
# Playwright browsers: `pnpm -C web/runtime exec playwright install chromium webkit`).
.PHONY: runtime-e2e runtime-size
runtime-e2e:
	$(PNPM) -C web/runtime exec playwright test $(E2E_ARGS)

# Runtime bundle size (gzip), informational: target <= 90 KB.
runtime-size:
	$(PNPM) -C web/runtime exec vite build --logLevel warn
	$(PNPM) -C web/runtime exec node scripts/size.mjs

# Researcher hooks (task R7, runtime-design.md §7a). `hooks-test` (in `make check`): manifest,
# action validation and engine integration in node. `hooks-e2e`: the adversarial gate in real
# Chromium and WebKit (egress, forged messages, floods, loops, allocations, stale results,
# refresh, duplicate submit, undeclared redirects/parent messages, escaped hook text). Needs
# Playwright browsers: `pnpm -C web/hooks-sandbox exec playwright install chromium webkit`.
.PHONY: hooks-test hooks-e2e
hooks-test:
	$(PNPM) -C web/hooks-sandbox exec vitest run

hooks-e2e:
	$(PNPM) -C web/hooks-sandbox exec playwright test $(E2E_ARGS)

# LimeSurvey .lss export (task M4): import and activate every fixture in a real LimeSurvey
# 6.17 over RemoteControl, using spikes/spike-1's docker compose (pinned images, local-only
# credentials). Not part of `make check`; skips cleanly without Docker. Leaves containers
# it started running with OSP_LSS_IMPORT_KEEP=1.
.PHONY: lss-import-check
lss-import-check:
	OSP_LSS_IMPORT=1 $(UV_RUN) pytest python/osp-targets/tests/test_lss_import.py -rs

# Local dev: `make dev` runs osp-api (SQLite in .data/, port 8000) and the builder dev server
# (5173, which serves each builder page at its usual URL with a dev config and proxies /api
# to the API, so no CORS; web/builder/dev-host/) together; Ctrl+C stops both. No sign-in:
# OSP_IDENTITY=dev makes every request the dev researcher, owner of dev-lab (plan P; refused
# off loopback or outside OSP_ENV=dev). The first run makes dev-only keys and three seeded
# surveys, all in .data/ (gitignored); every run prints the URLs. The participant app's dev server (5174, base
# /r/, proxying /api too) starts as well; its links are /r/?s=<slug>. `make dev-reset` wipes .data/. Dev only: never point this at real data.
# It builds the engine bundle (make engine-bundle) first, so repro packages include replay.mjs.
DEV_DATA := .data
DEV_API_PORT := 8000
DEV_BUILDER_PORT := 5173
DEV_RUNTIME_PORT := 5174
DEV_FIXTURES := fixtures/01-all-types fixtures/13-randomiser-blocks fixtures/18-multi-language
DEV_ENV := OSP_ENV=dev OSP_IDENTITY=dev OSP_DATA_DIR=$(DEV_DATA) OSP_DATABASE_URL=sqlite:///$(DEV_DATA)/osp.db
DEV_PROXY := OSP_API_URL=http://127.0.0.1:$(DEV_API_PORT)

.PHONY: dev dev-reset
# engine-bundle first: the reproducibility package's replay.mjs needs web/engine/dist/engine.js.
dev: engine-bundle
	@$(DEV_ENV) $(UV_RUN) osp-api init >/dev/null
	@if [ -z "$${OSP_STORE_KEYS:-}" ]; then set -a; . $(DEV_DATA)/dev-keys.env; set +a; fi; \
	runtime=""; if [ -f web/runtime/package.json ]; then \
		runtime="http://localhost:$(DEV_RUNTIME_PORT)/r/?s={slug}"; fi; \
	$(DEV_ENV) $(UV_RUN) osp-cli dev-seed $(DEV_FIXTURES) \
		--builder-url http://localhost:$(DEV_BUILDER_PORT) \
		--api-url http://localhost:$(DEV_API_PORT) --participant-link "$$runtime"; \
	pids=""; \
	stop() { trap - INT TERM EXIT; if [ -n "$$pids" ]; then kill $$pids 2>/dev/null || true; fi; \
		wait 2>/dev/null || true; }; \
	alive() { for p in $$pids; do kill -0 $$p 2>/dev/null || return 1; done; }; \
	trap 'stop; exit 130' INT TERM; trap stop EXIT; \
	$(DEV_ENV) OSP_PARTICIPANT_URL_TEMPLATE="http://localhost:$(DEV_RUNTIME_PORT)/r/?s={slug}" \
		$(UV_RUN) osp-api serve --port $(DEV_API_PORT) & pids="$$!"; \
	(cd web/builder && exec env $(DEV_PROXY) node_modules/.bin/vite dev \
		--port $(DEV_BUILDER_PORT) --strictPort) & pids="$$pids $$!"; \
	if [ -n "$$runtime" ]; then \
		(cd web/runtime && exec env $(DEV_PROXY) node_modules/.bin/vite dev \
			--port $(DEV_RUNTIME_PORT) --strictPort) & pids="$$pids $$!"; \
	fi; \
	while alive; do sleep 1; done; \
	echo "make dev: a server stopped, so stopping the others"; exit 1

dev-reset:
	rm -rf $(DEV_DATA)
	@echo "dev-reset: removed $(DEV_DATA)/; the next make dev starts fresh"
