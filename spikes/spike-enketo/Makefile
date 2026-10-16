# One command: make -C spikes/spike-enketo run
.PHONY: run deps build clean

run: deps build
	uv run python -m spike_enketo

deps:
	cd web && npm ci --no-audit --no-fund --loglevel=error
	uv sync --quiet
	uv run playwright install chromium webkit

build:
	cd web && node build.mjs

clean:
	rm -rf data build web/dist evidence/run
