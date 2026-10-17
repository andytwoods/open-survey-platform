"""Ending op: `set_ending` (end-of-survey plan §4.1, task EN1).

`settings.endings` maps an outcome (an end node's `outcome`, a quota's `onFull.outcome`, the
consent `declineOutcome`, the built-ins `complete` and `hook-failed`) to the screen the
participant sees when the session ends with it. One op sets or removes the ending of one
outcome as a whole object (title, body, status, summary), so its fields stay consistent; the
survey model validates it and the validator reports `ending.*` and piping problems.
"""

from __future__ import annotations

from osp_spec.model import Ending, OutcomeKey
from pydantic import JsonValue, ValidationError

from .registry import REVERSE_PATCH, Ctx, Invocation, OpError, Params, op


class SetEnding(Params):
    outcome: OutcomeKey
    ending: dict[str, JsonValue] | None = None  # None: the outcome uses the app's defaults


@op("set_ending", SetEnding, label="Set ending", area="survey")
def set_ending(ctx: Ctx, p: SetEnding) -> Invocation:
    """Set the ending screen for one outcome (`title` and `body`, plain or per language, with
    piping in both; `status` `auto` or `none`; `summary` reserved), or with `ending: null`
    remove it, so that outcome shows the app's defaults. An outcome nothing reaches is
    allowed but warned about (`ending.unreachable`)."""
    settings = ctx.doc.get("settings")
    endings = settings.get("endings") if isinstance(settings, dict) else None
    if p.ending is None:
        if not isinstance(settings, dict) or not isinstance(endings, dict):
            return REVERSE_PATCH  # nothing to remove
        if p.outcome not in endings:
            return REVERSE_PATCH
        del endings[p.outcome]
        if not endings:
            del settings["endings"]
        return REVERSE_PATCH
    try:
        ending = Ending.model_validate(p.ending)
    except ValidationError as err:
        e = err.errors(include_url=False, include_input=False)[0]
        parts = [str(x) for x in e["loc"] if isinstance(x, (str, int))]
        ptr = "".join("/" + x.replace("~", "~0").replace("/", "~1") for x in parts)
        message = f"not a valid ending: {e['msg']}"[:300]
        where = f"/settings/endings/{p.outcome}{ptr}"
        raise OpError("op.invalid_result", message, where) from None
    if not isinstance(settings, dict):
        settings = ctx.doc["settings"] = {}
    if not isinstance(endings, dict):
        endings = settings["endings"] = {}
    endings[p.outcome] = ending.model_dump(mode="json", exclude_unset=True)
    return REVERSE_PATCH
