"""osp-expr AST → SurveyJS expression text, keeping our missing-value rules (semantics.md §3).

The inverse of ``imports/sjs_expr.py``, written from the same public SurveyJS expression
documentation: ``{name}`` (``{grid.row}`` for a matrix row), ``= <> < <= > >=``,
``empty`` / ``notempty``, ``contains``, ``and``, ``or``, ``!``, ``+ - * /``,
``iif(c, a, b)``, single-quoted strings, numbers and ``true`` / ``false``.

An empty SurveyJS value does not behave like our ``null``: ``{a} <> 3`` is true when ``a``
is empty, ours is false. So every comparison is guarded with ``{x} notempty`` for each
reference in its operands; the one exception is ``==`` against a literal, which an empty
value can never satisfy. ``contains`` on an empty checkbox is false, as ours.

A reference to something SurveyJS does not have (an assigned variable) cannot be written:
:class:`Unmappable` is raised and the exporter reports the expression as a loss.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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
    If,
    IntLit,
    Not,
    NullLit,
    Or,
    Ref,
    TextLit,
)

TRUE = "true"
FALSE = "false"

_OPS = {"==": "=", "!=": "<>", "<": "<", "<=": "<=", ">": ">", ">=": ">="}


class Unmappable(Exception):
    """The expression reads something SurveyJS has no counterpart for."""


def string_literal(s: str) -> str:
    """A single-quoted SurveyJS string; quotes and backslashes escaped with a backslash."""
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def number_literal(value: int | Decimal) -> str:
    return format(value, "f") if isinstance(value, Decimal) else str(value)


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
    # `and` binds tighter than `or`: only an `or` needs brackets inside an `and`.
    return " and ".join(f"({p})" if _top_level(p, " or ") else p for p in kept)


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
    return " or ".join(kept)


def not_(p: str) -> str:
    if p == TRUE:
        return FALSE
    if p == FALSE:
        return TRUE
    if p.startswith("!(") and p.endswith(")") and is_atomic(p[1:]):
        return p[2:-1]
    return f"!({p})"


def _top_level(p: str, word: str) -> bool:
    """Whether ``word`` occurs in ``p`` outside quotes and brackets."""
    depth = 0
    in_quote = False
    escaped = False
    for i, ch in enumerate(p):
        if in_quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == "'":
                in_quote = False
        elif ch == "'":
            in_quote = True
        elif ch in "({":
            depth += 1
        elif ch in ")}":
            depth -= 1
        elif depth == 0 and p.startswith(word, i):
            return True
    return False


def paren(p: str) -> str:
    return p if is_atomic(p) else f"({p})"


def is_atomic(p: str) -> bool:
    """True if ``p`` is one reference, literal, call or parenthesised group: the writer puts
    a space around every operator, so that is no space outside quotes and brackets."""
    depth = 0
    in_quote = False
    escaped = False
    for ch in p:
        if in_quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == "'":
                in_quote = False
        elif ch == "'":
            in_quote = True
        elif ch in "({":
            depth += 1
        elif ch in ")}":
            depth -= 1
        elif ch == " " and depth == 0:
            return False
    return True


@dataclass
class SjsContext:
    """How references resolve.

    - ``names``: our id → the SurveyJS name inside braces (``q1``, ``grid.row``).
    - ``types``: our id → question type, or ``computed`` / ``embedded`` / ``assigned``.
    """

    names: Mapping[str, str]
    types: Mapping[str, str]


@dataclass
class _Value:
    text: str
    refs: tuple[str, ...] = ()
    is_null: bool = False
    literal: bool = False


class SjsWriter:
    def __init__(self, ctx: SjsContext) -> None:
        self.ctx = ctx

    # -- public ------------------------------------------------------------------------

    def condition(self, expr: Expr) -> str:
        """A SurveyJS boolean that is true exactly when our condition is true."""
        return self._cond(expr)

    def value(self, expr: Expr) -> str:
        """A SurveyJS value (a calculated value's expression)."""
        if isinstance(expr, (Compare, And, Or, Not, Answered, Contains, BoolLit)):
            return f"iif({self._cond(expr)}, true, false)"
        return self._value(expr).text

    def ref(self, rid: str) -> str:
        if self.ctx.types.get(rid) == "assigned" or rid not in self.ctx.names:
            raise Unmappable(f"{rid} has no SurveyJS counterpart")
        return "{" + self.ctx.names[rid] + "}"

    # -- internals ---------------------------------------------------------------------

    def _value(self, e: Expr) -> _Value:
        match e:
            case IntLit(value=v) | DecLit(value=v):
                return _Value(number_literal(v), literal=True)
            case TextLit(value=v):
                return _Value(string_literal(v), literal=True)
            case NullLit():
                return _Value("null", is_null=True)
            case BoolLit(value=b):
                return _Value(TRUE if b else FALSE, literal=True)
            case Ref(id=rid):
                return _Value(self.ref(rid), refs=(rid,))
            case If(cond=c, then=t, else_=f):
                tv, fv = self._value(t), self._value(f)
                return _Value(f"iif({self._cond(c)}, {tv.text}, {fv.text})", (*tv.refs, *fv.refs))
            case Arith(op=op, left=left, right=right):
                lv, rv = self._value(left), self._value(right)
                text = f"{self._operand(lv)} {op} {self._operand(rv)}"
                return _Value(text, (*lv.refs, *rv.refs), is_null=lv.is_null or rv.is_null)
            case _:
                return _Value(f"iif({self._cond(e)}, true, false)")

    @staticmethod
    def _operand(v: _Value) -> str:
        return f"({v.text})" if v.text.startswith("-") else paren(v.text)

    def _cond(self, e: Expr) -> str:
        match e:
            case Compare(op=op, left=left, right=right):
                lv, rv = self._value(left), self._value(right)
                if lv.is_null or rv.is_null:
                    return FALSE  # comparing with null is false (§3)
                test = f"{self._operand(lv)} {_OPS[op]} {self._operand(rv)}"
                if op == "==" and (lv.literal or rv.literal):
                    return test
                guards = [f"{self.ref(r)} notempty" for r in dict.fromkeys((*lv.refs, *rv.refs))]
                return and_(*guards, test)
            case And(args=args):
                return and_(*(self._cond(a) for a in args))
            case Or(args=args):
                return or_(*(self._cond(a) for a in args))
            case Not(arg=arg):
                return not_(self._cond(arg))
            case Answered(ref=ref):
                return f"{self.ref(ref.id)} notempty"
            case Contains(ref=ref, value=value):
                v = self._value(value)
                if v.is_null:
                    return FALSE
                return f"{self.ref(ref.id)} contains {self._operand(v)}"
            case BoolLit(value=b):
                return TRUE if b else FALSE
            case If(cond=c, then=t, else_=f):
                return f"iif({self._cond(c)}, {self._cond(t)}, {self._cond(f)})"
            case Ref(id=rid):
                return f"{self.ref(rid)} = true"
            case _:
                # A non-boolean operand used as a condition is not true (open question 2).
                return FALSE


__all__ = [
    "FALSE",
    "TRUE",
    "SjsContext",
    "SjsWriter",
    "Unmappable",
    "and_",
    "not_",
    "number_literal",
    "or_",
    "paren",
    "string_literal",
]
