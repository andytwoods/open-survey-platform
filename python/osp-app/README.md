# osp-app

**Layer:** L5. Imports only packages in lower layers (enforced by `uv run lint-imports`). I/O allowed (L4 and up).

**Job:** Session layer: auth, drafts, versions, publish; dispatches ops and app commands by id.

Internal package; not published.

## `osp_app.auth` (task C10a)

Auth core, no HTTP. Built against repository Protocols (`UserRepo`, `MembershipRepo`,
`SessionRepo`) with in-memory implementations; `osp-store` provides the DB-backed ones.

- `passwords`: argon2id (`argon2-cffi`), NIST 800-63B rules (min 15, max 256, NFKC,
  bundled blocklist `common_passwords.txt`, context words), rehash on login.
- `totp`: own RFC 6238 (SHA-1, 6 digits, 30 s, ±1 step), replay guard, provisioning
  URI, 10 single-use recovery codes stored as SHA-256.
- `sessions`: 256-bit opaque tokens stored as SHA-256; 30 min idle, 12 h absolute,
  5 min MFA-pending challenge; `rotate`, `revoke`, `revoke_all`.
- `service.AuthService`: login → MFA → session, lockout with exponential backoff
  (5 free attempts, 30 s doubling, cap 15 min), one uniform failure message.
- `permissions.can(actor, action, resource)`: fail-closed policy; `requires(action)`
  decorator for app commands.
- `testing`: fake clock, deterministic randomness, cheap hasher (tests only).

## Builder services (task C10)

- `store_repos`: `StoreUserRepo`, `StoreSessionRepo`, `StoreMembershipRepo` (osp-store backed;
  one tenant per user, role from `users.role`, unknown roles fail closed).
- `commands`: the app-command registry (`COMMANDS`, `dispatch`); refuses non-actors first.
- `builder.Builder`: `survey.create/list/get/delete`, `survey.apply_ops` (load draft ->
  `osp_ops.apply_transaction` -> `save_draft` + op_log with per-op inverses), `survey.undo` /
  `survey.redo` (by transaction id; undo ids `u:…`, redo ids `r:…`), `survey.history`,
  `survey.publish` (below), `survey.export_xlsform` (osp-targets).
  Surveys in tenants the actor can't read are `NotFoundError`; missing permission is `Forbidden`.
- `services.build_services(store, ...)` wires `AuthService` + `Builder` + one
  `osp_runtime.SessionService` (over `runtime_repo.StoreParticipantRepo`), shared by publish
  and the participant API.

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
