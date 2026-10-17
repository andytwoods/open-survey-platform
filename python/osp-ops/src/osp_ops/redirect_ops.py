"""Redirect template op: `set_redirect_template` (end-of-survey plan §4.2, task EN2).

`settings.redirectTemplates` maps a name to an https URL template with `{name}` placeholders
after the origin, each with the pattern its value must match (the shape `hooks.redirects`
has always had: `osp_spec.model.RedirectTemplate`). An ending's redirect (`set_ending` with
`redirect`) and hook code (`setEndRedirect`) name a template; the participant app fills it
with pattern-checked, URL-encoded values and re-checks the origin before navigating.

One op sets or removes one template as a whole. The URL rules (https, no placeholder in the
origin, placeholders and params agree, patterns compile) are the validator's
`redirect.template` diagnostics, which block publishing; the app layer audits a transaction
that changes templates or redirects (`osp_app.builder`), as it does for hook code.
"""

from __future__ import annotations

from osp_spec.model import Name, RedirectTemplate
from pydantic import JsonValue, ValidationError

from .registry import REVERSE_PATCH, Ctx, Invocation, OpError, Params, op


class SetRedirectTemplate(Params):
    name: Name
    template: dict[str, JsonValue] | None = None  # None: remove the template


@op("set_redirect_template", SetRedirectTemplate, label="Set redirect template", area="survey")
def set_redirect_template(ctx: Ctx, p: SetRedirectTemplate) -> Invocation:
    """Set one end-of-survey redirect template (`url`: an https URL with `{name}`
    placeholders after the origin; `params`: every placeholder, each with an optional
    `pattern` its value must match in full), or with `template: null` remove it. Endings
    that name a removed template get the validator's `redirect.unknown_template` error."""
    settings = ctx.doc.get("settings")
    templates = settings.get("redirectTemplates") if isinstance(settings, dict) else None
    if p.template is None:
        if not isinstance(settings, dict) or not isinstance(templates, dict):
            return REVERSE_PATCH  # nothing to remove
        if p.name not in templates:
            return REVERSE_PATCH
        del templates[p.name]
        if not templates:
            del settings["redirectTemplates"]
        return REVERSE_PATCH
    try:
        template = RedirectTemplate.model_validate(p.template)
    except ValidationError as err:
        e = err.errors(include_url=False, include_input=False)[0]
        parts = [str(x) for x in e["loc"] if isinstance(x, (str, int))]
        ptr = "".join("/" + x.replace("~", "~0").replace("/", "~1") for x in parts)
        message = f"not a valid redirect template: {e['msg']}"[:300]
        where = f"/settings/redirectTemplates/{p.name}{ptr}"
        raise OpError("op.invalid_result", message, where) from None
    if not isinstance(settings, dict):
        settings = ctx.doc["settings"] = {}
    if not isinstance(templates, dict):
        templates = settings["redirectTemplates"] = {}
    templates[p.name] = template.model_dump(mode="json", exclude_none=True)
    return REVERSE_PATCH
