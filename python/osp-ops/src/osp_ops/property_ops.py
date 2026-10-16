"""`set_property`: set or unset one field of any addressable object, validated against
the `osp-spec` model (the property must be a field of that object's model class)."""

from __future__ import annotations

import copy
from typing import Any

from osp_spec import model as m
from pydantic import BaseModel, JsonValue

from .doc import BLOCK, CHOICE_LIST, NODE, PAGE, QUESTION, QUOTA, VARIABLE, get, locate
from .patch import to_pointer
from .registry import REVERSE_PATCH, Ctx, Invocation, OpError, Params, op

QUESTION_CLASSES: dict[str, type[BaseModel]] = {
    "integer": m.IntegerQuestion,
    "decimal": m.DecimalQuestion,
    "text": m.TextQuestion,
    "single": m.SingleQuestion,
    "multi": m.MultiQuestion,
    "date": m.DateQuestion,
    "note": m.NoteQuestion,
}
NODE_CLASSES: dict[str, type[BaseModel]] = {
    "block": m.BlockNode,
    "branch": m.BranchNode,
    "randomiser": m.RandomiserNode,
    "assign": m.AssignNode,
    "quotaCheck": m.QuotaCheckNode,
    "end": m.EndNode,
}
VARIABLE_CLASSES: dict[str, type[BaseModel]] = {
    "embedded": m.EmbeddedVariable,
    "assigned": m.AssignedVariable,
    "computed": m.ComputedVariable,
}
FIXED_CLASSES: dict[str, type[BaseModel]] = {
    PAGE: m.Page,
    BLOCK: m.Block,
    CHOICE_LIST: m.ChoiceList,
    QUOTA: m.Quota,
}
# Pseudo-targets: a leading "/" can never be an id.
SINGLETONS: dict[str, tuple[tuple[str, ...], type[BaseModel]]] = {
    "/metadata": (("metadata",), m.Metadata),
    "/settings": (("settings",), m.Settings),
}
# Identity and discriminators are never edited in place; child collections have their
# own ops (which check references).
FORBIDDEN = frozenset({"id", "type", "kind", "items", "pages", "then", "else", "children"})


def model_fields(cls: type[BaseModel]) -> list[str]:
    return [f.alias or name for name, f in cls.model_fields.items()]


def resolve(ctx: Ctx, target: str) -> tuple[tuple[Any, ...], type[BaseModel]]:
    """Path to the target object and its model class."""
    if target in SINGLETONS:
        path, cls = SINGLETONS[target]
        if path[0] == "settings" and "settings" not in ctx.doc:
            ctx.doc["settings"] = {}  # `settings` is optional; creating it is a no-op value
        return path, cls
    loc = locate(ctx, target)
    obj = get(ctx.doc, loc.path)
    cls: type[BaseModel] | None
    if loc.kind == QUESTION:
        cls = QUESTION_CLASSES.get(obj.get("type"))
    elif loc.kind == NODE:
        cls = NODE_CLASSES.get(obj.get("type"))
    elif loc.kind == VARIABLE:
        cls = VARIABLE_CLASSES.get(obj.get("kind"))
    else:
        cls = FIXED_CLASSES.get(loc.kind)
    assert cls is not None  # the survey parsed, so the discriminator is known
    return loc.path, cls


class SetProperty(Params):
    target: str  # an object id, or "/metadata" or "/settings"
    property: str
    value: JsonValue = None
    unset: bool = False  # remove the key (back to the model default)


@op("set_property", SetProperty, label="Set property", area="questions")
def set_property(ctx: Ctx, p: SetProperty) -> Invocation:
    """Set (or with `unset`, remove) one field of a question, page, block, choice list,
    variable, quota, flow node, `/metadata` or `/settings`. The new value is validated
    by the survey model; `id`, `type`, `kind` and child collections are not editable."""
    had_settings = "settings" in ctx.doc
    path, cls = resolve(ctx, p.target)
    allowed = model_fields(cls)
    if p.property in FORBIDDEN or p.property not in allowed:
        editable = ", ".join(f for f in allowed if f not in FORBIDDEN)
        raise OpError(
            "op.not_allowed",
            f"{p.property[:40]!r} is not an editable property of {cls.__name__} "
            f"(editable: {editable})",
            to_pointer((*path, p.property[:64])),
        )
    obj = get(ctx.doc, path)
    absent = p.property not in obj
    old = copy.deepcopy(obj.get(p.property))
    if p.unset:
        obj.pop(p.property, None)
    else:
        obj[p.property] = copy.deepcopy(p.value)
    if not had_settings and p.target == "/settings":
        # Undo must also drop the `settings` object it created.
        if not obj:
            del ctx.doc["settings"]
        return REVERSE_PATCH
    ctx.touch()
    if absent:
        return Invocation(
            op="set_property", params={"target": p.target, "property": p.property, "unset": True}
        )
    return Invocation(
        op="set_property", params={"target": p.target, "property": p.property, "value": old}
    )
