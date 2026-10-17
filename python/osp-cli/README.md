# osp-cli

**Layer:** L6. Imports only packages in lower layers (enforced by `uv run lint-imports`). I/O allowed (L4 and up).

**Job:** Thin command-line shell over `osp-app`.

Internal package; not published.

## Commands

The database URL is `--db` or `OSP_DATABASE_URL`. The encryption keyring is `OSP_STORE_KEYS`
(`k1:<base64>`, optionally `OSP_STORE_ACTIVE_KEY`), the same variables the server reads.

```sh
uv run osp-cli gen-key                      # prints OSP_STORE_KEYS=k1:<fresh key>
uv run osp-cli lab create <lab-id> [--name N] [--db URL]   # when OSP_AUTO_CREATE_LABS=off
uv run osp-cli seed-fixture <fixture-dir> [--db URL] [--user ID] [--lab ID] [--save-mode every-page|end-only]
```

### `seed-fixture` (task R2b, for Playwright and other end-to-end tests)

Migrates the database, makes sure the lab exists (the host's lab id, default `seed-lab`),
then, as `--user` (default `seed-researcher`, owner of the lab; no accounts, plan P), imports `<fixture-dir>/survey.json` as a new survey and publishes it, so it
is startable at once. It prints one JSON object:

```json
{"fixture": "16-assign", "tenantId": "seed-lab", "userId": "seed-researcher", "surveyId": "…", "slug": "cuk2tvftmi", "versionId": "…", "versionNumber": 1,
 "planChecksum": "sha256:…", "planUrl": "/api/s/<slug>/plan/<checksum>",
 "startUrl": "/api/s/<slug>/sessions", "saveMode": "every-page"}
```

Example (a throwaway SQLite file; the server must use the same database and keys):

```sh
export OSP_STORE_KEYS=k1:$(uv run python -c "from osp_store import generate_key; print(generate_key())")
uv run osp-cli seed-fixture fixtures/16-assign --db sqlite:///$PWD/.build/e2e.db
```

- Each run makes a new survey with its own slug; seed every fixture a test needs.
- A first publish is version 1, so the plan's seed version is `"1"`, as in the fixtures'
  expected traces.
- The default ids are test data only. Errors print one line to stderr, exit code 2.
