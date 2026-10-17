# Open Survey Platform

An open-source, GUI-first survey builder for academic research, built as a free alternative
to commercial survey tools. Researchers design surveys in the browser, participants answer
them on any screen size, and every response can be replayed exactly.

**Status:** early development (October 2026). Usable on a laptop for building and running
test surveys; not yet deployed in production. Expect breaking changes.

<figure markdown="span">
  ![The builder: outline on the left, the questions in the middle, properties on the right](assets/screenshots/editor.png){ loading=lazy }
  <figcaption>The builder, editing an invented "Coffee and sleep study".</figcaption>
</figure>

## Where to start

<div class="grid cards" markdown>

- :material-rocket-launch: **[Getting started](getting-started.md)**

    Install the tools, run `make dev` and open the three seeded surveys.

- :material-pencil-ruler: **[Building a survey](building-a-survey.md)**

    Pages, blocks and questions; the outline, canvas and properties panel; undo, redo and
    the command palette.

- :material-source-branch: **[Logic and flow](logic.md)**

    Display conditions, branches, randomisers, quotas, assignment and piping.

- :material-send: **[Publishing and exports](publishing.md)**

    Publish checks, versions, the participant link, data exports and the reproducibility
    package.

- :material-chart-bar: **[Results](results.md)**

    A chart and a table per question, filters, splits and figure export.

- :material-robot-outline: **[Drafting with an AI assistant](ai-drafting.md)**

    Describe your study to an MCP-capable assistant and review its draft in the builder; it
    can never publish.

- :material-server: **[Hosting](hosting.md)**

    Run the platform behind your own sign-in, with a minimal Django example.

</div>

## What it does

- **Visual builder.** Pages, blocks and questions in an outline; a canvas that shows each
  question as participants will see it; a properties panel; undo and redo; a command
  palette (++ctrl+k++ or ++cmd+k++); keyboard-only operation.
- **Nine question types:** text, whole number, decimal number, single choice, multiple
  choice, date, grid, slider and note. Change a question's type later without losing its
  text or logic. See [Question types](question-types.md).
- **Survey logic:** display conditions, branching flow, piped text, block randomisers and
  shuffled choices, random assignment to conditions, quotas, validation.
- **Research features:** a consent page (nothing is saved before agreement, and withdrawal
  is handled), several languages per survey, save-and-resume links, per-page or end-only
  saving, built-in trial and position counters, and researcher hooks (your own JavaScript on
  key events, run in a sandbox).
- **Looks and accessibility:** themes built from design tokens with a WCAG AA contrast
  check, light and dark, tested at phone, tablet and desktop sizes with axe checks.
- **Data and reproducibility:** CSV and JSON response export with a codebook, versioned
  publishing (each response is tied to the exact survey version it saw), and a
  reproducibility package that replays any response with the engine that ran it.
- **Interoperability:** export to XLSForm (ODK, Enketo, KoboToolbox) and LimeSurvey.
- **Bring your own sign-in.** The platform has no accounts or passwords. Your web app (a
  university system, Django, a single sign-on proxy) signs researchers in and forwards
  requests with signed identity headers.
- **Privacy:** answers are encrypted at rest (AES-GCM), labs are kept apart, retention
  periods are enforced, and no participant IP address is stored or logged.

## How it is built

| Part | What | Where |
|---|---|---|
| Builder | Svelte 5 pages, one bundle per page, mounted by your host | `web/builder` |
| Participant app | Svelte 5; the survey engine runs entirely in the browser | `web/runtime`, `web/engine` |
| API | FastAPI over a layered Python core (spec, ops, store, exports) | `python/` |
| Storage | SQLAlchemy with Alembic migrations; SQLite or Postgres | `python/osp-store` |
| Contract | OpenAPI schema; the TypeScript client is generated from it | `contract/`, `web/api-client` |

The browser decides which page comes next; the server only saves answers and counts across
participants (quotas, assignment). Behaviour is pinned down in
[`planning/semantics.md`](https://github.com/andytwoods/open-survey-platform/blob/main/planning/semantics.md)
and checked by 40 fixture surveys played through real browsers on four device profiles.

The source is on [GitHub](https://github.com/andytwoods/open-survey-platform) under the MIT
licence. Contributors and AI agents: see [Contributing](reference/contributing.md).
