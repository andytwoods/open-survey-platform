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

CHECKS := py-test py-layers py-lint web-check web-test web-build contract-check licence-check harness-quick engine-test

.PHONY: install check $(CHECKS) contract

install:
	uv sync --locked
	$(PNPM) -C web install --frozen-lockfile

check: $(CHECKS)
	@echo "make check: all green"

py-test:
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

web-build:
	$(PNPM) -C web --filter @osp/builder exec vite build --logLevel warn
	@test -f web/builder/build/index.html && echo "web-build: static site in web/builder/build"

# FastAPI app (osp-api) -> contract/openapi.json -> web/api-client/src/schema.d.ts
contract:
	$(UV_RUN) python scripts/contract.py generate

# Fails if either generated file differs from what the current app produces.
contract-check:
	$(UV_RUN) python scripts/contract.py check

licence-check:
	$(UV_RUN) python scripts/licence_check.py

# Enketo equivalence harness on touched fixtures (task C8). Stub until fixtures exist.
harness-quick:
	@echo "harness-quick: no fixtures yet"

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

# Local dev: `make dev` runs osp-api (SQLite in .data/, port 8000) and the builder dev server
# (5173, which proxies /api to the API, so no CORS) together; Ctrl+C stops both. The first
# run makes dev-only keys, a dev login and three seeded surveys, all in .data/ (gitignored);
# every run prints the login and the URLs. The participant app's dev server (5174, base
# /r/, proxying /api too) starts as well; its links are /r/?s=<slug>. `make dev-reset` wipes .data/. Dev only: never point this at real data.
DEV_DATA := .data
DEV_API_PORT := 8000
DEV_BUILDER_PORT := 5173
DEV_RUNTIME_PORT := 5174
DEV_FIXTURES := fixtures/01-all-types fixtures/13-randomiser-blocks fixtures/18-multi-language
DEV_ENV := OSP_ENV=dev OSP_DATA_DIR=$(DEV_DATA) OSP_DATABASE_URL=sqlite:///$(DEV_DATA)/osp.db
DEV_PROXY := OSP_API_URL=http://127.0.0.1:$(DEV_API_PORT)

.PHONY: dev dev-reset
dev:
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
	$(DEV_ENV) $(UV_RUN) osp-api serve --port $(DEV_API_PORT) & pids="$$!"; \
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
