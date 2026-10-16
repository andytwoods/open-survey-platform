"""Evaluator, exactly per planning/semantics.md §2 and §3.

Values: ``int``, ``Decimal`` (never float), ``str``, ``datetime.date``, ``frozenset``
(a multi-choice answer: set of choice codes), ``bool`` (results of tests), or ``None``
(the missing value).

Rules (section numbers are semantics.md):

- §3 Any comparison with ``None`` is false, including ``None == None``.
- §3 Arithmetic with ``None`` gives ``None``.
- §3 A condition that evaluates to ``None`` counts as false (``evaluate_condition``).
- §3 A reference to a question that is not-reached (absent from ``env``) or irrelevant
  (``None`` in ``env``) gives ``None``.
- §2 ``/`` returns a ``Decimal``. ``+ - *`` on two integers stay exact integers.
- §2 / §1 Text is trimmed and whitespace-only text counts as unanswered (``None``); an
  empty multi-choice answer is unanswered (``None``).

Provisional rules (semantics.md "Open questions", not yet decided by a human):

- Division by zero gives ``None``.
- Ill-typed operands: a test (comparison, ``contains``) on values of the wrong kinds is
  false; ordering (``< <= > >=``) is defined only for numbers and for dates; arithmetic
  on non-numbers gives ``None``; ``and``/``or``/``not`` treat any operand that is not
  ``True`` as false. ``typecheck`` reports all of these statically.

The evaluator never raises on any expression or environment.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping
from decimal import ROUND_HALF_EVEN, Context, Decimal

from .ast import (
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

Value = int | Decimal | str | _dt.date | frozenset | bool | None

DECIMAL_PRECISION = 28
"""Significant digits kept by decimal arithmetic (Python's default context)."""


def _context() -> Context:
    # A fresh, explicit context per evaluation: no dependence on (or mutation of) the
    # thread's global decimal context, and no traps, so overflow cannot raise.
    return Context(
        prec=DECIMAL_PRECISION,
        rounding=ROUND_HALF_EVEN,
        Emax=999_999,
        Emin=-999_999,
        traps=[],
    )


def normalise_value(value: object) -> Value:
    """Map an answer from the environment to an evaluator value.

    Unsupported values (floats, bools, non-finite decimals, other objects) become
    ``None`` rather than raising: answers are numbers, text, dates or choice sets (§2).
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, str):
        text = value.strip()  # §2: trimmed; whitespace-only is unanswered
        return text or None
    if isinstance(value, _dt.datetime):
        return None
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, set | frozenset | list | tuple):
        codes = []
        for code in value:
            if isinstance(code, bool) or not isinstance(code, int | str):
                return None
            codes.append(code)
        return frozenset(codes) or None  # §1: nothing ticked is unanswered
    return None


def _is_number(v: Value) -> bool:
    return isinstance(v, int | Decimal) and not isinstance(v, bool)


def _kind(v: Value) -> str:
    if isinstance(v, bool):
        return "bool"
    if _is_number(v):
        return "number"
    if isinstance(v, str):
        return "text"
    if isinstance(v, frozenset):
        return "multi"
    if isinstance(v, _dt.date):
        return "date"
    return "none"


class _Evaluator:
    def __init__(self, env: Mapping[str, object]):
        self.env = env
        self.ctx = _context()

    def lookup(self, qid: str) -> Value:
        try:
            raw = self.env.get(qid)  # §3: not-reached (absent) -> None
        except Exception:
            return None
        return normalise_value(raw)

    def eval(self, node: Expr) -> Value:
        match node:
            case IntLit(value=v) | DecLit(value=v) | TextLit(value=v) | BoolLit(value=v):
                return v
            case NullLit():
                return None
            case Ref(id=qid):
                return self.lookup(qid)
            case Answered(ref=r):
                return self.lookup(r.id) is not None
            case Contains(ref=r, value=v):
                return self.contains(self.lookup(r.id), self.eval(v))
            case Compare(op=op, left=left, right=right):
                return self.compare(op, self.eval(left), self.eval(right))
            case Arith(op=op, left=left, right=right):
                return self.arith(op, self.eval(left), self.eval(right))
            case And(args=args):
                return all(self.eval(a) is True for a in args)
            case Or(args=args):
                return any(self.eval(a) is True for a in args)
            case Not(arg=a):
                return self.eval(a) is not True
        return None

    @staticmethod
    def contains(multi: Value, value: Value) -> bool:
        if multi is None or value is None:
            return False
        if not isinstance(multi, frozenset) or _kind(value) not in ("number", "text"):
            return False  # provisional: ill-typed test is false
        return value in multi

    @staticmethod
    def compare(op: str, left: Value, right: Value) -> bool:
        if left is None or right is None:
            return False  # §3, including null == null
        kind = _kind(left)
        if kind != _kind(right):
            return False  # provisional: ill-typed test is false
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        if kind not in ("number", "date"):
            return False  # provisional: ordering only for numbers and dates
        if op == "<":
            return left < right  # type: ignore[operator]
        if op == "<=":
            return left <= right  # type: ignore[operator]
        if op == ">":
            return left > right  # type: ignore[operator]
        return left >= right  # type: ignore[operator]

    def arith(self, op: str, left: Value, right: Value) -> Value:
        if left is None or right is None:
            return None  # §3
        if not (_is_number(left) and _is_number(right)):
            return None  # provisional: arithmetic on non-numbers is null
        if op != "/" and isinstance(left, int) and isinstance(right, int):
            if op == "+":
                return left + right
            if op == "-":
                return left - right
            return left * right
        a, b = Decimal(left), Decimal(right)  # type: ignore[arg-type]
        if op == "/":
            if b == 0:
                return None  # provisional: division by zero is null
            result = self.ctx.divide(a, b)  # §2: '/' is decimal
        elif op == "+":
            result = self.ctx.add(a, b)
        elif op == "-":
            result = self.ctx.subtract(a, b)
        else:
            result = self.ctx.multiply(a, b)
        return result if result.is_finite() else None


def evaluate(expr: Expr, env: Mapping[str, object]) -> Value:
    """Evaluate ``expr`` against ``env`` (question id -> answer). Never raises."""
    try:
        return _Evaluator(env).eval(expr)
    except Exception:  # e.g. RecursionError on a pathologically deep AST
        return None


def evaluate_condition(expr: Expr, env: Mapping[str, object]) -> bool:
    """Evaluate ``expr`` as a condition: only ``True`` is true; ``None`` is false (§3)."""
    return evaluate(expr, env) is True


__all__ = ["Value", "DECIMAL_PRECISION", "normalise_value", "evaluate", "evaluate_condition"]
