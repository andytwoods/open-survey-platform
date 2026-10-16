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
  `survey.publish` (validate -> freeze version + checksum; runtime plan compile is a TODO hook,
  `compile_runtime_plan`, until R1 lands), `survey.export_xlsform` (osp-targets).
  Surveys in tenants the actor can't read are `NotFoundError`; missing permission is `Forbidden`.
- `services.build_services(store, ...)` wires `AuthService` + `Builder`.
