"""Flow ops: insert, delete and move a node (with its subtree)."""

from __future__ import annotations

import copy
from typing import Any, Literal

from osp_spec.model import FLOW_NODE_TYPES
from pydantic import Field, JsonValue

from .doc import NODE, Loc, claim_id, flow_nodes, get, insert_at, locate
from .registry import Ctx, Invocation, OpError, Params, op

type Arm = Literal["then", "else", "children"]
Index = Field(default=None, ge=0)
ARMS: dict[str, tuple[str, ...]] = {"branch": ("then", "else"), "randomiser": ("children",)}


def node_list(ctx: Ctx, parent: str | None, arm: str | None) -> list[Any]:
    """The node list of `parent`/`arm` (the top-level flow when parent is None)."""
    if parent is None:
        if arm is not None:
            raise OpError("op.not_allowed", "the top-level flow has no arms; omit 'arm'")
        return ctx.doc.setdefault("flow", [])
    loc = locate(ctx, parent, NODE)
    node = get(ctx.doc, loc.path)
    kind = str(node.get("type"))
    arms = ARMS.get(kind, ())
    if not arms:
        raise OpError("op.not_allowed", f"flow node '{parent}' ({kind}) has no children")
    use = arm or arms[0]
    if use not in arms:
        raise OpError("op.not_allowed", f"'{parent}' ({kind}) has {', '.join(arms)}, not {use}")
    return node.setdefault(use, [])


def where(ctx: Ctx, loc: Loc) -> dict[str, JsonValue]:
    """`{parent, arm}` params locating a node's list ({} for the top-level flow)."""
    if len(loc.path) == 2:
        return {}
    parent = get(ctx.doc, loc.path[:-2])
    return {"parent": parent["id"], "arm": loc.path[-2]}  # type: ignore[dict-item]


class InsertFlowNode(Params):
    node: dict[str, JsonValue]  # e.g. {"type": "block", "block": "b1"}; id optional
    parent: str | None = None  # a branch or randomiser id; None = top-level flow
    arm: Arm | None = None  # branch: then (default) / else; randomiser: children
    index: int | None = Index


@op("insert_flow_node", InsertFlowNode, label="Insert flow node", area="flow")
def insert_flow_node(ctx: Ctx, p: InsertFlowNode) -> Invocation:
    """Insert a flow node (block, branch, randomiser, assign, quotaCheck, end) and any
    children it carries. A missing id is generated."""
    node = copy.deepcopy(dict(p.node))
    kind = node.get("type")
    if kind not in FLOW_NODE_TYPES:
        raise OpError(
            "op.params", f"node type must be one of {', '.join(FLOW_NODE_TYPES)}", "/node/type"
        )
    nid = claim_id(ctx, node["id"] if isinstance(node.get("id"), str) else None, str(kind))
    node = {"type": kind, "id": nid, **{k: v for k, v in node.items() if k not in ("type", "id")}}
    insert_at(node_list(ctx, p.parent, p.arm), p.index, node)
    ctx.touch()
    return Invocation(op="delete_flow_node", params={"id": nid})


class DeleteFlowNode(Params):
    id: str


@op("delete_flow_node", DeleteFlowNode, label="Delete flow node", area="flow")
def delete_flow_node(ctx: Ctx, p: DeleteFlowNode) -> Invocation:
    """Delete a flow node and its subtree. Blocks it showed stay in the survey (unused);
    nothing refers to flow node ids, so no reference can dangle."""
    loc = locate(ctx, p.id, NODE)
    params: dict[str, JsonValue] = {**where(ctx, loc), "index": loc.index}
    params["node"] = get(ctx.doc, loc.container).pop(loc.index)
    ctx.touch()
    return Invocation(op="insert_flow_node", params=params)


class MoveFlowNode(Params):
    id: str
    parent: str | None = None
    arm: Arm | None = None
    index: int | None = Index  # position in the destination after removal; None = end


@op("move_flow_node", MoveFlowNode, label="Move flow node", area="flow")
def move_flow_node(ctx: Ctx, p: MoveFlowNode) -> Invocation:
    """Move a node (with its subtree) anywhere in the flow, but not into itself."""
    loc = locate(ctx, p.id, NODE)
    back: dict[str, JsonValue] = {"id": p.id, **where(ctx, loc), "index": loc.index}
    node = get(ctx.doc, loc.path)
    if p.parent is not None and p.parent in {n["id"] for _, n in flow_nodes([node], ())}:
        raise OpError("op.not_allowed", f"cannot move '{p.id}' into itself", loc.pointer)
    get(ctx.doc, loc.container).pop(loc.index)
    ctx.touch()
    insert_at(node_list(ctx, p.parent, p.arm), p.index, node)
    ctx.touch()
    return Invocation(op="move_flow_node", params=back)
