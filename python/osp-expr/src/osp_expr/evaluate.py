"""Evaluator, exactly per planning/semantics.md §2 and §3.

Values: ``int``, ``Decimal`` (never float), ``str``, ``datetime.date``, ``frozenset``
(a multi-choice answer: set of choice codes), ``bool`` (results of tests), or ``None``
(the missing value).

Rules (section numbers are semantics.md):

- §3 Two-valued logic. Any comparison with ``None`` is false, including
  ``None == None``; ``contains(None, v)`` is false. ``and`` / ``or`` / ``not`` and a
  condition treat anything that is not ``True`` as false, so ``not null`` is true.
- §3 Arithmetic with ``None`` gives ``None``.
- §3 A reference to a question that is not-reached (absent from ``env``) or irrelevant
  (``None`` in ``env``) gives ``None``.
- §3 ``if(cond, a, b)`` is lazy: only the chosen branch is evaluated, and a condition
  that is not ``True`` (``None`` included) picks ``b``.
- §2 Choice codes compare as text (C2-8): an integer and a text are equal when the
  integer's decimal text is the text (``1 == "1"``), in ``==``, ``!=`` and ``contains``.
  Any other number never equals a text.
- §3 A type mismatch (``text == 5``, ``text < "b"``, ``text + 1``,
  ``contains(non-multi, v)``, a number used as a condition) gives ``None`` and a
  ``type-mismatch`` diagnostic. ``typecheck`` blocks these at publish, so they only
  arise in hand-edited JSON. Inside ``and`` / ``or`` / ``not`` / ``if`` the mismatched
  operand counts as ``None``, so the two-valued rules above still apply.
- §2 ``/`` returns a ``Decimal``; ``x / 0`` gives ``None`` and a ``division-by-zero``
  diagnostic. ``+ - *`` on two integers stay exact integers; every other operation keeps
  28 significant digits, rounding half-even.
- §2 Text is trimmed (``values.TRIM_CHARS``) and whitespace-only text counts as
  unanswered (``None``); an empty multi-choice answer is unanswered (``None``).

Runtime diagnostics are collected when the caller passes a ``diagnostics`` list; they are
never raised. The evaluator never raises on any expression or environment.
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
    If,
    IntLit,
    Not,
    NullLit,
    Or,
    Ref,
    TextLit,
)
from .diagnostics import Diagnostic
from .values import trim

Value = int | Decimal | str | _dt.date | frozenset | bool | None

DECIMAL_PRECISION = 28
"""Significant digits kept by decimal arithmetic (Python's default context)."""

TYPE_MISMATCH = "type-mismatch"
DIVISION_BY_ZERO = "division-by-zero"


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
        text = trim(value)  # §2: trimmed; whitespace-only is unanswered
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


def _code_eq(a: Value, b: Value) -> bool:
    """Equality of two codes or numbers: numbers numerically, an integer and a text as
    text (semantics.md §2, C2-8), anything else exactly."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b and type(a) is type(b)
    if isinstance(a, int) and isinstance(b, str):
        return str(a) == b
    if isinstance(a, str) and isinstance(b, int):
        return a == str(b)
    return a == b


def _same_codes(a: frozenset, b: frozenset) -> bool:
    """Two multi answers hold the same codes (each code of one equals one of the other)."""
    return all(any(_code_eq(x, y) for y in b) for x in a) and all(
        any(_code_eq(x, y) for x in a) for y in b
    )


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
    def __init__(self, env: Mapping[str, object], diagnostics: list[Diagnostic] | None):
        self.env = env
        self.ctx = _context()
        self.diagnostics = diagnostics

    def note(self, code: str, path: str, message: str) -> None:
        if self.diagnostics is not None:
            self.diagnostics.append(
                Diagnostic(code=code, message=message, severity="warning", path=path or "/")
            )

    def lookup(self, qid: str) -> Value:
        try:
            raw = self.env.get(qid)  # §3: not-reached (absent) -> None
        except Exception:
            return None
        return normalise_value(raw)

    def eval(self, node: Expr, path: str) -> Value:
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
                return self.contains(self.lookup(r.id), self.eval(v, path + "/value"), path)
            case Compare(op=op, left=left, right=right):
                a = self.eval(left, path + "/left")
                b = self.eval(right, path + "/right")
                return self.compare(op, a, b, path)
            case Arith(op=op, left=left, right=right):
                a = self.eval(left, path + "/left")
                b = self.eval(right, path + "/right")
                return self.arith(op, a, b, path)
            case And(args=args):
                return all(self.truth(a, f"{path}/args/{i}") for i, a in enumerate(args))
            case Or(args=args):
                return any(self.truth(a, f"{path}/args/{i}") for i, a in enumerate(args))
            case Not(arg=a):
                return not self.truth(a, path + "/arg")
            case If(cond=c, then=t, else_=e):
                if self.truth(c, path + "/cond"):
                    return self.eval(t, path + "/then")
                return self.eval(e, path + "/else")
        return None

    def truth(self, node: Expr, path: str) -> bool:
        """A logical operand: only ``True`` is true. A non-boolean value is a mismatch."""
        v = self.eval(node, path)
        if v is not None and not isinstance(v, bool):
            self.note(TYPE_MISMATCH, path, f"a condition needs true/false, not {_kind(v)}")
        return v is True

    def contains(self, multi: Value, value: Value, path: str) -> Value:
        if multi is None or value is None:
            return False  # §3: two-valued; contains(null, v) is false
        if not isinstance(multi, frozenset):
            self.note(TYPE_MISMATCH, path + "/ref", f"contains() needs a multi, not {_kind(multi)}")
            return None
        if _kind(value) not in ("number", "text"):
            self.note(
                TYPE_MISMATCH, path + "/value", f"contains() looks for a code, not {_kind(value)}"
            )
            return None
        return any(_code_eq(code, value) for code in multi)

    def compare(self, op: str, left: Value, right: Value, path: str) -> Value:
        if left is None or right is None:
            return False  # §3, including null == null
        kind = _kind(left)
        code_pair = {type(left), type(right)} == {int, str}  # C2-8: codes compare as text
        if kind != _kind(right) and not (code_pair and op in ("==", "!=")):
            self.note(TYPE_MISMATCH, path, f"cannot compare {kind} {op} {_kind(right)}")
            return None
        if op in ("==", "!="):
            if isinstance(left, frozenset) and isinstance(right, frozenset):
                same = _same_codes(left, right)
            else:
                same = _code_eq(left, right)
            return same if op == "==" else not same
        if kind not in ("number", "date"):
            self.note(TYPE_MISMATCH, path, f"'{op}' needs two numbers or two dates, not {kind}")
            return None
        if op == "<":
            return left < right  # type: ignore[operator]
        if op == "<=":
            return left <= right  # type: ignore[operator]
        if op == ">":
            return left > right  # type: ignore[operator]
        return left >= right  # type: ignore[operator]

    def arith(self, op: str, left: Value, right: Value, path: str) -> Value:
        if left is None or right is None:
            return None  # §3
        if not (_is_number(left) and _is_number(right)):
            self.note(
                TYPE_MISMATCH, path, f"'{op}' needs numbers, not {_kind(left)}, {_kind(right)}"
            )
            return None
        if op != "/" and isinstance(left, int) and isinstance(right, int):
            if op == "+":
                return left + right
            if op == "-":
                return left - right
            return left * right
        a, b = Decimal(left), Decimal(right)  # type: ignore[arg-type]
        if op == "/":
            if b == 0:
                self.note(DIVISION_BY_ZERO, path, "division by zero gives null")
                return None
            result = self.ctx.divide(a, b)  # §2: '/' is decimal
        elif op == "+":
            result = self.ctx.add(a, b)
        elif op == "-":
            result = self.ctx.subtract(a, b)
        else:
            result = self.ctx.multiply(a, b)
        return result if result.is_finite() else None


def evaluate(
    expr: Expr, env: Mapping[str, object], diagnostics: list[Diagnostic] | None = None
) -> Value:
    """Evaluate ``expr`` against ``env`` (question id -> answer). Never raises.

    Runtime diagnostics (``type-mismatch``, ``division-by-zero``; severity warning, with
    a JSON-pointer ``path`` into the AST) are appended to ``diagnostics`` if given.
    """
    try:
        return _Evaluator(env, diagnostics).eval(expr, "")
    except Exception:  # e.g. RecursionError on a pathologically deep AST
        return None


def evaluate_condition(
    expr: Expr, env: Mapping[str, object], diagnostics: list[Diagnostic] | None = None
) -> bool:
    """Evaluate ``expr`` as a condition: only ``True`` is true; ``None`` is false (§3)."""
    value = evaluate(expr, env, diagnostics)
    if diagnostics is not None and value is not None and not isinstance(value, bool):
        diagnostics.append(
            Diagnostic(
                code=TYPE_MISMATCH,
                message=f"a condition needs true/false, not {_kind(value)}",
                severity="warning",
                path="/",
            )
        )
    return value is True


__all__ = [
    "DECIMAL_PRECISION",
    "DIVISION_BY_ZERO",
    "TYPE_MISMATCH",
    "Value",
    "evaluate",
    "evaluate_condition",
    "normalise_value",
]
