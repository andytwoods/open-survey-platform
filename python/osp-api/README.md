# osp-api

**Layer:** L6. Imports only packages in lower layers (enforced by `uv run lint-imports`). I/O allowed (L4 and up).

**Job:** Thin HTTP shell (FastAPI). Its OpenAPI schema is the contract in `/contract/openapi.json`.

Internal package; not published.

## Routes

- Participant (`participant.py`, task R2): `/api/s/...`, `/api/sessions/...`, bearer tokens.
- Builder (`routes/`, task C10): `auth.py` (login, TOTP step, logout, me, TOTP enrol/verify),
  `surveys.py` (CRUD, history, publish, XLSForm export), `ops.py` (`/ops`, `/undo`, `/redo`),
  `meta.py` (op catalogue, property/survey/theme schemas). Wired by `routes.install`.

Builder auth is a cookie: `__Host-osp_session` (HttpOnly, Secure, SameSite=Lax). Every unsafe
request also needs `X-CSRF-Token` (from `/api/auth/me` or the `__Host-osp_csrf` cookie; derived
from the session token) and must not be cross-origin. Errors are `{code, message}`; a stale
`baseRevision` is 409 with `currentRevision`; a rejected edit is 422 with `diagnostics`.
