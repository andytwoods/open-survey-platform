"""The seam between the survey model and `osp-expr` (L0).

Every expression field in the model is C1's AST (`osp_expr.ast.Expr`, JSON objects with
a `kind` discriminator; references are `{"kind": "ref", "id": "<stable id>"}`), under one
of two aliases:

- `Condition`: must evaluate to true/false (`showIf`, `constraint`, branch `if`, quota
  `when`). The validator type-checks it with `condition=True`; at runtime a `null`
  condition counts as false (semantics.md §3).
- `Expression`: any value (computed-variable `expr`).

Both serialise identically; the alias only says how the field is checked and edited.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping

from osp_expr.ast import (
    And,
    Answered,
    Arith,
    Compare,
    Contains,
    Expr,
    IntLit,
    Not,
    Or,
    Ref,
    TextLit,
)
from pydantic import BaseModel

try:  # C1's static checks; land on main after the AST (osp_expr/static.py).
    from osp_expr.static import typecheck as _typecheck
except ImportError:  # pragma: no cover - depends on merge order
    _typecheck = None

type Expression = Expr
type Condition = Expr

# osp-expr codes this package reports itself (as `ref.*`), so they are not repeated.
_OWN_CHECKS = frozenset({"unknown-question", "unknown-type"})


def _children(node: BaseModel) -> Iterator[BaseModel]:
    match node:
        case Compare(left=left, right=right) | Arith(left=left, right=right):
            yield left
            yield right
        case And(args=args) | Or(args=args):
            yield from args
        case Not(arg=arg):
            yield arg
        case Answered(ref=ref):
            yield ref
        case Contains(ref=ref, value=value):
            yield ref
            yield value


def references(expr: Expression) -> list[str]:
    """Ids referenced by `expr`, in first-seen order, without duplicates."""
    seen: dict[str, None] = {}
    stack: list[BaseModel] = [expr]
    while stack:
        node = stack.pop()
        if isinstance(node, Ref):
            seen.setdefault(node.id, None)
        stack.extend(reversed(list(_children(node))))
    return list(seen)


def code_tests(expr: Expression) -> list[tuple[str, str, int | str]]:
    """Literal choice-code tests in `expr`: `(pointer suffix of the literal, ref id, code)`
    for `ref == code`, `ref != code` (either order) and `contains(ref, code)`."""
    out: list[tuple[str, str, int | str]] = []
    stack: list[tuple[BaseModel, str]] = [(expr, "")]
    while stack:
        node, path = stack.pop()
        match node:
            case Compare(op="==" | "!=", left=Ref(id=rid), right=IntLit() | TextLit() as lit):
                out.append((path + "/right", rid, lit.value))
            case Compare(op="==" | "!=", left=IntLit() | TextLit() as lit, right=Ref(id=rid)):
                out.append((path + "/left", rid, lit.value))
            case Contains(ref=Ref(id=rid), value=IntLit() | TextLit() as lit):
                out.append((path + "/value", rid, lit.value))
        stack.extend(reversed([(c, path + s) for s, c in _children_with_paths(node)]))
    return out


def _children_with_paths(node: BaseModel) -> Iterator[tuple[str, BaseModel]]:
    match node:
        case Compare(left=left, right=right) | Arith(left=left, right=right):
            yield "/left", left
            yield "/right", right
        case And(args=args) | Or(args=args):
            for i, a in enumerate(args):
                yield f"/args/{i}", a
        case Not(arg=arg):
            yield "/arg", arg
        case Contains(value=value):
            yield "/value", value


def typecheck(expr: Expression, env: Mapping[str, str], *, boolean: bool) -> list[tuple[str, str]]:
    """Type errors in `expr` as `(pointer suffix into the expression, message)` pairs.

    `env` maps referenced ids to value types (`integer`, `decimal`, `text`, `single`,
    `multi`, `date`); ids missing from it are left to the reference checks. `boolean`
    says the expression is a condition. Empty until `osp_expr.static` is available.
    """
    if _typecheck is None:
        return []
    out: list[tuple[str, str]] = []
    for d in _typecheck(expr, env, condition=boolean):
        if d.code in _OWN_CHECKS:
            continue
        path = d.path if d.path and d.path != "/" else ""
        out.append((path, f"{d.message} [{d.code}]"))
    return out
