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

CHECKS := py-test py-layers py-lint web-check web-test web-build contract-check licence-check harness-quick

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
