"""`set_custom_property`: set or remove one of a question's lab-defined custom properties
(planning/property-profiles.md §4). The only editing path for `custom`, so every change
has an exact inverse; `set_property` refuses the `custom` object as a whole."""

from __future__ import annotations

import copy

from osp_spec.model import MAX_CUSTOM_PROPERTIES

from .doc import QUESTION, get, locate
from .patch import to_pointer
from .registry import Ctx, Invocation, OpError, Params, op

CUSTOM = "custom"


class SetCustomProperty(Params):
    target: str  # a question id
    key: str  # ^[a-z][a-z0-9_]{0,39}$ (the model checks it)
    value: str | int | float | bool | None = None
    unset: bool = False  # remove the key (and the `custom` object when it empties)


@op("set_custom_property", SetCustomProperty, label="Set custom property", area="questions")
def set_custom_property(ctx: Ctx, p: SetCustomProperty) -> Invocation:
    """Set (or with `unset`, remove) one key of a question's `custom` object: the lab's
    own annotations, defined by its panel profile. Values are scalars; the survey model
    checks the key and value shape. Only questions carry custom properties."""
    loc = locate(ctx, p.target, QUESTION)
    q = get(ctx.doc, loc.path)
    custom = q.get(CUSTOM)
    custom = dict(custom) if isinstance(custom, dict) else {}
    had = p.key in custom
    old = copy.deepcopy(custom.get(p.key))
    if p.unset:
        custom.pop(p.key, None)
    else:
        if p.value is None:
            raise OpError(
                "op.params",
                "a custom property needs a value (text, number or true/false), or `unset`",
                loc.pointer + to_pointer((CUSTOM, p.key[:64])),
            )
        if not had and len(custom) >= MAX_CUSTOM_PROPERTIES:
            raise OpError(
                "op.not_allowed",
                f"a question may carry at most {MAX_CUSTOM_PROPERTIES} custom properties",
                loc.pointer + to_pointer((CUSTOM,)),
            )
        custom[p.key] = p.value
    if custom:
        q[CUSTOM] = custom
    else:
        q.pop(CUSTOM, None)
    ctx.touch()
    if not had:
        params = {"target": p.target, "key": p.key, "unset": True}
    else:
        params = {"target": p.target, "key": p.key, "value": old}
    return Invocation(op="set_custom_property", params=params)
