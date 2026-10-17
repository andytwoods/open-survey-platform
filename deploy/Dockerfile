#
# Open Survey Platform: the official osp-api image (docs/hosting.md section 7).
#
#   docker build -f deploy/Dockerfile -t osp-api .
#
# One image holds osp-api (and osp-cli), the participant app (served at /r/ and /s/{slug}),
# the builder page files (served at /builder/, and at /app/web/builder in the image for a
# host that copies them), the engine bundle (repro packages) and the simulator CLI with the
# Node binary that runs it (the preview's "run simulation").
#
# Base images are pinned by version; bump them together with CI's NODE_VERSION/UV_VERSION.

ARG PYTHON_IMAGE=python:3.14.8-slim-trixie
ARG NODE_IMAGE=node:24.12.0-trixie-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.23
ARG PNPM_VERSION=12.14.0

# -- web: builder pages, participant app, engine bundle, simulator CLI -------------------
FROM ${NODE_IMAGE} AS web
ARG PNPM_VERSION
ENV CI=1 PNPM_HOME=/pnpm PATH=/pnpm:$PATH
RUN npm install --global --no-fund --no-audit "pnpm@${PNPM_VERSION}"
WORKDIR /src/web
# Dependencies first (cached while only sources change).
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
COPY web/api-client/package.json api-client/
COPY web/builder/package.json builder/
COPY web/engine/package.json engine/
COPY web/engine-sim/package.json engine-sim/
COPY web/harness/package.json harness/
COPY web/hooks-sandbox/package.json hooks-sandbox/
COPY web/runtime/package.json runtime/
COPY web/ui-components/package.json ui-components/
RUN pnpm install --frozen-lockfile --ignore-scripts
COPY web/ ./
RUN pnpm --filter @osp/builder exec vite build --logLevel warn \
 && pnpm --filter @osp/builder exec node scripts/check-build.mjs \
 && pnpm -C runtime exec vite build --logLevel warn \
 && pnpm -C engine exec vite build --config bundle.config.ts --logLevel warn \
 && pnpm -C engine-sim exec vite build --logLevel warn

# -- python: osp-api + osp-cli into a self-contained virtualenv -------------------------
FROM ${UV_IMAGE} AS uv
FROM ${PYTHON_IMAGE} AS python
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3 UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY python/ python/
# --no-editable: the packages are installed into the venv, so the source tree is not
# needed at run time.
RUN uv sync --locked --no-dev --no-editable --package osp-api --package osp-cli

# -- runtime -----------------------------------------------------------------------------
FROM ${NODE_IMAGE} AS node
FROM ${PYTHON_IMAGE}
LABEL org.opencontainers.image.title="osp-api" \
      org.opencontainers.image.description="Open Survey Platform API, participant app and builder files" \
      org.opencontainers.image.source="https://github.com/andytwoods/open-survey-platform" \
      org.opencontainers.image.licenses="MIT"
# Node runs the simulator CLI only (osp_runtime.sim_sidecar); it is one static-ish binary.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=python /app/.venv /app/.venv
COPY --from=web /src/web/runtime/dist /app/web/runtime
COPY --from=web /src/web/builder/build /app/web/builder
COPY --from=web /src/web/engine/dist/engine.js /app/web/engine/engine.js
COPY --from=web /src/web/engine-sim/dist /app/web/engine-sim
COPY deploy/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh \
 && groupadd --system --gid 10001 osp \
 && useradd --system --uid 10001 --gid osp --home-dir /data --no-create-home osp \
 && mkdir -p /data && chown osp:osp /data
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    OSP_ENV=production \
    OSP_HOST=0.0.0.0 \
    OSP_PORT=8000 \
    OSP_DATA_DIR=/data \
    OSP_PARTICIPANT_DIR=/app/web/runtime \
    OSP_BUILDER_DIR=/app/web/builder \
    OSP_ENGINE_BUNDLE=/app/web/engine/engine.js \
    OSP_SIM_CLI=/app/web/engine-sim/cli.js \
    OSP_NODE=/usr/local/bin/node
USER osp
WORKDIR /data
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request as u; u.urlopen('http://127.0.0.1:%s/api/health' % (os.environ.get('PORT') or os.environ['OSP_PORT']), timeout=4)"]
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["serve"]
