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
harness-quick:
	@fx="$${OSP_HARNESS_FIXTURES-$(HARNESS_TOUCHED)}"; \
	echo "harness-quick: fixtures: $${fx:-all}"; \
	OSP_HARNESS_FIXTURES="$$fx" $(PNPM) -C web/harness exec playwright test --project=desktop-chromium

# Every fixture × every device project (iPhone SE/WebKit, Pixel 7/Chromium, desktop Firefox,
# desktop Chromium). engine-test first, so the report can tell runtime divergences (engine
# passes, app fails) from fixture or engine failures.
harness-full: engine-test
	OSP_HARNESS_FIXTURES= $(PNPM) -C web/harness exec playwright test $(HARNESS_ARGS)

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
