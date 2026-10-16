"""Validator diagnostics: severity, stable code, message, RFC 6901 JSON pointer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Severity = Literal["error", "warning", "info"]

# Every code the validator can emit, with its severity. Tests check this stays complete.
CODES: dict[str, Severity] = {
    # Structure (from the pydantic model)
    "schema.type": "error",
    "schema.missing": "error",
    "schema.extra": "error",
    "schema.enum": "error",
    "schema.pattern": "error",
    "schema.value": "error",
    "spec.unsupported_version": "error",
    # Identity
    "id.duplicate": "error",
    "id.reserved": "error",
    "name.duplicate": "error",
    "name.case_collision": "warning",
    "name.reserved": "error",
    # Languages and text
    "lang.duplicate": "error",
    "lang.unknown_default": "error",
    "text.unknown_language": "error",
    "text.missing_translation": "warning",
    # Choices
    "choice.source": "error",
    "choice.duplicate_value": "error",
    "choice.invalid_value": "error",
    "choice.mixed_types": "warning",
    "choicelist.unused": "info",
    # References (conditions, expressions, piping)
    "ref.unknown": "error",
    "ref.unknown_block": "error",
    "ref.unknown_choice_list": "error",
    "ref.unknown_quota": "error",
    "ref.unknown_variable": "error",
    "ref.no_value": "error",
    "ref.self": "error",
    "ref.forward": "error",
    "ref.not_in_flow": "warning",
    "ref.randomised_sibling": "warning",
    "ref.other_branch": "warning",
    "pipe.invalid": "error",
    "expr.type": "error",
    # Flow
    "flow.empty": "warning",
    "flow.unreachable": "warning",
    "flow.block_reused": "error",
    "flow.empty_branch": "warning",
    "flow.pick_too_large": "error",
    "flow.assign_wrong_kind": "error",
    "flow.variable_reassigned": "error",
    "block.unused": "warning",
    "quota.unused": "warning",
    # Variables
    "variable.cycle": "error",
    "variable.never_assigned": "warning",
    "variable.duplicate_level": "error",
    "variable.default_type": "error",
    # Safety net: the validator itself failed. Never expected; fuzz tests assert it.
    "internal.error": "error",
}


class Diagnostic(BaseModel):
    model_config = ConfigDict(frozen=True)

    severity: Severity
    code: str
    message: str
    pointer: str  # RFC 6901, "" is the document root


def make(code: str, pointer: str, message: str) -> Diagnostic:
    return Diagnostic(severity=CODES[code], code=code, message=message, pointer=pointer)


def pointer(*parts: str | int) -> str:
    """Build an RFC 6901 pointer from path parts."""
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def has_errors(diagnostics: list[Diagnostic]) -> bool:
    return any(d.severity == "error" for d in diagnostics)
