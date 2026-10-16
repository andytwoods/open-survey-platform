"""Shared choice list ops: create, delete."""

from __future__ import annotations

import copy
from typing import Any

from pydantic import Field, JsonValue

from .doc import CHOICE_LIST, claim_id, delete_with_refs, get, insert_at, locate
from .question_ops import DEFAULT_CHOICES
from .registry import REVERSE_PATCH, Ctx, Invocation, Params, op


class CreateChoiceList(Params):
    id: str | None = None
    choices: list[dict[str, JsonValue]] | None = None  # default: one "Option 1"
    index: int | None = Field(default=None, ge=0)


@op("create_choice_list", CreateChoiceList, label="Create choice list", area="choiceLists")
def create_choice_list(ctx: Ctx, p: CreateChoiceList) -> Invocation:
    """Create a shared choice list. Questions use it via `set_property(choiceList)`."""
    lid = claim_id(ctx, p.id, "list")
    choices: list[Any] = copy.deepcopy(p.choices if p.choices is not None else DEFAULT_CHOICES)
    insert_at(ctx.doc.setdefault("choiceLists", []), p.index, {"id": lid, "choices": choices})
    ctx.touch()
    return Invocation(op="delete_choice_list", params={"id": lid, "force": True})


class DeleteChoiceList(Params):
    id: str
    cascade: bool = False
    force: bool = False


@op("delete_choice_list", DeleteChoiceList, label="Delete choice list", area="choiceLists")
def delete_choice_list(ctx: Ctx, p: DeleteChoiceList) -> Invocation:
    """Delete a shared choice list. Rejected while questions use it, unless `cascade`
    (each such question gets an inline copy of the choices, so no data codes change) or
    `force`."""
    loc = locate(ctx, p.id, CHOICE_LIST)
    choices = get(ctx.doc, loc.path)["choices"]
    cl, cascaded = delete_with_refs(
        ctx,
        loc,
        {p.id},
        cascade=p.cascade,
        force=p.force,
        what=f"choice list '{p.id}'",
        inline={p.id: choices},
    )
    if cascaded:
        return REVERSE_PATCH
    return Invocation(
        op="create_choice_list",
        params={"id": cl["id"], "choices": cl["choices"], "index": loc.index},
    )
