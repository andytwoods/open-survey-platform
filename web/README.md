# web/

pnpm workspace (pnpm version pinned by `packageManager` in `package.json`).

| Package | Job |
|---|---|
| `builder` | Vite multi-page build: one JS entry per page plus `manifest.json` (see `builder/README.md`). Thin UI: no survey logic. |
| `api-client` | TS client generated from `/contract/openapi.json`. Never edit `src/schema.d.ts` by hand. |
| `ui-components` | Shared Svelte components. Must not import `api-client`. |
| `ops` | `@osp/ops`: every survey edit op of `python/osp-ops` in TypeScript (see `ops/README.md`). Imports only `engine`. |

Boundaries are enforced by dependency-cruiser (`.dependency-cruiser.cjs`): `builder`
may import `api-client` and `ui-components`, `ui-components` must not import
`api-client`, and nothing imports `builder`.

```sh
pnpm -C web install
pnpm -C web build   # page entries + manifest.json in web/builder/build
pnpm -C web check   # svelte-check, eslint, dependency-cruiser
pnpm -C web test    # vitest
```
