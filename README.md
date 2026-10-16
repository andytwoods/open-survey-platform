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
database, dev-only encryption keys, a dev login, and three published surveys (fixture 01
"all question types", 13 "block randomiser" and 18 "multi-language"). Every run prints
something like:

```text
  Builder      http://localhost:5173
  API health   http://localhost:8000/api/health
  API docs     http://localhost:8000/api/docs

  Sign in (dev only; two-factor not enrolled)
    email      dev@osp.example
    password   9etp-hjhw-tk6f-7n4r          <- random, made on the first run

  Seeded surveys
    All question types  (01-all-types)
      builder      http://localhost:5173/surveys/<id>
      participant  http://localhost:5174/r/?s=<slug>
    ...
```

What to click:

1. Open http://localhost:5173 and sign in with the printed email and password.
2. Open one of the three surveys. Add a question, rename things, and try undo/redo.
   Every edit is saved to the API as you go.
3. Open a **participant** link in another window (a private window works well) and
   answer the survey as a participant. Fixture 13 randomises the order of its blocks per
   participant; fixture 18 has its text in more than one language.

`make dev-reset` wipes `.data/`, so the next `make dev` starts fresh with a new password.
Ports 8000, 5173 and 5174 must be free; override them with
`make dev DEV_API_PORT=8010 DEV_BUILDER_PORT=5183 DEV_RUNTIME_PORT=5184`.

This setup is for a laptop only. The API alone runs with `uv run osp-api serve`; with
`OSP_ENV=production` it refuses to generate keys and needs `OSP_STORE_KEYS` and
`OSP_DATABASE_URL` set (see `python/osp-api/src/osp_api/serve.py`).

## Checks

`make check` runs every test, lint, layer and licence check; it must be green before a
change lands.
