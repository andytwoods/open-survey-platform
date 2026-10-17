# Hosting: running the platform behind your own sign-in

This project has no accounts, passwords or sessions. A **host** does that: your
university's Django or Rails app, or a reverse proxy with single sign-on. The host signs the
researcher in, serves the builder pages, and tells `osp-api` who the researcher is on every
request. The design is `planning/pages-split.md` (its §Decisions D1–D16).

A tested version of the proxy below is `python/osp-api/tests/test_hosting_example.py`.

## 1. The pieces

| Piece | What it is | Where it comes from |
|---|---|---|
| Builder pages | Static JS and CSS, one entry per page, plus `manifest.json` | `make web-build` writes `web/builder/build/` |
| Participant app | One static bundle; participants never sign in | `pnpm -C web/runtime build` writes `web/runtime/dist/` |
| `osp-api` | The HTTP API (FastAPI, run by uvicorn) | `osp-api serve` |
| Database | SQLite or Postgres URL (below) | `OSP_DATABASE_URL` |
| Encryption keys | Keyring for stored responses (`osp-cli gen-key`) | `OSP_STORE_KEYS` (optional `OSP_STORE_ACTIVE_KEY`) |

All of these but the database come in one container image, `deploy/Dockerfile` (section 7).

Run `osp-api` with `OSP_ENV=production`. It then refuses to start unless `OSP_DATABASE_URL`
and `OSP_STORE_KEYS` are set. Keep the keys in your secret store: without them the stored
responses cannot be read.

`OSP_DATABASE_URL` takes the URL your PaaS gives you. Postgres always goes through the
pg8000 driver (BSD; psycopg is LGPL and not installed), so `postgres://…` and
`postgresql://…` (Heroku, Dokku, Render, Appliku) both mean `postgresql+pg8000://…`, which
you can also write yourself. A libpq `?sslmode=` on the URL is honoured: `disable`,
`allow` and `prefer` connect without TLS; `require` uses TLS without checking the
certificate (as libpq does); `verify-ca` and `verify-full` check it against the system
trust store. SQLite (`sqlite:///path/osp.db`) suits one machine with one osp-api process.

`osp-api serve` binds `127.0.0.1` by default (`OSP_HOST`, `OSP_PORT`; port 8000). Keep it
that way. The host must be the **only** route to the API.

Other settings (all in `python/osp-api/src/osp_api/serve.py`):

| Variable | Meaning | Default |
|---|---|---|
| `OSP_IDENTITY` | `trusted-headers` or `dev` | `trusted-headers` |
| `OSP_IDENTITY_KEYS` | `kid:secret,...` shared with the host (each secret at least 32 bytes) | required |
| `OSP_AUTO_CREATE_LABS` | create a lab the first time the host names it | `on` |
| `OSP_PUBLIC_ORIGINS` | your public origin(s), e.g. `https://surveys.example.ac.uk`: accepted by osp-api's Origin check, no CORS (section 3) | none |
| `OSP_ALLOWED_ORIGINS` | exact origins allowed to call the API cross-origin (CORS, with credentials) | none |
| `OSP_TRUSTED_PROXIES` | IPs or CIDRs of your proxy, whose `X-Forwarded-For` gives the participant's address (section 4) | none |
| `OSP_NONCE_STORE` | where replayed signatures are caught: `database` (every worker) or `memory` (one process) | `database` in production, `memory` in dev |
| `OSP_PARTICIPANT_URL_TEMPLATE` | where participants open a survey (`{slug}`) | `/r/?s={slug}` |
| `OSP_LIVE_POLL_MS` | how often a live results page may ask whether responses changed (milliseconds, 1000–3600000); every poll is one signed request through your proxy, so raise it under load | `10000` |

Never use `OSP_IDENTITY=dev` on a server. It makes everyone the lab owner, so osp-api refuses
it unless `OSP_ENV=dev` and the bind is loopback.

## 2. Serving a builder page

There are eight pages: `list`, `editor`, `flow`, `settings`, `appearance` (one survey's
theme), `results` (one survey's results, a card per question), `themes` (the lab's theme
library) and `preview-frame`. You choose their URLs.

1. Serve `web/builder/build/` as static files, for example under `/static/osp/`. Keep its
   folder layout: the files load each other by relative path.
2. Read `build/manifest.json` once at start-up. It looks like this:
   ```json
   { "version": 1,
     "pages": { "editor": { "js": "assets/editor-….js", "css": ["assets/….css"], "preload": ["assets/….js"] } },
     "csp": { "preview-frame": "default-src 'none'; …" } }
   ```
   Paths are relative to `build/`. `csp` is the header a page needs instead of your
   default policy (section 5, item 6).
3. Add one route per page, behind your login. Each route renders:
   - every `css` file as `<link rel="stylesheet">`;
   - every `preload` file as `<link rel="modulepreload">`;
   - `<div id="osp"></div>`;
   - the config tag `<script type="application/json" id="osp-config">…</script>`;
   - the `js` file as `<script type="module">`.

   The page finds `#osp` and the config tag and mounts itself.
4. Optionally, give each page a `<title>`, a `<meta name="description">` and the icons.
   The icons sit in the root of `build/` (from `web/builder/static/`): `favicon.svg`,
   `favicon-32.png`, `apple-touch-icon.png` and `site.webmanifest`, whose icon paths are
   relative to it, so it works under any prefix. Link them with your static prefix, as in
   section 6. To use your own, link your files instead. The dev host's titles and
   descriptions (`TITLES`, `DESCRIPTIONS` in `web/builder/dev-host/pages.ts`) are a
   starting point.

### The config (`OspPageConfig`)

The source of truth is `web/builder/src/lib/host/config.ts`:

```ts
interface OspPageConfig {
  version: 1;
  apiBase: string;                 // replaces the `/api` prefix of every call, e.g. "/osp/api"
  surveyId?: string;               // required on editor, flow, settings, appearance, results
  tenantId?: string;               // which lab, if the user is in several (a selector only)
  links: {                         // URL templates; {id} is replaced (URL-encoded)
    list: string; editor: string; flow: string; settings: string;
    appearance: string; themes: string; previewFrame: string;
    results?: string;              // optional: without it the Results link is hidden
    profile?: string;              // optional: the lab's property panel profile page
  };
  csrf?: { header: string; token?: string; cookie?: string }; // sent on POST/PUT/PATCH/DELETE
  onUnauthenticated?: { redirect: string } | 'reload';        // after a 401; default 'reload'
  user?: { displayName?: string };  // shown in the header (else GET /api/me's displayName)
  allowedOrigins?: string[];        // exact origins apiBase/links may use besides the page's
}
```

- **`links`**: the first seven are required; `results` and `profile` are optional (without
  them the editor shows no Results link and no way to the panel profile page, so a config
  written before those pages still works).
  `editor`, `flow`, `settings`, `appearance` and `results` must contain `{id}`; the page
  puts the survey id there. The Results page needs the `survey.export` role (owner or
  editor); a viewer sees a "no access" message. Moving between pages is a normal full
  page load to these URLs.
- **`csrf`**: your own CSRF scheme, not ours. The page sends `header` on every write, with
  `token`, or with the value of the cookie named `cookie`. One of the two is required.
- **`onUnauthenticated`**: what happens when the API answers 401 (your session ended). With
  `{ "redirect": "/login/" }` the page shows a banner linking to `/login/?next=<this page>`.
  With `'reload'` it reloads once so your login runs. It never loops, and unsaved edits stay
  queued on the page. A 403 shows "you don't have access to this lab" instead.
- **`tenantId` and `surveyId`** only select. The API still checks the researcher's role in
  the survey's lab on every request.
- **Same origin**: `apiBase`, every link and the redirect must be on the page's own origin
  (relative paths are simplest), unless their origin is listed in `allowedOrigins`.
- The page rejects a bad config before anything runs: unknown keys, wrong types, values too
  long, or a cross-origin URL. It shows the errors in `#osp`.
- **`preview-frame`** takes only `{"version": 1}`, or no config tag at all. It never gets the
  API base or a CSRF token.

### Embedding the JSON safely

The config sits inside a `<script>` tag, so a `</script>` in any value would end it. Escape
every `<` as `<` (and `>` and `&` likewise). In Django use `json_script`, which does
this:

```django
{{ config|json_script:"osp-config" }}
```

Never build the tag with string formatting or `|safe`.

## 3. Forwarding API calls

The pages call `apiBase` (say `/osp/api`) on your origin. Your host forwards those calls to
osp-api's `/api`. For each request:

1. Check your own session. No session: answer 401 yourself, and forward nothing.
2. Check your own CSRF token on `POST`, `PUT`, `PATCH` and `DELETE`. Bad token: refuse.
3. Copy only the headers osp-api needs (`Content-Type`, `Accept`, `Origin`,
   `Sec-Fetch-Site`). This drops any `X-OSP-*` header the browser sent, along with your
   cookies.
4. Sign with `sign_identity_headers` from the `osp-host-signing` package (below) and add
   the headers it returns.
5. Send the body **byte for byte** as signed, to `http://127.0.0.1:8000` + the API path.
6. Return the status, the body and the `Content-Type`, `Content-Disposition` and
   `Cache-Control` headers.

Install the signer in your host. It is one module, standard library only, Python 3.9+, MIT,
and it is the code osp-api verifies with (`osp_api.signing` re-exports it). It is not on
PyPI; install it from the repository (pin a commit in production):

```sh
pip install "osp-host-signing @ git+https://github.com/andytwoods/open-survey-platform#subdirectory=python/osp-host-signing"
```

```python
from osp_host_signing import sign_identity_headers

headers = sign_identity_headers(
    key_id="host1",  # the kid of one OSP_IDENTITY_KEYS entry
    secret=SECRET,  # its secret
    method="POST",
    path="/api/surveys",  # as osp-api sees it, with the query if there is one
    body=body_bytes,
    user_id=str(request.user.pk),  # your opaque user id (1-64 of A-Z a-z 0-9 . _ ~ @ + -)
    roles={"psych-lab": "editor"},  # lab id -> "owner", "editor" or "viewer"
    display_name=request.user.get_full_name() or None,
)
```

It returns `X-OSP-Key-Id`, `X-OSP-User`, `X-OSP-Roles`, `X-OSP-Display-Name` (only with a
name), `X-OSP-Timestamp`, `X-OSP-Nonce` and `X-OSP-Signature`. The signature covers the
method, path, sorted query, a hash of the body, the identity, the time and a one-time
nonce. osp-api answers 401 if the signature is missing or wrong, more than 60 seconds old,
or reused. With `OSP_NONCE_STORE=database` (the production default) the used nonces are kept
in the database for 120 seconds, so a reused one is refused by every osp-api worker and
machine on that database; run as many workers as you like. The format is in
`python/osp-host-signing/README.md`.

Roles come from you on every request, so your app is the single source of truth for who
is in which lab. With `OSP_AUTO_CREATE_LABS=on` (the default) a lab exists as soon as you
first name it. With `off`, create it first (`osp-cli lab create <id>`); until then a role
in it confers nothing.

### Live results polling

With *Live* on, the Results page polls `GET /api/surveys/{id}/results/watermark` and
re-queries only when the watermark changes. The poll is an ordinary signed GET, so your
proxy needs nothing new: no streaming, no longer timeouts, no WebSocket upgrade. Things to
know:

- **Volume.** Each open live page makes one poll per `pollAfterMs` (the server's
  `OSP_LIVE_POLL_MS`, default 10 s): one request through your proxy, one signature check
  and, with `OSP_NONCE_STORE=database`, one nonce insert. 20 viewers at 10 s is 2
  requests a second. The page pauses while its tab is hidden. Under load, raise
  `OSP_LIVE_POLL_MS`: the page uses whatever interval the server sends.
- **Rate limit.** osp-api allows each user a burst of 5 polls, then one a second, per
  worker process. Faster polling gets `429` with `code: "rate_limited"`. Pass the 429
  through unchanged; the page backs off.
- **Caching.** Don't cache the poll in your proxy or CDN. A cached watermark makes the page
  look frozen. Forward osp-api's `Cache-Control` as step 6 says.
- **Audit.** The poll reads no answers and is not audited. An automatic refresh is audited
  as `results.live`: one row per user and query per 15 minutes, plus a new row when the
  query changes. A manual *Show results* stays `results.read`.

### Rotating the key

1. Make a new secret: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. List both keys and restart osp-api: `OSP_IDENTITY_KEYS=host1:<old>,host2:<new>`.
3. Switch the host to sign with `host2`.
4. Remove `host1` from `OSP_IDENTITY_KEYS` and restart osp-api.

### osp-api's own Origin check

osp-api refuses a write whose `Origin` is not allowed (`403`), and a write whose body is
not `application/json` (`415`). This is a second line behind your CSRF check, so keep it
working: forward `Origin` and `Sec-Fetch-Site` (step 3) and set `OSP_PUBLIC_ORIGINS` to
your public origin, for example `OSP_PUBLIC_ORIGINS=https://surveys.example.ac.uk`.
osp-api sees its own address as `http://127.0.0.1:8000`, not yours, so without that
setting every forwarded write is refused.

The allowed `Origin`s are:

- osp-api's own address, as the request gives it (scheme and `Host`);
- `OSP_PUBLIC_ORIGINS`: your public origins. They only pass this check; they do not turn
  on CORS, so no other site's JavaScript can read the API;
- `OSP_ALLOWED_ORIGINS`: the cross-origin opt-in (section 5, item 7). These get CORS
  headers with credentials and pass the check even as `Sec-Fetch-Site: cross-site`.

Any other `Origin`, `Origin: null`, or `Sec-Fetch-Site: cross-site` from a non-allowed
origin is refused. A write without `Origin` (a non-browser client, or a proxy that does not
forward it) is checked on `Sec-Fetch-Site` only.

### The in-process alternative (Python hosts)

A Python host can mount the ASGI app instead of proxying. Then there are no headers and no
secret: you pass a function that says who the request is.

```python
from osp_api.app import create_app
from osp_api.identity import InProcess
from osp_api.serve import Settings, prepare
from osp_app import Identity, build_services
from osp_app.auth import Actor


def who(request):  # a Starlette Request; a sync function runs in a worker thread
    user = my_user_from_session(request)  # your own session lookup
    if user is None:
        return None  # 401
    return Identity(Actor(str(user.pk), osp_roles(user)), user.get_full_name() or None)


settings = Settings.from_env()
services = build_services(prepare(settings), auto_create_labs=settings.auto_create_labs)
osp = create_app(
    builder=services,
    identity=InProcess(who),
    public_origins=("https://surveys.example.ac.uk",),  # your public origin
    trusted_proxies=settings.trusted_proxies,  # OSP_TRUSTED_PROXIES, if TLS ends in a proxy
)
# mount `osp` so that /api/... reaches it, e.g. Starlette Mount("/", app=osp) or your ASGI router
```

The CSRF duty is the same: check your CSRF token **before** the request reaches `osp`
(middleware in front of the mount). osp-api's Origin check compares `Origin` with the
request's own scheme and `Host`, and with `public_origins`. If TLS ends in a proxy in front
of you, the ASGI scope says `http` while the browser's `Origin` says `https`; listing your
public origin in `public_origins` makes that pass without trusting any forwarded scheme
header. (Setting uvicorn `--proxy-headers` also works, but then make sure only your proxy
can reach the server.)

## 4. Participants

Participants never sign in. They hold a bearer resume token instead.

1. Serve `web/runtime/dist/`. Its files go under `/r/` (the build uses `base: '/r/'`). Serve
   `dist/index.html` for `/r/` and for every `/s/{slug}`. The file carries its own
   Content-Security-Policy meta tag.
2. On the same origin, forward the participant API to osp-api's `/api/s/*` and
   `/api/sessions/*` (method, body, `Content-Type`, `Authorization`, and `X-Forwarded-For`,
   see below). Do not sign these, and do strip `X-OSP-*`.

   The app calls `/api/...` by default. If you forward it under another prefix, say so on
   the mount in the `index.html` you serve:
   ```html
   <div id="app" data-api-base="/osp/api"></div>
   ```
   The value must be a path on the same origin (or a URL on the page's own origin), with no
   query or fragment; anything else stops the app with an error. There is no cross-origin
   option: the page's CSP allows `connect-src 'self'` only. URLs the API returns, such as
   the plan URL `/api/s/{slug}/plan/{checksum}`, are mapped onto the prefix by the app.
3. Set `OSP_PARTICIPANT_URL_TEMPLATE` to the public link with a `{slug}` placeholder, for
   example `https://surveys.example.ac.uk/s/{slug}`. The builder shows this link after a
   publish. Without `{slug}` the default `/r/?s={slug}` is used.

### The participant app's icon

`index.html` links `/r/favicon.svg`, `/r/favicon-32.png`, `/r/apple-touch-icon.png` and
`/r/site.webmanifest` (from `web/runtime/public/`), our neutral mark, and names the app
"Survey". To show your institution's icon instead, either replace those files in the
`dist/` you serve (same names and sizes; edit `name` in `site.webmanifest` too), or edit
the `<link rel="icon">`, `apple-touch-icon` and `manifest` tags in the `index.html` you
serve, as for `data-api-base` above. Keep them on your own origin: the page's CSP allows
images and the manifest from `'self'` only.

The browser's toolbar colour (`<meta name="theme-color">`) follows the survey's theme:
the app sets it to the theme's page background once the survey loads, in light or dark
mode as the participant sees it. A theme's logo (`logoAssetId`) does not change the icon.

The public endpoints are:

| Method | Path |
|---|---|
| `POST` | `/api/s/{slug}/sessions` (start) |
| `GET` | `/api/s/{slug}/plan/{checksum}` |
| `GET` | `/api/sessions/resume` |
| `PUT` | `/api/sessions/{session_id}/snapshot` |
| `POST` | `/api/sessions/{session_id}/quota/{node_id}` |
| `POST` | `/api/sessions/{session_id}/submit` |
| `POST` | `/api/sessions/{session_id}/consent` |
| `POST` | `/api/sessions/{session_id}/decline` |
| `POST` | `/api/sessions/{session_id}/withdraw` |

### Rate limits and the participant's address

osp-api rate-limits starts and resumes per client address (starts: a burst of 10, then one
every 6 seconds; resumes: 20, then one a second). Behind your proxy every request comes from
the proxy, so set `OSP_TRUSTED_PROXIES` to its address(es), for example
`OSP_TRUSTED_PROXIES=127.0.0.1,::1` when the proxy runs on the same machine, and make the
proxy append the peer's address to `X-Forwarded-For` (nginx:
`proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`).

- osp-api reads `X-Forwarded-For` only when the direct peer is in `OSP_TRUSTED_PROXIES`.
  From anyone else the header is ignored, so a browser cannot pick its own address.
- It takes the right-most address in the header that is not itself a trusted proxy. The
  left part is whatever the browser claimed and is never used. List every proxy in the
  chain (a load balancer in front of your app too).
- IPv6 addresses count per /64 network, since one network can use any address in it.
- The address is a key in memory for the limiter only; it is never stored or logged.

Without `OSP_TRUSTED_PROXIES` all participants behind your proxy share one budget.

## 5. Security checklist

1. osp-api listens on `127.0.0.1` only. Nothing but your host can reach it.
2. Your proxy forwards an allowlist of headers, so a browser's `X-OSP-*` never arrives.
3. Every builder route checks your session and your CSRF token before it signs or calls in.
4. `OSP_IDENTITY_KEYS` secrets are at least 32 random bytes, kept in your secret store, and
   rotated with two keys listed at once (section 3).
5. Builder pages send `Content-Security-Policy: script-src 'self'` (plus `object-src
   'none'; base-uri 'none'`). The config tag is JSON, not script, so it needs no
   exception. Do not copy the dev host's inline theme script.
6. Every page except `preview-frame` sends `frame-ancestors 'none'`. `preview-frame` sends
   its own policy instead, which `build/manifest.json` gives you exactly as
   `csp["preview-frame"]`. Send it as the page's `Content-Security-Policy` header,
   unchanged:
   ```text
   default-src 'none'; script-src 'self' 'sha256-…'; worker-src blob:;
   style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self';
   connect-src 'none'; frame-src 'self'; object-src 'none'; base-uri 'none';
   form-action 'none'; frame-ancestors 'self'
   ```
   - The page runs the participant app, and with it the survey's researcher hooks, in
     the same sandbox participants get (runtime-design §7a). That sandbox is a `srcdoc`
     iframe that inherits this policy and then narrows itself to `default-src 'none'`,
     and it starts its worker from a `blob:` URL. So the policy allows the sandbox's one
     script by its hash (`'sha256-…'`; it changes only when `web/hooks-sandbox` does, so
     read it from the manifest on each deploy) and `worker-src blob:`. Without those two,
     surveys without hooks still preview, but every hook call fails (the debugger's
     "Researcher hooks" list shows them as failed).
   - `connect-src 'none'`: the preview never calls the API. It gets the compiled plan
     from the builder by `postMessage`, never the API base or a CSRF token.
   - `frame-ancestors 'self'`: the builder shows it in a sandboxed iframe on your origin.
   - Serve the page without the dev host's inline theme script (the policy blocks it).
   - That iframe is `sandbox="allow-scripts allow-same-origin allow-forms"`, and Chrome's
     console warns that a frame with both `allow-scripts` and `allow-same-origin` can
     remove its own sandbox. That is expected, and the reason is the build format. The page
     is Vite's ES-module build. A frame with an opaque origin (no `allow-same-origin`)
     fetches module scripts and their chunks as CORS requests with `Origin: null`, and
     your static files carry no `Access-Control-Allow-Origin`, so the browser blocks them
     and nothing runs. Same origin also lets the builder and the frame address each other's
     `postMessage` to one exact origin, rather than accepting `"null"` and sending with
     `*`. So the sandbox here limits navigation and popups; it does not isolate script. The
     CSP above does that: the page runs only your origin's own build (`script-src 'self'`)
     plus the hooks bootstrap by hash, with no inline script, no `eval`, and
     `connect-src 'none'`, so survey text that reaches the page cannot run as script. The
     researchers' hook code, the only untrusted code, never runs in this document. It runs
     one level down, in the participant app's own `allow-scripts`-only sandbox (opaque
     origin, `default-src 'none'`), as it does for participants. Keep this policy exactly as
     given: loosening `script-src` on this page is what would make the warning matter.
7. Keep everything same-origin. Cross-origin is opt-in: list exact origins in
   `OSP_ALLOWED_ORIGINS` (no wildcard; credentials allowed) and in the page config's
   `allowedOrigins`.
8. Turn `OSP_AUTO_CREATE_LABS` off if your app should not be able to make a lab just by
   naming it; then create labs with `osp-cli lab create`.
9. Keep `OSP_NONCE_STORE=database` (the production default) when you run several osp-api
   workers or machines: they then share the used-nonce list and a captured request cannot
   be replayed against another worker. `memory` is per process and only safe with one.
10. The config is escaped with `json_script` (or `<` for `<`), never `|safe`.

## 6. A minimal Django example

`settings.py` (your names, not ours):

```python
OSP_BUILD_DIR = BASE_DIR / "osp-builder"  # a copy of web/builder/build/
OSP_STATIC = "/static/osp/"  # where that folder is served
OSP_API_URL = "http://127.0.0.1:8000"
OSP_KEY_ID, OSP_SECRET = env("OSP_HOST_KEY").split(":", 1)  # one OSP_IDENTITY_KEYS entry
```

and osp-api runs with `OSP_PUBLIC_ORIGINS=https://<your site>` (the proxy forwards
`Origin`) and `OSP_TRUSTED_PROXIES=127.0.0.1` (Django calls it from the same machine).

`views.py`:

```python
import json

import httpx
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from osp_host_signing import sign_identity_headers

MANIFEST = json.loads((settings.OSP_BUILD_DIR / "manifest.json").read_text())["pages"]
UPSTREAM = httpx.Client(base_url=settings.OSP_API_URL, timeout=60)
LINKS = {
    "list": "/research/",
    "editor": "/research/surveys/{id}/",
    "flow": "/research/surveys/{id}/flow/",
    "settings": "/research/surveys/{id}/settings/",
    "appearance": "/research/surveys/{id}/appearance/",
    "results": "/research/surveys/{id}/results/",
    "themes": "/research/appearance/",
    "profile": "/research/profile/",
    "previewFrame": "/research/preview-frame/",
}
REQUEST_HEADERS = ("content-type", "accept", "origin", "sec-fetch-site")
RESPONSE_HEADERS = ("content-type", "content-disposition", "cache-control")


def osp_roles(user):
    """Your own rule: lab id -> "owner", "editor" or "viewer"."""
    return {m.lab.slug: m.role for m in user.lab_memberships.all()}


@login_required
def osp_page(request, page, survey_id=None):
    if page not in MANIFEST:
        raise Http404
    config = None
    if page != "preview-frame":
        config = {
            "version": 1,
            "apiBase": "/osp/api",
            "links": LINKS,
            "csrf": {"header": "X-CSRFToken", "token": get_token(request)},
            "onUnauthenticated": {"redirect": settings.LOGIN_URL},
            "user": {"displayName": request.user.get_full_name() or request.user.get_username()},
        }
        if survey_id is not None:
            config["surveyId"] = survey_id
    context = {"files": MANIFEST[page], "static": settings.OSP_STATIC, "config": config}
    return render(request, "osp/page.html", context)


def osp_api_proxy(request, rest):
    # Django's CsrfViewMiddleware has already checked X-CSRFToken on writes.
    if not request.user.is_authenticated:
        return JsonResponse({"code": "unauthenticated", "message": "Sign in first."}, status=401)
    path = "/api/" + request.get_full_path().removeprefix("/osp/api/")
    body = request.body
    headers = {k: v for k, v in request.headers.items() if k.lower() in REQUEST_HEADERS}
    headers.update(
        sign_identity_headers(
            key_id=settings.OSP_KEY_ID,
            secret=settings.OSP_SECRET,
            method=request.method,
            path=path,
            body=body,
            user_id=str(request.user.pk),
            roles=osp_roles(request.user),
            display_name=request.user.get_full_name() or None,
        )
    )
    r = UPSTREAM.request(request.method, path, content=body or None, headers=headers)
    response = HttpResponse(r.content, status=r.status_code)
    for name in RESPONSE_HEADERS:
        if name in r.headers:
            response[name] = r.headers[name]
    return response
```

`urls.py`:

```python
from django.urls import path

from . import views

urlpatterns = [
    path("research/", views.osp_page, {"page": "list"}),
    path("research/surveys/<str:survey_id>/", views.osp_page, {"page": "editor"}),
    path("research/surveys/<str:survey_id>/flow/", views.osp_page, {"page": "flow"}),
    path("research/surveys/<str:survey_id>/settings/", views.osp_page, {"page": "settings"}),
    path("research/surveys/<str:survey_id>/appearance/", views.osp_page, {"page": "appearance"}),
    path("research/surveys/<str:survey_id>/results/", views.osp_page, {"page": "results"}),
    path("research/appearance/", views.osp_page, {"page": "themes"}),
    path("research/profile/", views.osp_page, {"page": "profile"}),
    path("research/preview-frame/", views.osp_page, {"page": "preview-frame"}),
    path("osp/api/<path:rest>", views.osp_api_proxy),
]
```

`templates/osp/page.html`:

```django
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Surveys</title>
    <link rel="icon" href="{{ static }}favicon.svg" type="image/svg+xml">
    <link rel="icon" href="{{ static }}favicon-32.png" sizes="32x32" type="image/png">
    <link rel="apple-touch-icon" href="{{ static }}apple-touch-icon.png">
    <link rel="manifest" href="{{ static }}site.webmanifest">
    {% for href in files.css %}<link rel="stylesheet" href="{{ static }}{{ href }}">{% endfor %}
    {% for href in files.preload %}<link rel="modulepreload" href="{{ static }}{{ href }}">{% endfor %}
  </head>
  <body>
    <div id="osp"></div>
    {% if config %}{{ config|json_script:"osp-config" }}{% endif %}
    <script type="module" src="{{ static }}{{ files.js }}"></script>
  </body>
</html>
```

Add the CSP and `frame-ancestors` headers from section 5 (for example with
`django-csp`), and the participant routes from section 4. Django answers a bad CSRF token
with its own 403 page, which the builder shows as an access message.

## 7. Running the container image

`deploy/Dockerfile` builds one image with everything in section 1 except the database:
`osp-api` and `osp-cli`, the participant app, the builder page files, the engine bundle
(reproducibility packages) and the simulator with the Node binary that runs it (the
preview's "run simulation"). Build it from the repository root:

```sh
docker build -f deploy/Dockerfile -t osp-api .
```

Base images are pinned by version (`python:3.14.8-slim-trixie`, `node:24.12.0-trixie-slim`,
`ghcr.io/astral-sh/uv:0.11.23`; pnpm 12.14.0), set as build arguments at the top of the
file. The image runs as an unprivileged user (`osp`, uid 10001), listens on `$PORT` (default
8000), and has a `HEALTHCHECK` on `/api/health`.

Run it next to a Postgres database:

```sh
docker run -d --name osp-api --network <private network> \
  -e DATABASE_URL=postgres://osp:<password>@db:5432/osp \
  -e OSP_STORE_KEYS=k1:<key from `docker run --rm osp-api osp-cli gen-key`> \
  -e OSP_IDENTITY_KEYS=host1:<at least 32 random bytes> \
  -e OSP_PUBLIC_ORIGINS=https://surveys.example.ac.uk \
  -e OSP_TRUSTED_PROXIES=<your proxy's address> \
  osp-api
```

| Setting | In the image |
|---|---|
| `OSP_ENV` | `production` (so `OSP_DATABASE_URL` and `OSP_STORE_KEYS` are required) |
| `OSP_DATABASE_URL` | taken from `DATABASE_URL` when unset, as a PaaS links it (`postgres://…` works as it is, section 1) |
| `PORT` / `OSP_PORT` | `PORT` wins (a PaaS sets it), else `OSP_PORT`, else 8000 |
| `OSP_HOST` | `0.0.0.0`: inside a container the API must listen on its interface |
| `OSP_DATA_DIR` | `/data`, a volume, owned by `osp` |
| `OSP_PARTICIPANT_DIR` | `/app/web/runtime`: the participant app at `/r/` and `/s/{slug}` |
| `OSP_BUILDER_DIR` | `/app/web/builder`: the builder files at `/builder/` |
| `OSP_ENGINE_BUNDLE`, `OSP_SIM_CLI`, `OSP_NODE` | the bundled engine, simulator and Node |
| `OSP_OSF_API_URL`, `OSP_OSF_FILES_URL` | where the [preregistration upload](preregistration.md#uploading-to-osf) talks to OSF (default: osf.io; set the test servers to rehearse) |

Everything else is as in section 1. Set `OSP_PARTICIPANT_URL_TEMPLATE` to your public
participant link.

**Migrations.** `osp-api serve` migrates the database to the latest schema before it starts
listening, so a plain start is enough with one container. With several containers on one
database, run the migration once as a release step, before the new containers start:
`docker run --rm <same env> osp-api init` (Dokku: `app.json` `scripts.dokku.predeploy`;
Heroku: a `release` process). `init` migrates and exits.

**Volumes.** With Postgres the container keeps no state, and `/data` can stay empty. For a
single machine without Postgres, use SQLite on the volume:
`-v osp-data:/data -e OSP_DATABASE_URL=sqlite:////data/osp.db`, with one container only.

**Keep the API private.** `OSP_HOST=0.0.0.0` makes it listen on the container's own
interface, not on the internet. Section 5, item 1 still holds: put the container on a
private network that only your host can reach, and don't publish its port to the public
internet (`-p 127.0.0.1:8000:8000` at most, or no `-p` with a shared Docker network). On
Dokku, give the app no domain and turn its proxy off (`dokku proxy:disable osp-api`).

**What your host serves.** The image serves the participant app itself: forward
`/r/*`, `/s/*`, `/api/s/*` and `/api/sessions/*` to it unsigned (section 4), and the
builder API under your prefix signed (section 3). For the builder pages, your host still
renders each page behind its sign-in (section 2), and needs the files: proxy your static
prefix (say `/static/osp/`) to the container's `/builder/`, and read `manifest.json` from
`http://<container>:8000/builder/manifest.json` at start-up, or copy the folder out of the
image (`docker cp $(docker create osp-api):/app/web/builder ./osp-builder`). The `/builder/`
files are static JavaScript, CSS and icons; they hold no data and need no sign-in.

**Upgrades.** Rebuild from a newer commit and restart. The host's copy of the builder
files must come from the same image, as the page bundles and the API move together.
