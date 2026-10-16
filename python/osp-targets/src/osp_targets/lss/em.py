"""osp-expr AST → LimeSurvey Expression Manager (EM) syntax, keeping our missing-value
rules (semantics.md §3).

Every reference is read as ``<code>.NAOK`` ("not applicable OK"): an irrelevant question
then reads as empty instead of making the whole equation false. Empty does not behave like
our ``null`` (``"" == ""`` is true), so each comparison is guarded: it is true only if every
reference in its operands is non-empty (``!is_empty(x.NAOK)``) and every divisor is
non-zero (division by zero gives ``null``, open question 1). A value in an equation is
wrapped as ``if(<guards>, value, "")`` so ``null`` in gives ``null`` (empty) out.

Choice questions: a single-choice answer is its answer code, so a literal compared with it
is rewritten to the code the exporter gave that choice. A multi-choice question is one
column per choice (``<q>_<code>`` = ``Y``), so ``contains(q, v)`` reads that column.

Written from the public Expression Manager documentation (operators ``== != < <= > >=``,
``and``, ``or``, ``!``, functions ``is_empty``, ``if``, ``strtotime``, ``join``).
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

TRUE = "1"
FALSE = "0"
EMPTY = '""'

# Types whose stored value is a code (compare literals as the mapped code, as text).
_CODE_TYPES = frozenset({"single", "assigned"})


def string_literal(s: str) -> str:
    """An EM string literal for ``s`` (``join()`` if it holds both quote kinds)."""
    if '"' not in s:
        return f'"{s}"'
    if "'" not in s:
        return f"'{s}'"
    parts = s.split('"')
    return "join(" + ", '\"', ".join(f'"{p}"' for p in parts) + ")"


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
    return " and ".join(paren(p) for p in kept)


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
    return " or ".join(paren(p) for p in kept)


def not_(p: str) -> str:
    if p == TRUE:
        return FALSE
    if p == FALSE:
        return TRUE
    if p.startswith("!") and is_atomic(p[1:]):
        return p[1:]
    return "!" + paren(p)


def paren(p: str) -> str:
    return p if is_atomic(p) else f"({p})"


def is_atomic(p: str) -> bool:
    """True if ``p`` is one call, literal or reference with no top-level operator."""
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
class EMContext:
    """How references resolve.

    - ``codes``: id → LimeSurvey question code.
    - ``types``: id → value type (question type, ``assigned``, ``boolean``, a variable value
      type).
    - ``choices``: id of a single/multi question → {our value as text: answer or
      subquestion code}.
    """

    codes: Mapping[str, str]
    types: Mapping[str, str]
    choices: Mapping[str, Mapping[str, str]] = field(default_factory=dict)


@dataclass
class _Value:
    text: str
    guards: list[str] = field(default_factory=list)
    is_null: bool = False
    ref_id: str | None = None
    literal: str | None = None  # the literal's value as text, for choice-code mapping


class EMWriter:
    def __init__(self, ctx: EMContext) -> None:
        self.ctx = ctx

    # -- public ------------------------------------------------------------------------

    def condition(self, expr: Expr) -> str:
        """An EM boolean that is true exactly when our condition is true."""
        return self._cond(expr)

    def value(self, expr: Expr) -> str:
        """An EM value for an equation: empty whenever our value is ``null``."""
        if isinstance(expr, (Compare, And, Or, Not, Answered, Contains, BoolLit)):
            return f"if({self._cond(expr)}, 1, 0)"
        v = self._value(expr)
        if v.is_null:
            return EMPTY
        if not v.guards:
            return v.text
        return f"if({and_(*v.guards)}, {v.text}, {EMPTY})"

    # -- internals ---------------------------------------------------------------------

    def code(self, ref_id: str) -> str:
        return self.ctx.codes.get(ref_id, ref_id)

    def _ref(self, ref_id: str) -> str:
        return f"{self.code(ref_id)}.NAOK"

    def _subq(self, ref_id: str, choice_code: str) -> str:
        return f"{self.code(ref_id)}_{choice_code}.NAOK"

    def _value(self, e: Expr) -> _Value:
        match e:
            case IntLit(value=v):
                return _Value(number_literal(v), literal=str(v))
            case DecLit(value=v):
                return _Value(number_literal(v), literal=format(v, "f"))
            case TextLit(value=v):
                return _Value(string_literal(v), literal=v)
            case NullLit():
                return _Value(EMPTY, is_null=True)
            case BoolLit(value=b):
                return _Value(TRUE if b else FALSE)
            case Ref(id=rid):
                if self.ctx.types.get(rid) == "multi":
                    return self._multi_value(rid)
                r = self._ref(rid)
                return _Value(r, [f"!is_empty({r})"], ref_id=rid)
            case Arith(op=op, left=left, right=right):
                lv, rv = self._value(left), self._value(right)
                guards = [*lv.guards, *rv.guards]
                is_null = lv.is_null or rv.is_null
                if op == "/" and isinstance(right, (IntLit, DecLit)):
                    is_null = is_null or right.value == 0  # x / 0 is null
                elif op == "/":
                    guards.append(f"{paren(rv.text)} != 0")
                text = f"{paren(lv.text)} {op} {paren(rv.text)}"
                return _Value(text, guards, is_null=is_null)
            case _:
                return _Value(f"if({self._cond(e)}, 1, 0)")

    def _multi_value(self, rid: str) -> _Value:
        """A multi-choice answer as a value: its checked codes, space-separated."""
        codes = self.ctx.choices.get(rid, {})
        parts = [f'if({self._subq(rid, c)} == "Y", "{c} ", "")' for c in codes.values()]
        if not parts:
            return _Value(EMPTY, is_null=True)
        text = f"trim(join({', '.join(parts)}))"
        return _Value(text, [f"!is_empty({text})"], ref_id=rid)

    def _cond(self, e: Expr) -> str:
        match e:
            case Compare(op=op, left=left, right=right):
                lv, rv = self._value(left), self._value(right)
                if lv.is_null or rv.is_null:
                    return FALSE
                lt, rt = self._coerce(lv, rv, op), self._coerce(rv, lv, op)
                return and_(*lv.guards, *rv.guards, f"{lt} {op} {rt}")
            case And(args=args):
                return and_(*(self._cond(a) for a in args))
            case Or(args=args):
                return or_(*(self._cond(a) for a in args))
            case Not(arg=arg):
                return not_(self._cond(arg))
            case Answered(ref=ref):
                if self.ctx.types.get(ref.id) == "multi":
                    codes = self.ctx.choices.get(ref.id, {}).values()
                    return or_(*(f'{self._subq(ref.id, c)} == "Y"' for c in codes))
                return f"!is_empty({self._ref(ref.id)})"
            case Contains(ref=ref, value=value):
                return self._contains(ref.id, value)
            case BoolLit(value=b):
                return TRUE if b else FALSE
            case Ref(id=rid) if self.ctx.types.get(rid) == "boolean":
                return f"{self._ref(rid)} == 1"
            case _:
                # A non-boolean operand used as a condition is not true (open question 2).
                return FALSE

    def _contains(self, rid: str, value: Expr) -> str:
        codes = self.ctx.choices.get(rid, {})
        v = self._value(value)
        if v.is_null:
            return FALSE
        if v.literal is not None:
            code = codes.get(v.literal)
            return f'{self._subq(rid, code)} == "Y"' if code is not None else FALSE
        # A computed choice value: test each choice in turn.
        return and_(
            *v.guards,
            or_(
                *(
                    and_(
                        f"{paren(v.text)} == {string_literal(ours)}", f'{self._subq(rid, c)} == "Y"'
                    )
                    for ours, c in codes.items()
                )
            ),
        )

    def _coerce(self, v: _Value, other: _Value, op: str) -> str:
        if (v.ref_id is not None and self.ctx.types.get(v.ref_id) == "date") or (
            other.ref_id is not None and self.ctx.types.get(other.ref_id) == "date"
        ):
            return f"strtotime({v.text})"
        if (
            v.literal is not None
            and other.ref_id is not None
            and self.ctx.types.get(other.ref_id) in _CODE_TYPES
        ):
            mapped = self.ctx.choices.get(other.ref_id, {}).get(v.literal, v.literal)
            return string_literal(mapped)
        return paren(v.text)


__all__ = [
    "EMPTY",
    "FALSE",
    "TRUE",
    "EMContext",
    "EMWriter",
    "and_",
    "not_",
    "number_literal",
    "or_",
    "paren",
    "string_literal",
]
