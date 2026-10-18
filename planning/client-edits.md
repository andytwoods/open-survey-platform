# Edits in the browser (owner decision, 18 Oct 2026)

Owner: "edits in the builder should be in TS! These are applied to the script and we save
the script on the backend."

Today every builder edit is an op sent to the server, applied there by Python (`osp-ops`),
validated (`osp-spec`) and answered with a JSON Patch; Preview asks the server to compile a
plan (`POST /preview-plan`, `osp_runtime.plan`). After this change the builder applies its
own edits in TypeScript and the server checks and stores the document. That also gives a
builder that runs with no server at all (the Pages demo, DEMO2).

## Decisions (lead)

1. **TypeScript is the builder's editing engine.** New package `web/ops` (`@osp/ops`): every
   op in `osp-ops` with the same name, params, errors, patch and inverse. The builder applies
   ops locally and shows the result at once.
2. **Python stays, as the server's check and for server-side tools.** `osp-ops` remains for
   the MCP drafting tools, importers, the CLI and bank insertion. Drift is prevented the way
   the engine already does it: Python writes parity vectors (ops on every fixture, plus seeded
   random op sequences), and the TS package must produce byte-identical documents, patches and
   inverses (`make ops-parity`, part of `make check`).
3. **Saving.** `PUT /api/surveys/{id}/draft` with `{baseRevision, patch, ops, transactionId}`.
   The server applies the JSON Patch, validates the whole document with `osp-spec` (rich text,
   limits, ids: "sanitised at save" stays true), stores it, audits the op names, and answers
   `{revision, diagnostics}`. 409 on a stale base, 422 if the result is invalid (nothing saved).
   The old `POST /ops`, `/undo`, `/redo` stay for other clients (MCP), unchanged.
4. **Undo and redo move to the browser** (inverse patches, per page load as today).
5. **Diagnostics.** The server's validator stays authoritative (on save). The browser gets a
   TS port of the validator for instant feedback and for the serverless demo; parity vectors
   as in 2.
6. **Expressions.** TS gets the parser and static checks (`osp-expr` syntax + static), with
   parity on every expression in the fixtures and a generated corpus.
7. **Plan compile in TS** (`osp_runtime.plan` → `@osp/engine` `compilePlan`), checksum-identical
   to Python for every fixture. Preview compiles in the browser. Publish still compiles on the
   server (authoritative checksum); parity guarantees they agree.

## Tasks

| Id | What | Depends |
|---|---|---|
| CE1 | TS expression parser + static checks, parity | — |
| CE2 | `@osp/ops`: all ops in TS, parity vectors incl. random sequences | CE1 for condition ops |
| CE3 | TS plan compile, checksum parity on all fixtures | CE1 |
| CE4 | TS validator, diagnostics parity | CE1 |
| CE5 | Save protocol (`PUT …/draft`), builder applies ops locally, undo/redo in the browser | CE2, CE4 |
| DEMO2 | Pages: the builder with a prespecified study and no server (in-memory transport, local Preview), plus the study itself to take | CE2, CE3, CE4 |
