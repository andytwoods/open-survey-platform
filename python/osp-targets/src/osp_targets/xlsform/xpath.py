"""osp-expr AST → XLSForm XPath, keeping our missing-value rules (semantics.md §3).

XPath on an empty node does not behave like our ``null``: ``'' = ''`` is true and
``'' != 5`` is true, but every comparison with ``null`` is false for us. So each
comparison is guarded: it is true only if every reference in its operands has a value
(``string-length(${x}) > 0``) and every divisor is non-zero (division by zero gives
``null``, open question 1). Arithmetic in a ``calculate`` is wrapped as
``if(<guards>, value, '')`` so ``null`` in gives ``null`` (empty) out.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from osp_expr.ast import (
    And,
    Answered,
    Arith,
    BoolLit,
    Compare,
    Contains,
    DecLit,
    Expr,
    IntLit,
    Not,
    NullLit,
    Or,
    Ref,
    TextLit,
)

TRUE = "true()"
FALSE = "false()"

# Types whose stored value is a code: compare it to an integer literal as text, so the
# code "01" is not equal to 1 (codes are text in XForms, C2-8).
_CODE_TYPES = frozenset({"single", "multi", "assigned"})


def string_literal(s: str) -> str:
    """An XPath string literal for ``s`` (``concat()`` if it holds both quote kinds)."""
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    parts = s.split("'")
    return "concat(" + ', "\'", '.join(f"'{p}'" for p in parts) + ")"


def number_literal(value: int | Decimal) -> str:
    text = format(value, "f") if isinstance(value, Decimal) else str(value)
    return f"({text})" if text.startswith("-") else text


def and_(*parts: str) -> str:
    kept: list[str] = []
    for p in parts:
        if p == FALSE:
            return FALSE
        if p != TRUE and p not in kept:
            kept.append(p)
    if not kept:
        return TRUE
    if len(kept) == 1:
        return kept[0]
    return " and ".join(_paren(p) for p in kept)


def or_(*parts: str) -> str:
    kept: list[str] = []
    for p in parts:
        if p == TRUE:
            return TRUE
        if p != FALSE and p not in kept:
            kept.append(p)
    if not kept:
        return FALSE
    if len(kept) == 1:
        return kept[0]
    return " or ".join(_paren(p) for p in kept)


def not_(p: str) -> str:
    if p == TRUE:
        return FALSE
    if p == FALSE:
        return TRUE
    return f"not({p})"


def _paren(p: str) -> str:
    return p if _is_atomic(p) else f"({p})"


def _is_atomic(p: str) -> bool:
    """True if ``p`` is one call or reference with no top-level operator."""
    depth = 0
    in_quote: str | None = None
    for i, ch in enumerate(p):
        if in_quote:
            if ch == in_quote:
                in_quote = None
            continue
        if ch in "'\"":
            in_quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and i != len(p) - 1:
                return False
        elif ch == " " and depth == 0:
            return False
    return True


@dataclass
class XPathContext:
    """How references resolve: ``names`` maps ids to XLSForm names, ``types`` ids to value
    types (question types, ``assigned``, or a variable value type). ``self_id`` is written
    as ``.`` (a question's own constraint)."""

    names: Mapping[str, str]
    types: Mapping[str, str]
    self_id: str | None = None


@dataclass
class _Value:
    text: str
    guards: list[str] = field(default_factory=list)
    is_null: bool = False
    ref_type: str | None = None


class XPathWriter:
    def __init__(self, ctx: XPathContext) -> None:
        self.ctx = ctx

    # -- public ------------------------------------------------------------------------

    def condition(self, expr: Expr) -> str:
        """A boolean XPath that is true exactly when our condition is true."""
        return self._cond(expr)

    def value(self, expr: Expr) -> str:
        """An XPath value for a ``calculate``: empty whenever our value is ``null``."""
        if isinstance(expr, (Compare, And, Or, Not, Answered, Contains)):
            return self._cond(expr)
        v = self._value(expr)
        if v.is_null:
            return "''"
        if not v.guards:
            return v.text
        return f"if({and_(*v.guards)}, {v.text}, '')"

    # -- internals ---------------------------------------------------------------------

    def _ref(self, ref: Ref) -> str:
        if self.ctx.self_id is not None and ref.id == self.ctx.self_id:
            return "."
        return "${" + self.ctx.names.get(ref.id, ref.id) + "}"

    def _value(self, e: Expr) -> _Value:
        match e:
            case IntLit(value=v):
                return _Value(number_literal(v))
            case DecLit(value=v):
                return _Value(number_literal(v))
            case TextLit(value=v):
                return _Value(string_literal(v))
            case NullLit():
                return _Value("''", is_null=True)
            case BoolLit(value=b):
                # Boolean values are stored as the strings 'true'/'false' in the instance.
                return _Value("'true'" if b else "'false'")
            case Ref():
                r = self._ref(e)
                # A constraint only runs on a non-empty value, so `.` needs no guard.
                guards = [] if r == "." else [f"string-length({r}) > 0"]
                return _Value(r, guards, ref_type=self.ctx.types.get(e.id))
            case Arith(op=op, left=left, right=right):
                lv, rv = self._value(left), self._value(right)
                xop = "div" if op == "/" else op
                guards = [*lv.guards, *rv.guards]
                if op == "/":
                    guards.append(f"{_paren(rv.text)} != 0")
                text = f"{_paren(lv.text)} {xop} {_paren(rv.text)}"
                return _Value(text, guards, is_null=lv.is_null or rv.is_null)
            case _:
                # A condition used as a value: XPath gives a boolean.
                return _Value(self._cond(e))

    def _cond(self, e: Expr) -> str:
        match e:
            case Compare(op=op, left=left, right=right):
                lv, rv = self._value(left), self._value(right)
                if lv.is_null or rv.is_null:
                    return FALSE
                lt, rt = self._coerce(lv, rv, op), self._coerce(rv, lv, op)
                xop = "=" if op == "==" else op
                return and_(*lv.guards, *rv.guards, f"{lt} {xop} {rt}")
            case And(args=args):
                return and_(*(self._cond(a) for a in args))
            case Or(args=args):
                return or_(*(self._cond(a) for a in args))
            case Not(arg=arg):
                return not_(self._cond(arg))
            case Answered(ref=ref):
                return f"string-length({self._ref(ref)}) > 0"
            case Contains(ref=ref, value=value):
                v = self._value(value)
                if v.is_null:
                    return FALSE
                text = string_literal(str(value.value)) if isinstance(value, IntLit) else v.text
                return and_(*v.guards, f"selected({self._ref(ref)}, {text})")
            case BoolLit(value=b):
                return TRUE if b else FALSE
            case Ref() if self.ctx.types.get(e.id) == "boolean":
                return f"{self._ref(e)} = 'true'"
            case _:
                # A non-boolean operand used as a condition is not true (open question 2).
                return FALSE

    def _coerce(self, v: _Value, other: _Value, op: str) -> str:
        if v.ref_type == "date" and op in ("<", "<=", ">", ">="):
            return f"decimal-date-time({v.text})"
        if other.ref_type in _CODE_TYPES and _is_int_text(v.text):
            return string_literal(v.text.strip("()"))
        return _paren(v.text)


def _is_int_text(text: str) -> bool:
    t = text.strip("()")
    return t.lstrip("-").isdigit()


__all__ = [
    "FALSE",
    "TRUE",
    "XPathContext",
    "XPathWriter",
    "and_",
    "not_",
    "number_literal",
    "or_",
    "string_literal",
]
