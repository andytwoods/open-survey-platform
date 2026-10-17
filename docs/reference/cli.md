# Command line

Three small command-line tools come with the Python packages. Run them with `uv run` from a
checkout (or from the virtual environment `uv sync` makes).

## `osp-api`

The HTTP API server (FastAPI, run by uvicorn).

| Command | What it does |
|---|---|
| `osp-api serve [--host HOST] [--port PORT]` | Serve the API. Binds `127.0.0.1:8000` by default; keep it that way behind a host. |
| `osp-api init` | Create the data directory, run the database migrations and (in dev) generate dev-only keys, then exit. |

Configuration is by environment variable. The full table, with defaults, is in
[Hosting](../hosting.md#1-the-pieces); the essentials:

| Variable | Meaning |
|---|---|
| `OSP_ENV` | `dev` or `production`. Production refuses to start without `OSP_DATABASE_URL` and `OSP_STORE_KEYS`. |
| `OSP_DATABASE_URL` | Any SQLAlchemy URL, for example `sqlite:///.data/osp.db` or a Postgres URL. |
| `OSP_STORE_KEYS`, `OSP_STORE_ACTIVE_KEY` | The keyring that encrypts stored responses (`osp-cli gen-key`). |
| `OSP_IDENTITY` | `trusted-headers` (a host signs every request) or `dev` (everyone is the dev researcher; loopback and `OSP_ENV=dev` only). |
| `OSP_IDENTITY_KEYS` | `kid:secret,...` shared with the host. |
| `OSP_PUBLIC_ORIGINS`, `OSP_ALLOWED_ORIGINS`, `OSP_TRUSTED_PROXIES`, `OSP_NONCE_STORE` | Origin check, cross-origin opt-in, proxy addresses and the replay-protection store. |
| `OSP_PARTICIPANT_URL_TEMPLATE` | The public participant link with a `{slug}` placeholder, shown after a publish. Default `/r/?s={slug}`. |
| `OSP_ENGINE_BUNDLE` | Path to `web/engine/dist/engine.js` if it is not at the default place (the reproducibility package ships it). |

In development, `make dev` runs `osp-api init` and `osp-api serve` for you with a SQLite
database and generated keys in `.data/`.

## `osp-cli`

Administrative commands. The database comes from `--db` or `OSP_DATABASE_URL`.

| Command | What it does |
|---|---|
| `osp-cli gen-key` | Print a fresh `OSP_STORE_KEYS=k1:…` line for a new deployment. |
| `osp-cli lab create <id> [--name NAME]` | Create a lab. Needed only when `OSP_AUTO_CREATE_LABS=off`; otherwise a lab exists as soon as the host first names it. |
| `osp-cli seed-fixture <dir> [--user U] [--lab L] [--save-mode MODE]` | Import a fixture survey (one of `fixtures/NN-…`) into a lab and publish it. If the fixture has no retention policy, 30 days after close is set. |
| `osp-cli dev-seed <dirs…> [--data-dir D] [--builder-url U] [--participant-link T]` | What `make dev` runs: seed several fixtures and print their builder and participant links. Refused when `OSP_ENV=production`. |

## `osp-mcp`

The MCP server through which an AI assistant drafts surveys; see
[Drafting with an AI assistant](../ai-drafting.md) for the setup and the tools.

| Command | What it does |
|---|---|
| `osp-mcp` | Serve MCP over standard input and output (an MCP client launches it). Needs `OSP_DATABASE_URL`, `OSP_STORE_KEYS`, `OSP_MCP_USER` and `OSP_MCP_LAB`; optional `OSP_MCP_ROLE`, `OSP_MCP_NAME`, `OSP_MCP_BUILDER_URL`. |
| `osp-mcp tools` | Print the tool list as JSON and exit; no database needed. |

## Make targets

The Makefile is the one entry point for humans, agents and CI. The most useful targets:

| Target | What it does |
|---|---|
| `make install` | `uv sync` and `pnpm install`, from the lockfiles |
| `make dev`, `make dev-reset` | Run the API, builder and participant app locally; wipe `.data/` |
| `make check` | Everything that must be green before a change lands |
| `make web-e2e`, `make harness-quick`, `make harness-full` | The browser suites (need Playwright browsers) |
| `make contract` | Regenerate `contract/openapi.json` and the TypeScript client |
| `make engine-bundle` | Build `web/engine/dist/engine.js` for the reproducibility package |
| `make docs`, `make docs-serve`, `make docs-screenshots` | This site |
| `make demo-videos` | The scripted [demo videos](../demos.md) |
| `make test-postgres` | The store tests against a throwaway Postgres container |
