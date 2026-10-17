# osp-store

**Layer:** L4. Imports only packages in lower layers (enforced by `uv run lint-imports`). I/O allowed (L4 and up).

**Job:** Database persistence (SQLite for dev/tests, Postgres via `pg8000`). Model-agnostic: survey JSON is opaque, identified by survey id + draft revision, or version id + checksum. `osp-spec` validates it; the store only checks it is JSON.

Internal package; not published.

## Use

```python
from osp_store import Keyring, Store, SystemContext, TenantContext, create_engine, migrate

engine = create_engine("sqlite:///osp.db")  # or postgresql+pg8000://user:pw@host/db
migrate(engine)  # Alembic upgrade head
store = Store(engine, Keyring.from_env())  # OSP_STORE_KEYS="k1:<b64>", OSP_STORE_ACTIVE_KEY="k1"
```

Every method takes a context first. `TenantContext(tenant_id, actor)` scopes every query to one tenant; a row in another tenant raises `NotFound`, the same as a missing one. `SystemContext("system:<job>")` is a separate type for cross-tenant jobs (tenant creation, login lookup, retention, key rotation). A missing or wrong-type context raises `AccessDenied`. Role checks belong to `osp-app`.

## Tables

| Table | Holds |
|---|---|
| `tenants` | organisations / labs |
| `principals` | one row per host user id: last display name, first/last seen (plan P; display and audit only, never roles). Migration `0007_host_identity` |
| `surveys` | title, owner actor, `closed_at`, retention policy, `public_slug` (participant link id, generated, unique; migration `0005_public_slug`) |
| `drafts` | opaque survey JSON + `revision` (stale base revision → `RevisionConflict`) |
| `op_log` | op id, params, inverse (opaque JSON), resulting revision, seq, `txn_id` (undo unit) |
| `versions` | immutable: number, canonical JSON text, SHA-256 checksum (verified on every read), XForm blob, tool-version meta |
| `sessions` | version, `sessionSeed` (positive int), assigned conditions, realised orders (append-only), current page, autosaved instance (encrypted) |
| `responses` | version + checksum, allocation mode, seed, conditions, orders, engine version, answers with state (encrypted), timestamps |
| `audit_log` | actor, the actor's display name when written (`actor_name`, 0007), action, target; never participant data. Reads of responses are audited |
| `themes` | the lab's theme library: name (unique per lab), opaque theme JSON (`osp_spec.theme` validates it). Migration `0002_themes` |
| `lab_theme_defaults` | one row per lab: the theme new surveys start with; composite FK to the lab's own theme, cleared when that theme is deleted |
| `results_layouts` | a survey's saved Results-page layouts, shared by the lab: name (unique per survey), opaque settings JSON (`osp_app.results_layouts` validates it; never response data). Deleted with the survey. Migration `0009_results_layouts` |
| `results_layout_defaults` | one row per survey: its default layout; composite FK to one of that survey's own layouts, cleared when that layout is deleted |

Migration `0007_host_identity` dropped `users`, `user_mfa` and `auth_sessions` (passwords, TOTP, sign-in sessions): the host owns accounts (`planning/pages-split.md` D5). Labs a host names are made with `store.ensure_tenant(sys, lab_id)` (the host's id is the tenant id, 1-36 characters).

Child rows reference parents through composite `(tenant_id, id)` foreign keys, so the database refuses cross-tenant references too.

## Encryption at rest

AES-256-GCM (`cryptography`) per field: autosaved instances, answers, URL parameters, conflict snapshots, response records. Each row stores `<field>_key_id` next to the ciphertext (`0x01 ‖ nonce ‖ ct‖tag`). The AEAD associated data is `osp-store/<table>.<field>/<row id>`, so a blob copied to another row fails to decrypt. Rotation: add the new key and make it active (old rows stay readable), run `store.rotate_keys(SystemContext("system:rotate"))`, and retire the old key once `count_by_key` shows no rows for it.

## Data protection

- **Retention:** per survey `RetentionPolicy.none()` (default), `.days_after_close(n)` or `.after_date(dt)`. `plan_retention` is pure; `Store.run_retention(sys)` deletes due responses *and* sessions, one audit entry per survey. `Store.plan_retention(sys)` is the dry run.
- **Withdrawal:** `delete_response(ctx, response_id)` deletes the response and its session; `delete_session` covers withdrawal before submission.
- **No IP address, user agent or other network identifier** is stored (asserted in `tests/test_store_schema.py`).

## Tests

`make check` runs everything on SQLite. `make test-postgres` runs the same tests on a throwaway Postgres container too (needs Docker/Colima; skips with a message otherwise), or set `OSP_TEST_POSTGRES_URL`.
