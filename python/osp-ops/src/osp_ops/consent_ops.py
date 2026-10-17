"""Consent op: `set_consent` (semantics.md §11; Survey settings "Consent" section, B12).

The consent page is a survey-level object (`osp_spec.model.Consent`), not a flow node, so
it has its own op rather than `set_property`. The whole object is replaced at once, which
keeps its required `text` and its labels consistent; the survey model validates it.
"""

from __future__ import annotations

import copy

from pydantic import JsonValue

from .registry import REVERSE_PATCH, Ctx, Invocation, Params, op


class SetConsent(Params):
    consent: dict[str, JsonValue] | None = None  # None: no consent page


@op("set_consent", SetConsent, label="Set consent page", area="survey")
def set_consent(ctx: Ctx, p: SetConsent) -> Invocation:
    """Set the consent page (`text`, `agreeLabel`, `declineLabel`, `declineOutcome`,
    `countDeclines`), or with `consent: null` remove it. Texts are plain or per language;
    nothing can be piped into them (`consent.pipe`)."""
    if p.consent is None:
        ctx.doc.pop("consent", None)
    else:
        ctx.doc["consent"] = copy.deepcopy(dict(p.consent))
    ctx.touch()
    return REVERSE_PATCH
