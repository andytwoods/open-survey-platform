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
