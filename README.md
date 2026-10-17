# Open Survey Platform

An MIT-licensed, GUI-first survey builder for academic research. Surveys are authored in
our own JSON model, run in our own browser runtime, and can be exported to other
platforms. Contributors and AI agents: start with [`AGENTS.md`](AGENTS.md).

## Try it locally

**Prerequisites:** [uv](https://docs.astral.sh/uv/), Node 22+ and
[pnpm](https://pnpm.io/). Python 3.14 is fetched by uv.

```sh
make install   # uv sync + pnpm install, from the lockfiles
make dev       # API + builder + participant app; Ctrl+C stops them all
```

The first `make dev` creates everything it needs in `.data/` (gitignored): a SQLite
database, dev-only encryption keys, and three published surveys (fixture 01
"all question types", 13 "block randomiser" and 18 "multi-language"). There is no sign-in
in dev: everyone is the dev researcher. Every run prints something like:

```text
  Builder      http://localhost:5173
  API health   http://localhost:8000/api/health
  API docs     http://localhost:8000/api/docs

  No sign-in: everyone is dev-researcher, owner of dev-lab (dev only)

  Seeded surveys
    All question types  (01-all-types)
      builder      http://localhost:5173/surveys/<id>
      participant  http://localhost:5174/r/?s=<slug>
    ...
```

What to click:

1. Open http://localhost:5173.
2. Open one of the three surveys. Add a question, rename things, and try undo/redo.
   Every edit is saved to the API as you go.
3. Open a **participant** link in another window (a private window works well) and
   answer the survey as a participant. Fixture 13 randomises the order of its blocks per
   participant; fixture 18 has its text in more than one language.

`make dev-reset` wipes `.data/`, so the next `make dev` starts fresh.
Ports 8000, 5173 and 5174 must be free; override them with
`make dev DEV_API_PORT=8010 DEV_BUILDER_PORT=5183 DEV_RUNTIME_PORT=5184`.

This setup is for a laptop only. The API alone runs with `uv run osp-api serve`; with
`OSP_ENV=production` it refuses to generate keys and needs `OSP_STORE_KEYS` and
`OSP_DATABASE_URL` set (see `python/osp-api/src/osp_api/serve.py`).

## Deploying

The platform has no accounts of its own: your web app (a host) signs researchers in,
serves the builder pages and forwards API calls with signed identity headers. How to do
that, with a minimal Django example, is [`docs/hosting.md`](docs/hosting.md).

Build the engine bundle as part of every deployment build:

```sh
make engine-bundle   # web/engine/dist/engine.js
```

The reproducibility package ships this file with `replay.mjs`, so anyone can replay a
response with the exact engine that ran it. `web/engine/dist/` is not committed. If the
bundle is missing, packages go out without `replay.mjs` and say so. Point
`OSP_ENGINE_BUNDLE` at the file if it is not at the default path. `make dev` and
`make check` build it themselves.

## Checks

`make check` runs every test, lint, layer and licence check; it must be green before a
change lands.

The data export and reproducibility tests read committed engine records
(`python/osp-targets/tests/data/records/`). After adding a fixture script or changing a
fixture survey, run `make engine-records`; a test fails with that command if you forget.
