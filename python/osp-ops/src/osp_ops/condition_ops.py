"""`set_condition`: set, replace or clear a condition from an AST or from text."""

from __future__ import annotations

import copy
from typing import Literal

import osp_expr
from osp_expr.ast import EXPR_ADAPTER
from pydantic import JsonValue, ValidationError

from .doc import NODE, QUESTION, QUOTA, VARIABLE, get, locate
from .registry import Ctx, Invocation, OpError, Params, diag, op

type ExprField = Literal["showIf", "constraint", "if", "when", "expr"]

# Which expression fields each kind of target has; the first is the default.
FIELDS: dict[str, tuple[str, ...]] = {
    "question": ("showIf", "constraint"),
    "branch": ("if",),
    "quota": ("when",),
    "computed": ("expr",),
}
REQUIRED = frozenset({"if", "when", "expr"})
MAX_TEXT = 20_000


class SetCondition(Params):
    target: str  # question, branch node, quota or computed variable id
    condition: str | dict[str, JsonValue] | None  # text, AST (JSON) or None to clear
    field: ExprField | None = None  # default: showIf / if / when / expr by target


def to_ast(condition: str | dict[str, JsonValue]) -> JsonValue:
    """Condition text or AST -> canonical AST JSON. Raises OpError with diagnostics."""
    if isinstance(condition, str):
        if len(condition) > MAX_TEXT:
            raise OpError("op.params", f"condition text is over {MAX_TEXT} characters")
        res = osp_expr.parse(condition)
        if res.expr is None:
            ds = [
                diag("op.expr_syntax", f"{d.message} [{d.code}] at {d.start}-{d.end}", "/condition")
                for d in res.diagnostics
            ] or [diag("op.expr_syntax", "condition does not parse", "/condition")]
            raise OpError(ds[0].code, ds[0].message, ds[0].pointer, *ds[1:])
        expr = res.expr
    else:
        try:
            expr = EXPR_ADAPTER.validate_python(condition)
        except ValidationError as err:
            msg = str(err.errors(include_url=False, include_input=False)[0]["msg"])[:300]
            raise OpError("op.params", f"not an expression AST: {msg}", "/condition") from None
    return EXPR_ADAPTER.dump_python(expr, mode="json")


@op("set_condition", SetCondition, label="Set condition", area="conditions")
def set_condition(ctx: Ctx, p: SetCondition) -> Invocation:
    """Set a question's `showIf`/`constraint`, a branch's `if`, a quota's `when` or a
    computed variable's `expr`. Text is parsed with osp-expr (`age >= 18 and
    answered(q2)`); a blank string or None clears an optional condition."""
    loc = locate(ctx, p.target, QUESTION, NODE, QUOTA, VARIABLE)
    obj = get(ctx.doc, loc.path)
    if loc.kind == QUESTION:
        kind = "question"
    elif loc.kind == QUOTA:
        kind = "quota"
    else:
        kind = str(obj.get("type") if loc.kind == NODE else obj.get("kind"))
    fields = FIELDS.get(kind)
    if fields is None:
        raise OpError("op.not_allowed", f"'{p.target}' ({kind}) has no condition", loc.pointer)
    field = p.field or fields[0]
    if field not in fields:
        raise OpError(
            "op.not_allowed",
            f"'{p.target}' ({kind}) has no '{field}'; it has {', '.join(fields)}",
            loc.pointer,
        )
    cond = p.condition
    if isinstance(cond, str) and not cond.strip():
        cond = None
    absent = field not in obj
    old = copy.deepcopy(obj.get(field))
    if cond is None:
        if field in REQUIRED:
            raise OpError("op.not_allowed", f"'{field}' is required and cannot be cleared")
        obj.pop(field, None)
    else:
        obj[field] = to_ast(cond)
    params: dict[str, JsonValue] = {"target": p.target, "property": field}
    params.update({"unset": True} if absent else {"value": old})
    return Invocation(op="set_property", params=params)
