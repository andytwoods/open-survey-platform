# python/

uv workspace members. The workspace root is `/pyproject.toml` at the repo root, so
run `uv sync` and `uv run ...` from the repo root.

Each package lives in `python/<name>/` with a `src/<module>/` layout and a README
that states its layer. Layers are enforced by import-linter (`uv run lint-imports`).
See `/AGENTS.md` §2.
