# contract/

The only meeting point of `python/` and `web/`.

- `openapi.json` is generated from the FastAPI app in `osp-api` by `make contract`.
  It is committed. Never edit it by hand. `make contract-check` (part of `make check`)
  fails if it, or the TS client generated from it, is stale.
