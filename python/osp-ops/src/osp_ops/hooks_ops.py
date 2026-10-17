"""Hooks op: `set_hooks` (runtime-design.md §7a; Survey settings "Researcher hooks", R11).

The hook manifest is a survey-level object (`osp_spec.hooks.Hooks`): the researcher's
script plus the events it handles and what each handler reads. The whole manifest is
replaced at once (as `set_consent` and `set_theme` do), so the script and its declarations
never drift apart. The op checks the manifest's shape and stores its normalised form;
reference problems (a handler reading an unknown question) come back as the validator's
`hooks.*` diagnostics, which block publishing and preview until fixed.

The app layer treats a transaction that changes `hooks` as a code change: it is written to
the audit log (`osp_app.builder`), and only owners and editors may edit a survey at all.
"""

from __future__ import annotations

from osp_spec.hooks import Hooks, hooks_json
from pydantic import JsonValue, ValidationError

from .registry import REVERSE_PATCH, Ctx, Invocation, OpError, Params, op


class SetHooks(Params):
    hooks: dict[str, JsonValue] | None = None  # None: the survey runs no custom code


def _first_problem(err: ValidationError) -> tuple[str, str]:
    e = err.errors(include_url=False, include_input=False)[0]
    parts = [p for p in e["loc"] if isinstance(p, (str, int)) and not str(p).startswith("[")]
    ptr = "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)
    return ptr, str(e["msg"])


@op("set_hooks", SetHooks, label="Set researcher hooks", area="survey")
def set_hooks(ctx: Ctx, p: SetHooks) -> Invocation:
    """Set the survey's hook manifest (`osp-hooks/1`: `source`, `handlers` with `reads`,
    `writes` and an optional `timeoutMs` per event, optional `urlParams`, `redirects`,
    `parent`), or with `hooks: null` remove it. The manifest must have the manifest shape;
    its references are checked by the validator (`hooks.*` diagnostics)."""
    if p.hooks is None:
        if "hooks" not in ctx.doc:
            return REVERSE_PATCH  # nothing to remove
        del ctx.doc["hooks"]
        ctx.touch()
        return REVERSE_PATCH
    try:
        manifest = Hooks.model_validate(p.hooks)
    except ValidationError as err:
        ptr, msg = _first_problem(err)
        message = f"not a valid hook manifest: {msg}"[:300]
        raise OpError("op.invalid_result", message, "/hooks" + ptr) from None
    ctx.doc["hooks"] = hooks_json(manifest)
    ctx.touch()
    return REVERSE_PATCH
