# osp-mcp

**Layer:** L6. Imports only packages in lower layers (enforced by `uv run lint-imports`). I/O allowed (L4 and up).

**Job:** Thin MCP server shell over `osp-app`, so AI agents can draft surveys by op id (task AI1). User docs: `docs/ai-drafting.md`.

Internal package; not published.

## Running it

```sh
uv run osp-mcp          # serve MCP over stdio (what an MCP client launches)
uv run osp-mcp tools    # print the tools and descriptions; needs no database
```

Settings (environment): `OSP_DATABASE_URL` and `OSP_STORE_KEYS` as for `osp-api`/`osp-cli`;
`OSP_MCP_USER`, `OSP_MCP_LAB`, `OSP_MCP_ROLE` (default `editor`), `OSP_MCP_NAME` say which
researcher the server acts as (no sign-in here, plan P: the launcher vouches, as a host does);
`OSP_MCP_BUILDER_URL` (with `{id}`) is where the builder opens a survey.

## Modules

- `drafting.py`: `Drafting` = the tools' bodies over `osp_app.Builder`, returning JSON;
  `DraftingError` for every refusal (code, message, diagnostics). The guardrails live here:
  `ALLOWED_COMMANDS` (the only app commands dispatched: create, list, get, apply ops, undo,
  redo, history, preview plan), `FORBIDDEN_ACTIONS` (publish, delete, export, response
  delete: `check_guardrails()` proves no allowed command needs one), `BLOCKED_OPS`
  (`set_hooks`, `apply_patch`). `outline()` is the compact survey map every edit returns.
- `recipes.py`: pure. Typed requests (`PageSpec`, `QuestionSpec`, `ChoiceSpec`, `RowSpec`)
  become ordinary op invocations (`add_block` + `insert_flow_node`, `add_page` with a whole
  page object, `add_question` with a whole question object; `showIf` text is parsed with
  osp-expr into the object). osp-ops validates them like any other edit.
- `server.py`: `MCPServer` wiring (16 tools, read-only annotations on the readers),
  `Settings.from_env`, `open_services`, `drafting_for`, `main`.

## Tests

`tests/`: recipes (pure), drafting over a SQLite store (build, validate, preview, undo,
all-or-nothing, refusals with diagnostics), guardrails (allowlist vs the live registry, tool
names, viewer role), and `test_mcp_client.py`: the official `mcp` client in-process and as a
stdio subprocess, replaying the worked example from `docs/ai-drafting.md`.
