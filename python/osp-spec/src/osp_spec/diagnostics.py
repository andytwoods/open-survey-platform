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
    "name.case_collision": "error",
    "name.reserved": "error",
    # Languages and text
    "lang.duplicate": "error",
    "lang.unknown_default": "error",
    "text.unknown_language": "error",
    "text.missing_translation": "warning",
    # Rich text (planning/rich-text.md §3.2): per-field levels and limits, links
    "text.too_long": "error",  # more text characters than the field's level allows
    "text.too_many_blocks": "error",  # over 200 blocks, or over 100 items in a list
    "text.block_not_allowed": "error",  # a heading in a stem; a list or 2nd block inline
    "link.scheme": "error",  # a link whose href is not an absolute https: URL
    "link.empty": "error",  # a link with no text
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
    "ref.unknown_choice_code": "warning",
    "ref.self": "error",
    "ref.forward": "error",
    "ref.not_in_flow": "warning",
    "ref.randomised_sibling": "warning",
    "ref.other_branch": "warning",
    "ref.cycle": "error",
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
    # Questions
    "question.bounds": "error",
    "question.slider": "error",
    "matrix.duplicate_row": "error",
    "matrix.row_id": "error",
    # Settings
    "settings.retention": "error",
    # Consent (semantics.md §11)
    "consent.pipe": "error",
    "consent.outcome": "error",
    # Endings (end-of-survey plan §4.1, EN1)
    "ending.unreachable": "warning",  # an ending for an outcome nothing in the survey reaches
    "ending.declined_summary": "error",  # a decline records nothing, so it has no answers to show
    # End redirects (end-of-survey plan §4.2, EN2)
    "redirect.template": "error",  # a settings.redirectTemplates entry breaks the URL rules
    "redirect.template_clash": "error",  # the same name in settings.redirectTemplates and hooks
    "redirect.unknown_template": "error",  # an ending names a template nothing declares
    "redirect.params": "error",  # params and the template's placeholders differ
    "redirect.param_literal": "error",  # a literal value that can never pass its pattern
    "redirect.param_question": "warning",  # a piped answer leaves for a third party (data export)
    "redirect.immediate": "warning",  # delay 0: the ending's text is never seen
    # External task step (task EX2, planning/external-tasks.md)
    "external.unknown_template": "error",  # the node names a template nothing declares
    "external.params": "error",  # params and the template's placeholders differ
    "external.param_literal": "error",  # a literal param value that can never pass its pattern
    "external.param_question": "warning",  # a piped answer leaves for the external task (export)
    "external.reserved_param": "error",  # a template placeholder uses osp_return / osp_token
    "external.return_target": "error",  # a `returns` id is not an embedded URL variable
    # Researcher hooks (runtime-design.md §7a; osp_spec.hooks.check_hooks)
    "hooks.unknown_ref": "error",  # a handler reads an id that is not a question or variable
    "hooks.write_target": "error",  # a handler writes something that is not a hook variable
    "hooks.redirect": "error",  # a redirect template breaks the host's URL rules
    "hooks.parent_origin": "error",  # the parent origin is not one https origin
    # Publishing only (publish_diagnostics; never from validate)
    "publish.retention_required": "error",
    "publish.consent_missing": "warning",  # participant questions but no consent page
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
