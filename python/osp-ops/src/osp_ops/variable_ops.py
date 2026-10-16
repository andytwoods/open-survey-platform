"""Variable ops: add, delete (embedded, assigned and computed variables)."""

from __future__ import annotations

import copy

from pydantic import Field, JsonValue

from .doc import VARIABLE, claim_id, delete_with_refs, insert_at, locate
from .registry import REVERSE_PATCH, Ctx, Invocation, Params, op


class AddVariable(Params):
    # The full variable, e.g. {"kind": "embedded", "param": "src"}; id optional.
    variable: dict[str, JsonValue]
    index: int | None = Field(default=None, ge=0)


@op("add_variable", AddVariable, label="Add variable", area="variables")
def add_variable(ctx: Ctx, p: AddVariable) -> Invocation:
    """Add a variable. The object is validated by the survey model; a missing id is
    generated. An `assigned` variable also needs an `assign` flow node to be set."""
    v = copy.deepcopy(dict(p.variable))
    vid = claim_id(ctx, v["id"] if isinstance(v.get("id"), str) else None, "var")
    v = {"id": vid, **{k: x for k, x in v.items() if k != "id"}}
    insert_at(ctx.doc.setdefault("variables", []), p.index, v)
    ctx.touch()
    return Invocation(op="delete_variable", params={"id": vid, "force": True})


class DeleteVariable(Params):
    id: str
    cascade: bool = False
    force: bool = False


@op("delete_variable", DeleteVariable, label="Delete variable", area="variables")
def delete_variable(ctx: Ctx, p: DeleteVariable) -> Invocation:
    """Delete a variable. Rejected while conditions, piping or `assign` nodes refer to
    it, unless `cascade` (clears optional conditions, drops pipes, removes it from assign
    nodes, and empty assign nodes) or `force`."""
    loc = locate(ctx, p.id, VARIABLE)
    v, cascaded = delete_with_refs(
        ctx, loc, {p.id}, cascade=p.cascade, force=p.force, what=f"variable '{p.id}'"
    )
    if cascaded:
        return REVERSE_PATCH
    return Invocation(op="add_variable", params={"variable": v, "index": loc.index})
