"""Static helpers: ``references`` and ``typecheck``.

``typecheck`` takes the question types from semantics.md §2 (``integer``, ``decimal``,
``text``, ``single``, ``multi``, ``date``) and reports diagnostics with a JSON-pointer
``path`` into the AST. A ``single`` answer is a choice code, which may be a number or
text (§2), so it is accepted wherever a number or text is.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping

from .ast import (
    And,
    Answered,
    Arith,
    BoolLit,
    Compare,
    Contains,
    DecLit,
    Expr,
    If,
    IntLit,
    Not,
    NullLit,
    Or,
    Ref,
    TextLit,
)
from .diagnostics import Diagnostic

QUESTION_TYPES = frozenset({"integer", "decimal", "text", "single", "multi", "date"})


def children(node: Expr) -> Iterator[tuple[str, Expr]]:
    """Yield ``(json_pointer_suffix, child)`` for each direct child of ``node``."""
    match node:
        case Compare(left=left, right=right) | Arith(left=left, right=right):
            yield "/left", left
            yield "/right", right
        case And(args=args) | Or(args=args):
            for i, a in enumerate(args):
                yield f"/args/{i}", a
        case Not(arg=a):
            yield "/arg", a
        case Answered(ref=r):
            yield "/ref", r
        case Contains(ref=r, value=v):
            yield "/ref", r
            yield "/value", v
        case If(cond=c, then=t, else_=e):
            yield "/cond", c
            yield "/then", t
            yield "/else", e


def references(expr: Expr) -> tuple[str, ...]:
    """Question ids used by ``expr``, de-duplicated, in first-occurrence order."""
    seen: dict[str, None] = {}
    stack: list[Expr] = [expr]
    while stack:
        node = stack.pop()
        if isinstance(node, Ref):
            seen.setdefault(node.id, None)
        stack.extend(reversed([c for _, c in children(node)]))
    return tuple(seen)


# Static types: number, text, code (single choice: number or text), multi, date,
# boolean, null, any (unknown; suppresses follow-on errors).
_FROM_QUESTION = {
    "integer": "number",
    "decimal": "number",
    "text": "text",
    "single": "code",
    "multi": "multi",
    "date": "date",
}


def _compatible_eq(a: str, b: str) -> bool:
    if "any" in (a, b) or a == b:
        return True
    return {a, b} in ({"code", "number"}, {"code", "text"})


def _branch_type(a: str, b: str) -> str | None:
    """The type of ``if(c, a, b)`` when the branch types are compatible, else None.
    ``null`` fits any branch type; a number and a code (single choice) give a code."""
    if a == b:
        return a
    if "any" in (a, b):
        return "any"
    if a == "null":
        return b
    if b == "null":
        return a
    if {a, b} in ({"code", "number"}, {"code", "text"}):
        return "code"
    return None


def _is_zero(node: Expr) -> bool:
    return isinstance(node, IntLit | DecLit) and node.value == 0


def _orderable(a: str, b: str) -> bool:
    if "any" in (a, b):
        return True
    pair = {a, b}
    return pair <= {"number", "code"} or pair == {"date"}


class _Checker:
    def __init__(self, types: Mapping[str, str]):
        self.types = types
        self.diags: list[Diagnostic] = []

    def add(self, code: str, message: str, path: str, severity: str = "error") -> None:
        self.diags.append(
            Diagnostic(code=code, message=message, path=path or "/", severity=severity)  # type: ignore[arg-type]
        )

    def ref_type(self, ref: Ref, path: str) -> str:
        qtype = self.types.get(ref.id)
        if qtype is None:
            self.add("unknown-question", f"no question with id '{ref.id}'", path)
            return "any"
        if qtype not in _FROM_QUESTION:
            self.add("unknown-type", f"question '{ref.id}' has unknown type '{qtype}'", path)
            return "any"
        return _FROM_QUESTION[qtype]

    def check(self, node: Expr, path: str) -> str:
        match node:
            case IntLit() | DecLit():
                return "number"
            case TextLit():
                return "text"
            case BoolLit():
                return "boolean"
            case NullLit():
                return "null"
            case Ref():
                return self.ref_type(node, path)
            case Answered(ref=r):
                self.ref_type(r, path + "/ref")
                return "boolean"
            case Contains(ref=r, value=v):
                rt = self.ref_type(r, path + "/ref")
                vt = self.check(v, path + "/value")
                if rt not in ("multi", "any"):
                    self.add(
                        "contains-non-multi",
                        f"contains() needs a multi-choice question; '{r.id}' is {rt}",
                        path + "/ref",
                    )
                if vt == "null":
                    self.add(
                        "null-comparison",
                        "contains(q, null) is always false; use answered()",
                        path + "/value",
                        "warning",
                    )
                elif vt not in ("number", "text", "code", "any"):
                    self.add(
                        "type-mismatch",
                        f"contains() looks for a choice code (number or text), not {vt}",
                        path + "/value",
                    )
                return "boolean"
            case Compare(op=op, left=left, right=right):
                lt = self.check(left, path + "/left")
                rt = self.check(right, path + "/right")
                if "null" in (lt, rt):
                    self.add(
                        "null-comparison",
                        "comparing with null is always false (even null == null); use answered()",
                        path,
                        "warning",
                    )
                elif op in ("==", "!="):
                    if not _compatible_eq(lt, rt):
                        self.add("type-mismatch", f"cannot compare {lt} {op} {rt}", path)
                elif not _orderable(lt, rt):
                    self.add(
                        "type-mismatch",
                        f"'{op}' needs two numbers or two dates, not {lt} and {rt}",
                        path,
                    )
                return "boolean"
            case Arith(op=op, left=left, right=right):
                lt = self.check(left, path + "/left")
                rt = self.check(right, path + "/right")
                if "null" in (lt, rt):
                    self.add(
                        "null-arithmetic", "arithmetic with null is always null", path, "warning"
                    )
                    return "any"
                for side, t in (("left", lt), ("right", rt)):
                    if t not in ("number", "code", "any"):
                        self.add(
                            "type-mismatch",
                            f"'{op}' needs numbers; {side} is {t}",
                            f"{path}/{side}",
                        )
                if op == "/" and _is_zero(right):
                    self.add(
                        "division-by-zero",
                        "dividing by the constant 0 always gives null",
                        path + "/right",
                    )
                return "number"
            case And(args=args) | Or(args=args):
                word = "and" if isinstance(node, And) else "or"
                for i, a in enumerate(args):
                    self.boolean_operand(a, f"{path}/args/{i}", f"'{word}'")
                return "boolean"
            case Not(arg=a):
                self.boolean_operand(a, path + "/arg", "'not'")
                return "boolean"
            case If(cond=c, then=t, else_=e):
                self.boolean_operand(c, path + "/cond", "if()")
                tt = self.check(t, path + "/then")
                et = self.check(e, path + "/else")
                joined = _branch_type(tt, et)
                if joined is None:
                    self.add(
                        "type-mismatch",
                        f"if() branches must have compatible types, not {tt} and {et}",
                        path,
                    )
                    return "any"
                return joined
        return "any"

    def boolean_operand(self, node: Expr, path: str, where: str) -> None:
        t = self.check(node, path)
        if t not in ("boolean", "any"):
            self.add("not-boolean", f"{where} needs a condition, not {t}", path)


def typecheck(expr: Expr, types: Mapping[str, str], *, condition: bool = True) -> list[Diagnostic]:
    """Type-check ``expr`` given ``types`` (question id -> semantics §2 type).

    With ``condition=True`` the whole expression must be a condition (true/false).
    """
    checker = _Checker(types)
    try:
        result = checker.check(expr, "")
    except RecursionError:
        return [Diagnostic(code="too-deep", message="expression is nested too deeply", path="/")]
    if condition and result not in ("boolean", "any"):
        checker.add("not-boolean", f"a condition must be true/false, not {result}", "")
    return checker.diags


__all__ = ["QUESTION_TYPES", "children", "references", "typecheck"]
