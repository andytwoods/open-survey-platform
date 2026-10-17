# osp-api

**Layer:** L6. Imports only packages in lower layers (enforced by `uv run lint-imports`). I/O allowed (L4 and up).

**Job:** Thin HTTP shell (FastAPI). Its OpenAPI schema is the contract in `/contract/openapi.json`.

Internal package; not published.

## Routes

- Participant (`participant.py`, task R2): `/api/s/...`, `/api/sessions/...`, bearer tokens.
- Builder (`routes/`, task C10): `me.py` (`GET /api/me`: who the host says you are, your
  labs), `surveys.py` (CRUD, history, publish, exports), `ops.py` (`/ops`, `/undo`, `/redo`),
  `themes.py`, `meta.py` (op catalogue, schemas, expressions). Wired by `routes.install`.

Errors are `{code, message}`; a stale `baseRevision` is 409 with `currentRevision`; a
rejected edit is 422 with `diagnostics`.

## Identity: the host signs in, osp-api trusts it (plan P)

osp-api has **no accounts, passwords, two-factor or sessions** (`planning/pages-split.md`).
A host (a university's web app, a reverse proxy with single sign-on) authenticates the
researcher and tells osp-api who they are on every request. `create_app(builder=...,
identity=...)` takes an `IdentityProvider` (`osp_api/identity.py`):

| Provider | Use | `osp-api serve` |
|---|---|---|
| `TrustedHeaders(keys)` | a host or proxy forwards requests with HMAC-signed `X-OSP-*` headers | `OSP_IDENTITY=trusted-headers` (default) + `OSP_IDENTITY_KEYS=kid:secret,...` |
| `InProcess(fn)` | a Python host mounts the ASGI app; `fn(request)` returns an `Identity`/`Actor`/`None` (sync runs in a thread, so a sync ORM is fine) | - |
| `Dev(env=, host=)` | everyone is `dev-researcher`, owner of `dev-lab` (`make dev`, e2e) | `OSP_IDENTITY=dev`; refused unless `OSP_ENV=dev` and a loopback bind |

What a provider returns is re-checked (`osp_app.make_identity`) whoever the host is: user ids
1-64 and lab ids 1-36 characters of `A-Z a-z 0-9 . _ ~ @ + -`; roles exactly `owner`,
`editor` or `viewer`; at most 64 labs; display names printable, at most 200 characters. A
bad value refuses the whole identity (401). Every route then checks the resource's lab
against the actor's roles, as before: a survey in a lab you have no role in is 404.

Per request the app also upserts a `principals` row (host user id, last display name,
first/last seen; audit rows snapshot the name) and creates each named lab on first sight
(`OSP_AUTO_CREATE_LABS`, default on; off: `osp-cli lab create <id>` first, and an unknown
lab confers nothing).

CSRF is the host's job before it signs or calls in (D4). osp-api still refuses unsafe
requests that are cross-origin (`Origin` / `Sec-Fetch-Site`; `OSP_ALLOWED_ORIGINS` lists
exact origins allowed cross-origin, with CORS credentials) and unsafe requests whose body is
not `application/json` (415).

`osp-api serve` binds 127.0.0.1 by default (D3). The host must be the only route to the API
and must strip any `X-OSP-*` header a browser sends. Without a valid signature a request is
401, whatever headers it carries.

### Signed headers (v1)

| Header | Value |
|---|---|
| `X-OSP-Key-Id` | which `OSP_IDENTITY_KEYS` secret signed it (rotation: list old and new, switch the host, drop the old) |
| `X-OSP-User` | the host's opaque user id |
| `X-OSP-Roles` | `lab:role,...` sorted by lab id (empty: no labs) |
| `X-OSP-Display-Name` | optional; UTF-8, percent-encoded |
| `X-OSP-Timestamp` | Unix seconds; at most 60 s from osp-api's clock |
| `X-OSP-Nonce` | 128 random bits (base64url); each accepted once (in-memory, per process, 120 s) |
| `X-OSP-Signature` | hex HMAC-SHA256 of the canonical string |

The canonical string is, one per line: `OSP-HMAC-SHA256-v1`, the method, the
percent-decoded path as osp-api routes it, the query with pairs sorted and RFC 3986-encoded,
the SHA-256 hex of the exact body bytes, then the user, roles, display-name, timestamp and
nonce header values (`osp_api/signing.py`, the one implementation both sides use). Secrets
are at least 32 bytes. Comparison is constant-time. The nonce cache is per process: with
several workers, pin a host to one or accept the per-worker replay window (documented
limit; JWT/JWKS is a later option, P5).

A host signs with the same module (standard library only):

```python
from osp_api.signing import sign_identity_headers

headers = sign_identity_headers(
    key_id="host1",
    secret=SECRET,  # one of OSP_IDENTITY_KEYS
    method="POST",
    path="/api/surveys",  # as osp-api sees it, query included if any
    body=body_bytes,  # send exactly these bytes
    user_id=str(request.user.pk),
    roles={"psych-lab": "editor"},
    display_name=request.user.get_full_name(),
)
# forward to osp-api with these headers added (after stripping any incoming X-OSP-*)
```

How a host serves the builder pages and proxies `/osp/api` is `docs/hosting.md` (task P4).
