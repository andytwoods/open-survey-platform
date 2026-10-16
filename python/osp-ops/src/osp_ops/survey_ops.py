"""Whole-document ops: `replace_survey` (the JSON view's Apply) and `apply_patch`
(RFC 6902; also the generic inverse of cascading deletes)."""

from __future__ import annotations

import copy

from pydantic import JsonValue

from . import patch as jp
from .registry import REVERSE_PATCH, Ctx, Invocation, OpError, Params, op


class ReplaceSurvey(Params):
    survey: dict[str, JsonValue]


@op(
    "replace_survey",
    ReplaceSurvey,
    label="Replace survey (JSON)",
    area="survey",
    whole_document=True,
)
def replace_survey(ctx: Ctx, p: ReplaceSurvey) -> Invocation:
    """Replace the whole survey, as the JSON view's Apply does. The new survey must be
    structurally valid; semantic problems come back as diagnostics, like any op. The
    input survey may be invalid (this is how a broken draft is repaired)."""
    ctx.doc = copy.deepcopy(dict(p.survey))
    ctx.touch()
    return Invocation(op="replace_survey", params={"survey": copy.deepcopy(ctx.before)})


class ApplyPatch(Params):
    patch: list[dict[str, JsonValue]]


@op("apply_patch", ApplyPatch, label="Apply JSON Patch", area="survey", whole_document=True)
def apply_patch(ctx: Ctx, p: ApplyPatch) -> Invocation:
    """Apply an RFC 6902 JSON Patch to the survey. The result must be structurally valid."""
    try:
        ctx.doc = jp.apply(ctx.doc, [dict(o) for o in p.patch])
    except jp.PatchError as e:
        raise OpError("op.patch", str(e)[:300]) from None
    ctx.touch()
    return REVERSE_PATCH
