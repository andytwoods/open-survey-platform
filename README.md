# Open Survey Platform

[![CI](https://github.com/andytwoods/open-survey-platform/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/andytwoods/open-survey-platform/actions/workflows/ci.yml)

An open-source, GUI-first survey builder for academic research, built as a free
alternative to commercial survey tools. Researchers design surveys in the browser,
participants answer them on any screen size, and every response can be replayed exactly.

**Status:** early development (October 2026). Usable on a laptop for building and
running test surveys; not yet deployed in production. Expect breaking changes.

## What it does

- **Visual builder.** Pages, blocks and questions in an outline; a canvas that shows each
  question as participants will see it; a properties panel; undo/redo; a command palette
  (Ctrl/Cmd+K); keyboard-only operation.
- **Nine question types:** text, whole number, decimal, single choice, multiple choice,
  date, grid (matrix), slider and note. Change a question's type later without losing
  its text or logic.
- **Survey logic:** display conditions, branching flow, piped text, block randomisers
  and shuffled choices, balanced assignment to conditions, quotas, validation.
- **Research features:** consent block (nothing saved before agreement, withdrawal
  handled), several languages per survey, save-and-resume links, per-page or end-only
  saving, built-in trial and position counters, and researcher hooks (your own JavaScript
  on key events, run in a sandbox).
- **Looks and accessibility:** themes built from design tokens with a WCAG AA contrast
  check, light and dark, tested on phone, tablet and desktop sizes, with axe checks.
- **Data and reproducibility:** CSV/JSON response export with a codebook, versioned
  publishing (each response is tied to the exact survey version it saw), and a
  reproducibility package that replays any response with the engine that ran it.
- **Interoperability:** export to XLSForm (ODK/Enketo/KoboToolbox) and LimeSurvey.
- **Bring your own sign-in.** The platform has no accounts or passwords. Your web app
  (a university system, Django, a single sign-on proxy) signs researchers in and forwards
  requests with signed identity headers. See [`docs/hosting.md`](docs/hosting.md).
- **Privacy:** answers are encrypted at rest (AES-GCM), labs are kept apart, retention
  periods are enforced.

## How it is built

| Part | What | Where |
|---|---|---|
| Builder | Svelte 5 pages, one bundle per page, mounted by your host | `web/builder` |
| Participant app | Svelte 5; the survey engine runs entirely in the browser | `web/runtime`, `web/engine` |
| API | FastAPI over a layered Python core (spec, ops, store, exports) | `python/` |
| Storage | SQLAlchemy with Alembic migrations; SQLite or Postgres | `python/osp-store` |
| Contract | OpenAPI schema; the TypeScript client is generated from it | `contract/`, `web/api-client` |

The browser decides which page comes next; the server only saves answers and counts
across participants (quotas, balanced assignment). Behaviour is pinned down in
[`planning/semantics.md`](planning/semantics.md) and checked by 40 fixture surveys that are
played through real browsers on four device profiles.

Contributors and AI agents: start with [`AGENTS.md`](AGENTS.md).

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
      responses    150 fake sessions: 125 submitted (complete 125), 25 dropped out
      participant  http://localhost:5174/r/?s=<slug>
    ...
```

On that first run each seeded survey also gets 150 invented responses, so the Results
page has something to show. They are made by the real engine and stored through the same
session path as real participants (spread over the last 21 days, about 15 % dropping out
part-way). `DEV_FAKE_RESPONSES=0 make dev` turns this off; `make dev-fake N=200` adds 200
more to each seeded survey while the servers run. For one survey:
`OSP_ENV=dev uv run osp-cli fake-responses <survey id or slug> --n 150 --seed 1 --partial 0.15 --days 21`
(with `OSP_DATABASE_URL` and `OSP_STORE_KEYS` set as in `make dev`).

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
change lands. GitHub Actions ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs
it on every push and pull request: the non-browser checks on Ubuntu and Windows, and the
builder end-to-end suite and the fixture harness as their own jobs with cached Playwright
browsers.

The data export and reproducibility tests read committed engine records
(`python/osp-targets/tests/data/records/`). After adding a fixture script or changing a
fixture survey, run `make engine-records`; a test fails with that command if you forget.

## Contributing

Issues and pull requests are welcome. Please read [`AGENTS.md`](AGENTS.md) first: it covers
the layer rules, the licence policy (permissive dependencies only) and the clean-room rule
(never copy code from other survey tools). `make check` must pass.

## Licence

[MIT](LICENSE). Dependencies are limited to permissive licences, checked by
`make licence-check` against [`licence-policy.toml`](licence-policy.toml).
