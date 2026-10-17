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
    # Researcher hooks (runtime-design.md §7a; osp_spec.hooks.check_hooks)
    "hooks.unknown_ref": "error",  # a handler reads an id that is not a question or variable
    "hooks.write_target": "error",  # a handler writes something that is not a hook variable
    "hooks.redirect": "error",  # a redirect template breaks the host's URL rules
    "hooks.parent_origin": "error",  # the parent origin is not one https origin
    # Media (planning/media.md §2; osp_spec.media.check_media)
    "media.url": "error",  # not https / a same-origin path, credentials, whitespace
    "media.url_insecure": "warning",  # http://localhost, for development only
    "media.url_pipe": "error",  # `${…}` in a URL: answers never build URLs
    "media.origin_not_allowed": "error",  # not in the deployment's OSP_MEDIA_ORIGINS
    "media.alt_missing": "error",  # an image without alt text
    "media.alt_kind": "warning",  # alt on audio/video
    "media.transcript_missing": "error",  # audio without a transcript
    "media.transcript_recommended": "warning",  # video without a transcript
    "media.captions_missing": "error",  # video without a WebVTT captions file
    "media.field_kind": "error",  # captions/poster/autoplay on non-video, mustPlayToEnd on image
    "media.size_pair": "error",  # width without height or the reverse
    "media.choice_kind": "error",  # a video on a choice
    "media.must_play_choice": "error",  # mustPlayToEnd on a choice's media
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
