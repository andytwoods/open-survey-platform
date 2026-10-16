"""osp-expr (layer L0): expression AST, text syntax, evaluator and static checks.

See README.md and planning/semantics.md §2-§3.
"""

from .ast import (
    EXPR_ADAPTER,
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
    expr_from_json,
    expr_to_json,
)
from .diagnostics import Diagnostic
from .evaluate import Value, evaluate, evaluate_condition
from .static import references, typecheck
from .values import DECIMAL_DIGITS, TRIM_CHARS, canonical_decimal, trim
from .syntax import ParseResult, parse, to_text

__all__ = [
    "EXPR_ADAPTER",
    "And",
    "Answered",
    "Arith",
    "BoolLit",
    "Compare",
    "Contains",
    "DecLit",
    "DECIMAL_DIGITS",
    "Diagnostic",
    "Expr",
    "If",
    "IntLit",
    "Not",
    "NullLit",
    "Or",
    "ParseResult",
    "Ref",
    "TRIM_CHARS",
    "TextLit",
    "Value",
    "canonical_decimal",
    "evaluate",
    "evaluate_condition",
    "expr_from_json",
    "expr_to_json",
    "parse",
    "references",
    "to_text",
    "trim",
    "typecheck",
]
