"""Expression AST for survey conditions and calculations (planning/semantics.md §2, §3).

Every node is a frozen pydantic model with a ``kind`` discriminator, so an expression
round-trips through JSON (``Expr`` is a discriminated union; use ``EXPR_ADAPTER`` or
``expr_from_json`` / ``expr_to_json``). This module is the stable contract other
packages (``osp-spec``) type their condition fields against: change it only additively.

JSON shape, e.g. ``q3 > 5 and contains(q7, "b")``::

    {"kind": "and", "args": [
        {"kind": "compare", "op": ">", "left": {"kind": "ref", "id": "q3"},
         "right": {"kind": "int", "value": 5}},
        {"kind": "contains", "ref": {"kind": "ref", "id": "q7"},
         "value": {"kind": "text", "value": "b"}}]}

Numbers are never binary floats (§2): ``IntLit`` holds an ``int``, ``DecLit`` a finite
``Decimal`` (serialised to JSON as a string, e.g. ``"1.50"``).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, TypeAdapter

# Words that cannot be question ids, because the text syntax uses them.
# ``true``/``false`` are reserved for a possible boolean literal later.
KEYWORDS: frozenset[str] = frozenset({"and", "or", "not", "null", "true", "false"})

IDENT_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"

CompareOp = Literal["==", "!=", "<", "<=", ">", ">="]
ArithOp = Literal["+", "-", "*", "/"]


def _not_keyword(value: str) -> str:
    if value in KEYWORDS:
        raise ValueError(f"{value!r} is a reserved word and cannot be a question id")
    return value


QuestionId = Annotated[str, Field(pattern=IDENT_PATTERN), AfterValidator(_not_keyword)]


class _Node(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- Literals ---------------------------------------------------------------------


class IntLit(_Node):
    """Integer literal, e.g. ``5`` or ``-3``."""

    kind: Literal["int"] = "int"
    value: Annotated[int, Field(strict=True)]


class DecLit(_Node):
    """Decimal literal, e.g. ``2.50``. Always finite; never a float (§2)."""

    kind: Literal["decimal"] = "decimal"
    value: Annotated[Decimal, Field(allow_inf_nan=False)]


class TextLit(_Node):
    """Text literal, e.g. ``"b"``. Also used for text choice codes (§2)."""

    kind: Literal["text"] = "text"
    value: str


class NullLit(_Node):
    """The missing value ``null`` (§3)."""

    kind: Literal["null"] = "null"


# --- References -------------------------------------------------------------------


class Ref(_Node):
    """Reference to a question (or recorded variable) by id. Not-reached or
    irrelevant questions evaluate to null (§3)."""

    kind: Literal["ref"] = "ref"
    id: QuestionId


# --- Operators --------------------------------------------------------------------


class Compare(_Node):
    """``left op right``. Any comparison with null is false, even ``null == null`` (§3)."""

    kind: Literal["compare"] = "compare"
    op: CompareOp
    left: Expr
    right: Expr


class Arith(_Node):
    """``left op right`` for ``+ - * /``. Null in, null out (§3). ``/`` is decimal (§2)."""

    kind: Literal["arith"] = "arith"
    op: ArithOp
    left: Expr
    right: Expr


class And(_Node):
    """N-ary conjunction (at least two operands)."""

    kind: Literal["and"] = "and"
    args: Annotated[tuple[Expr, ...], Field(min_length=2)]


class Or(_Node):
    """N-ary disjunction (at least two operands)."""

    kind: Literal["or"] = "or"
    args: Annotated[tuple[Expr, ...], Field(min_length=2)]


class Not(_Node):
    """Negation."""

    kind: Literal["not"] = "not"
    arg: Expr


# --- Functions --------------------------------------------------------------------


class Answered(_Node):
    """``answered(q)``: true iff ``q`` has a value; the way to test presence (§3)."""

    kind: Literal["answered"] = "answered"
    ref: Ref


class Contains(_Node):
    """``contains(q, value)``: true iff multi-choice ``q`` includes ``value`` (§3)."""

    kind: Literal["contains"] = "contains"
    ref: Ref
    value: Expr


Expr = Annotated[
    IntLit
    | DecLit
    | TextLit
    | NullLit
    | Ref
    | Compare
    | Arith
    | And
    | Or
    | Not
    | Answered
    | Contains,
    Field(discriminator="kind"),
]

for _model in (Compare, Arith, And, Or, Not, Contains):
    _model.model_rebuild()

EXPR_ADAPTER: TypeAdapter[Expr] = TypeAdapter(Expr)


def expr_to_json(expr: Expr) -> str:
    """Serialise an expression to JSON text."""
    return EXPR_ADAPTER.dump_json(expr).decode()


def expr_from_json(data: str | bytes) -> Expr:
    """Parse and validate JSON text into an expression (raises pydantic.ValidationError)."""
    return EXPR_ADAPTER.validate_json(data)


__all__ = [
    "KEYWORDS",
    "IDENT_PATTERN",
    "CompareOp",
    "ArithOp",
    "QuestionId",
    "IntLit",
    "DecLit",
    "TextLit",
    "NullLit",
    "Ref",
    "Compare",
    "Arith",
    "And",
    "Or",
    "Not",
    "Answered",
    "Contains",
    "Expr",
    "EXPR_ADAPTER",
    "expr_to_json",
    "expr_from_json",
]
