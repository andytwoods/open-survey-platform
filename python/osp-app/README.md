# osp-app

**Layer:** L5. Imports only packages in lower layers (enforced by `uv run lint-imports`). I/O allowed (L4 and up).

**Job:** Session layer: permissions, host identity, drafts, versions, publish; dispatches ops and app commands by id.

Internal package; not published.

## `osp_app.auth` and `osp_app.identity` (plan P)

Sign-in belongs to a host (`planning/pages-split.md`): there are no passwords, TOTP,
sessions or account creation here any more (removed with migration `0007_host_identity`).

- `auth.permissions.can(actor, action, resource)`: fail-closed policy; `requires(action)`
  decorator for app commands. `Actor` is a user id + `{lab id: Role}`.
- `identity.make_identity(user_id, roles, display_name)`: checks what a host sent (id
  lengths and characters, strict role names, at most 64 labs, printable display name) and
  builds an `Identity` (actor + display name); anything bad raises `InvalidIdentity`.
  `dev_identity()` is `dev-researcher`, owner of `dev-lab`.
- `AppServices.admit(identity) -> Actor`: per request, upserts the `principals` row (so
  audit rows carry the display name) and creates each named lab on first sight
  (`auto_create_labs`, D6), or drops unknown labs when that is off.

## Builder services (task C10)

- `commands`: the app-command registry (`COMMANDS`, `dispatch`); refuses non-actors first.
- `builder.Builder`: `survey.create/list/get/delete`, `survey.apply_ops` (load draft ->
  `osp_ops.apply_transaction` -> `save_draft` + op_log with per-op inverses), `survey.undo` /
  `survey.redo` (by transaction id; undo ids `u:…`, redo ids `r:…`), `survey.history`,
  `survey.publish` (below), `survey.export_xlsform` (osp-targets).
  Surveys in tenants the actor can't read are `NotFoundError`; missing permission is `Forbidden`.
- `services.build_services(store, ...)` wires `Builder` + one
  `osp_runtime.SessionService` (over `runtime_repo.StoreParticipantRepo`), shared by publish
  and the participant API.

## Results (plan V)

- `results`: V1's aggregation (`survey.results_query`, `survey.results_text`; V-D5 semantics).
- `results_layouts`: saved Results-page layouts (V-D9). `LayoutSettings` is the closed pydantic
  schema (query, cards in display order with chart / hidden / bins / caption, `showNotes`;
  unknown fields refused, never response data); `validate_settings` normalises it and runs the
  query part through `results.parse_query`. Commands `survey.results_layouts` (list),
  `survey.results_layout_get/create/update/delete/set_default`, all `survey.export`
  (owner, editor), per survey, shared by the lab, audited as `results.layout.*`.

## Publish (task R2b)

`survey.publish(survey_id, base_revision=None, save_mode="every-page")`:

1. `osp_spec.validate` the draft; any error -> `Rejected`.
2. Compile the runtime plan (`osp_runtime.plan.compile_survey`) for the body with `version` set
   to the number this version gets (the plan's seed version, semantics R1-1), and derive its
   `runtime_config` (assignments, quotas, save mode); an unrunnable config -> `Rejected`.
3. Freeze the version: that body, its checksum, `meta` with `planChecksum`, `planVersion`,
   `engineVersion`, `runtimeConfig` and `slug`; `versions.xform` holds the XLSForm export as an
   artefact (`meta.xform == "xlsform"`; empty if it can't be exported). The store re-checks the
   number inside its transaction; a concurrent publish -> `ConflictError`.
4. Register the publication under the survey's public slug (`surveys.public_slug`, generated at
   creation). A republish keeps the slug: new sessions start on the newest version, and older
   plans stay servable at `GET /api/s/{slug}/plan/{checksum}` for sessions already on them.
