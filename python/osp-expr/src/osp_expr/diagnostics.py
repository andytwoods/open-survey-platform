"""Diagnostics returned (never raised) by the parser and the type checker."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Severity = Literal["error", "warning"]


class Diagnostic(BaseModel):
    """One problem found in an expression.

    ``start``/``end`` are 0-based character offsets into the source text (``end``
    exclusive), set by the parser. ``path`` is a JSON pointer into the AST's JSON form
    (e.g. ``/args/0/left``), set by the type checker.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str
    severity: Severity = "error"
    start: int | None = None
    end: int | None = None
    path: str | None = None
