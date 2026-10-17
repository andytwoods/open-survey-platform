# @osp/builder: the builder pages

The researcher-facing builder, as **separate pages** (planning/pages-split.md F1–F3). Each
page is its own JS entry; a host (a university's Django or Rails app, a reverse proxy with
single sign-on…) serves each one at whatever URL it likes, behind its own login. There is
no sign-in UI here: the host owns accounts, sessions and sign-out.

## Pages

| Page | Entry | Dev URL | Shows |
|---|---|---|---|
| `list` | `src/pages/list.ts` | `/` | Your surveys; create one |
| `editor` | `src/pages/editor.ts` | `/surveys/{id}` | Questions: outline, canvas, properties, JSON |
| `flow` | `src/pages/flow.ts` | `/surveys/{id}/flow` | Blocks, branching, randomisation |
| `settings` | `src/pages/settings.ts` | `/surveys/{id}/settings` | Saving, retention, consent, languages |
| `appearance` | `src/pages/appearance.ts` | `/surveys/{id}/appearance` | The survey's theme |
| `themes` | `src/pages/themes.ts` | `/appearance` | The lab's theme library |
| `preview-frame` | `src/pages/preview-frame.ts` | `/preview-frame` | One preview device frame (iframe only) |

Dev-only entries (`src/pages/dev/*`, not in the production build): `/?mock` (the shell over
static mock data) and the galleries `/dev/cards`, `/dev/choices`, `/dev/components`,
`/dev/conditions`, `/dev/properties`, `/dev/themes`, `/dev/widgets`.

Every entry exports `mount(el, config)` and also mounts itself when the document has
`<div id="osp">` and a config tag. A host page is just:

```html
<div id="osp"></div>
<script type="application/json" id="osp-config">{"version": 1, "apiBase": "/osp/api", "surveyId": "…", "links": {…}}</script>
<script type="module" src="/static/osp/assets/editor-1a2b3c.js"></script>
```

plus the page's CSS and preload links from the manifest. Escape `<` in the JSON as
`<` (Django: `{{ config|json_script:"osp-config" }}` does this).

## Config (`OspPageConfig`, `src/lib/host/config.ts`)

```ts
interface OspPageConfig {
  version: 1;
  apiBase: string;                 // replaces the `/api` prefix of every call, e.g. "/osp/api"
  surveyId?: string;               // required on editor, flow, settings, appearance
  tenantId?: string;               // which lab, if the user is in several (a selector only)
  links: {                         // URL templates; {id} is replaced (URL-encoded)
    list: string; editor: string; flow: string; settings: string;
    appearance: string; themes: string; previewFrame: string;
  };
  csrf?: { header: string; token?: string; cookie?: string }; // sent on POST/PUT/PATCH/DELETE
  onUnauthenticated?: { redirect: string } | 'reload';        // after a 401; default 'reload'
  user?: { displayName?: string };  // shown in the header (else GET /api/me's displayName)
  allowedOrigins?: string[];        // exact origins apiBase/links may use besides the page's
}
```

Validated at run time before anything runs: known keys only, types, lengths, `{id}` in
the survey links, and `apiBase`, every link and the sign-in redirect must be same-origin
unless their origin is in `allowedOrigins`. A bad config is rejected: the element shows the
errors and `mount` throws `OspConfigError`. The preview frame takes only `{"version": 1}`
(or no config tag): it never gets the API base or a CSRF token.

Behaviour the host can rely on:

- **Navigation** (`src/lib/host/links.ts`) is a full page load to the host's template.
  Before leaving, the page sends buffered text and waits for the save queue (at most 10 s,
  then asks); `beforeunload` warns while edits are unsaved. Undo history is per page.
- **401**: writes stop (the pending edits stay queued on the page) and a banner says the
  session ended, linking to `onUnauthenticated.redirect?next=<this page>`. With `'reload'`
  the page reloads once so the host's login runs, only if nothing is pending and it has not
  done so in the last 5 minutes; otherwise the banner offers a reload. Never a loop.
- **403**: a separate "you don't have access to this lab" banner.
- **Identity**: `GET /api/me` (`{userId, displayName?, memberships}`) gives the header name
  and the lab for a new survey (`tenantId` from config, else the only membership, else the
  user picks).
- **Preview**: the device frames are the `previewFrame` page in sandboxed iframes; the two
  sides talk only by `postMessage`, checking origin, source window and schema
  (`src/lib/preview/bridge.ts`).

## Build and manifest

`pnpm -C web build` (or `make web-build`) writes `build/`: hashed page entries and shared
chunks under `assets/`, and `build/manifest.json`:

```json
{ "version": 1,
  "pages": { "editor": { "js": "assets/editor-….js", "css": ["assets/….css"], "preload": ["assets/….js"] } } }
```

Paths are relative to `build/` (the build uses `base: './'`, so it can live under any
static URL). For each page write its `css` as stylesheets, its `preload` as
`modulepreload` links and its `js` as a module script. `scripts/check-build.mjs` (run by
`make web-build`) fails unless the manifest lists exactly the seven pages, every file
exists and each entry exports `mount`. `OSP_DEV_PAGES=1 vite build` adds the dev pages
(the e2e tests use it).

## Dev host

`vite dev` and `vite preview` serve the pages at the dev URLs above with a dev config
(`dev-host/`), proxying `/api`, `/s/` and `/r/` to osp-api (`OSP_API_URL`, default
`http://127.0.0.1:8000`). The dev config's CSRF scheme is osp-api's current cookie
(`X-CSRF-Token` / `__Host-osp_csrf`); in `?mock` mode its links stay in mock mode.

Checks: `pnpm -C web check` (svelte-check, eslint, dependency-cruiser), `pnpm -C web test`
(vitest), `make web-e2e` (Playwright; all sign-in glue is in `e2e/fixtures.ts`).
