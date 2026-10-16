# osp-expr

**Layer:** L0. Imports only packages in lower layers (enforced by `uv run lint-imports`). No I/O: no network, database, clock or global randomness.

**Job:** Condition/expression language: AST, parser/printer for the text syntax, evaluator (per `planning/semantics.md` §3). Pure; no workspace dependencies.

| Module | What |
|---|---|
| `osp_expr.ast` | Frozen pydantic nodes with a `kind` discriminator; `Expr` union, `expr_to_json` / `expr_from_json` |
| `osp_expr.syntax` | `parse(text) -> ParseResult` (never raises; diagnostics carry offsets), `to_text(expr)` (canonical) |
| `osp_expr.evaluate` | `evaluate(expr, env)`, `evaluate_condition(expr, env)` per semantics §2-§3 |
| `osp_expr.static` | `references(expr)`, `typecheck(expr, types)` |

Text syntax, e.g. `q3 > 5 and contains(q7, "b")`, `not answered(age) or age >= 18`,
`(score1 + score2) / 2 >= 3.5`. Operators by precedence: `or`, `and`, `not`,
`== != < <= > >=` (no chaining), `+ -`, `* /`. Literals: `5`, `-3`, `2.50`, `"text"`, `true`, `false`, `null`.
Full grammar in `syntax.py`.

Internal package; not published.
