# Contributing

Issues and pull requests are welcome at
[github.com/andytwoods/open-survey-platform](https://github.com/andytwoods/open-survey-platform).
Please read
[`AGENTS.md`](https://github.com/andytwoods/open-survey-platform/blob/main/AGENTS.md)
first: it is the guide for contributors and AI agents alike, and covers the repository map,
the layer rules, the licence policy and the clean-room rule.

## The rules in short

- **Semantics come from `planning/semantics.md`.** If a case is not covered, it goes under
  "Open questions" for a human decision. Nobody invents behaviour.
- **Every survey edit is an op** in `osp-ops`: an id, a parameter schema, a `run` that
  returns the new survey and its inverse, tests, and a hostile-input fuzz case.
- **Never crash on input.** Bad surveys, parameters, files or API responses produce a
  diagnostic, not an unhandled exception.
- **Clean-room.** Never copy code from LimeSurvey, Qualtrics, SurveyJS Creator, KoboToolbox,
  Formbricks or any other non-permissive project. Learn from documentation and observed
  behaviour.
- **Permissive dependencies only.** MIT, BSD, ISC, Apache-2.0 and similar; MPL-2.0 for
  dev, test and build tools only; GPL, AGPL, LGPL, BUSL and SSPL are refused.
  `make licence-check` enforces this for Python and JavaScript against
  `licence-policy.toml`.
- **No real personal data** in fixtures, logs, screenshots or prompts.
- **The UI is thin.** No survey logic in Svelte; the builder calls ops through the generated
  API client.

## Layers

The Python half is a uv workspace whose packages may only import lower layers, enforced by
import-linter:

| Layer | Packages | Notes |
|---|---|---|
| L0 | `osp-expr` | the expression language |
| L1 | `osp-spec` | the survey model and its JSON Schema |
| L2 | `osp-engine`, `osp-ops` | the Python engine and the edit ops |
| L3 | `osp-targets`, `osp-qa` | exports and quality checks |
| L4 | `osp-runtime`, `osp-store` | first layer allowed to do I/O |
| L5 | `osp-app` | commands, publishing, results |
| L6 | `osp-api`, `osp-cli`, `osp-mcp` | thin shells; only L6 may import the web framework |

L0 to L3 do no I/O at all: no network, database, clock or global randomness. The web half
is a pnpm workspace whose boundaries are enforced by dependency-cruiser.

## Definition of done

```sh
make install   # once
make check     # before finishing
```

`make check` runs the Python tests, import-linter, ruff, svelte-check, eslint,
dependency-cruiser, vitest, the builder build, the contract check, the licence check, the
engine and hooks tests, and a strict build of this documentation. Browser suites run as their
own targets (`make web-e2e`, `make harness-quick`). Changed an endpoint? Run `make contract`
and commit `contract/openapi.json` and the generated TypeScript client.

## This documentation

The site is MkDocs Material, built from `docs/` by `mkdocs.yml`:

```sh
make docs           # build into .build/site (strict: a broken link fails)
make docs-serve     # live preview at http://127.0.0.1:8000
make docs-screenshots   # redraw docs/assets/screenshots/ with Playwright
```

The [API reference](api.md) is generated from `contract/openapi.json` when the site is
built (`scripts/docs_openapi.py`), so it never goes stale. The screenshots come from a
Playwright script (`web/builder/docs/screenshots.ts`) that starts a throwaway stack and
drives the real builder with an invented survey, like the [demo videos](../demos.md); commit
the PNGs it writes. GitHub Pages publishes the site from `main`
(`.github/workflows/docs.yml`).

Write in plain UK English, and prefer short sentences and exact on-screen labels.
