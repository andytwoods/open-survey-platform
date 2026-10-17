"""Duplicate a page or a block (task B20): a copy just after the original, with new ids
for everything in it. References inside the copy to things inside the copy follow it;
references to anything outside stay as they were."""

from __future__ import annotations

import copy
from typing import Any

from .doc import BLOCK, PAGE, PIPE, claim_id, fresh_id, get, locate
from .registry import Ctx, Invocation, Params, op

# Room for "_copy" plus a counter inside the 64-character id limit.
_STEM = 52


class DuplicateById(Params):
    id: str
    new_id: str | None = None  # the copy's own id (its contents always get fresh ones)


def _new_id(ctx: Ctx, old: str, assigned: set[str]) -> str:
    new = fresh_id(ctx.doc, f"{old[:_STEM]}_copy", exact_first=True, also=assigned)
    assigned.add(new)
    return new


def _copy_page(ctx: Ctx, page: dict[str, Any], pid: str, ids: dict[str, str]) -> dict[str, Any]:
    """The page with new ids; records old -> new (incl. grid row variables) in `ids`."""
    out = {k: copy.deepcopy(v) for k, v in page.items() if k != "items"}
    out["id"] = pid
    ids[page["id"]] = pid
    assigned = set(ids.values())
    items = []
    for q in page["items"]:
        new = _new_id(ctx, q["id"], assigned)
        ids[q["id"]] = new
        if q.get("type") == "matrix":
            for r in q.get("rows") or []:
                ids[f"{q['id']}_{r['id']}"] = f"{new}_{r['id']}"
        # No explicit `name`: the copy's data name is its new id (as duplicate_question).
        rest = {k: copy.deepcopy(v) for k, v in q.items() if k not in ("id", "name")}
        items.append({"id": new, **rest})
    out["items"] = items
    return out


def _remap(node: Any, ids: dict[str, str]) -> Any:
    """Point expression refs and `${id}` pipes at the copies, where `ids` has one."""
    if isinstance(node, dict):
        if node.get("kind") == "ref" and node.get("id") in ids:
            return {**node, "id": ids[node["id"]]}
        return {k: (v if k == "id" else _remap(v, ids)) for k, v in node.items()}
    if isinstance(node, list):
        return [_remap(v, ids) for v in node]
    if isinstance(node, str):
        return PIPE.sub(lambda m: f"${{{ids.get(m.group(1).strip(), m.group(1))}}}", node)
    return node


@op("duplicate_page", DuplicateById, label="Duplicate page", area="pages")
def duplicate_page(ctx: Ctx, p: DuplicateById) -> Invocation:
    """Copy a page (and its questions) to just after itself, in the same block."""
    loc = locate(ctx, p.id, PAGE)
    pid = claim_id(ctx, p.new_id, "page") if p.new_id is not None else _new_id(ctx, p.id, set())
    ids: dict[str, str] = {}
    page = _remap(_copy_page(ctx, get(ctx.doc, loc.path), pid, ids), ids)
    get(ctx.doc, loc.container).insert(loc.index + 1, page)
    ctx.touch()
    return Invocation(op="delete_page", params={"id": pid, "force": True})


@op("duplicate_block", DuplicateById, label="Duplicate block", area="blocks")
def duplicate_block(ctx: Ctx, p: DuplicateById) -> Invocation:
    """Copy a block (its pages and questions) to just after itself in the block list. Like
    `add_block`, the copy is not placed in the flow: follow with `insert_flow_node`."""
    loc = locate(ctx, p.id, BLOCK)
    orig = get(ctx.doc, loc.path)
    bid = claim_id(ctx, p.new_id, "block") if p.new_id is not None else _new_id(ctx, p.id, set())
    ids: dict[str, str] = {orig["id"]: bid}
    pages = []
    for page in orig["pages"]:
        pid = _new_id(ctx, page["id"], {*ids.values()})
        pages.append(_copy_page(ctx, page, pid, ids))
    block = {k: copy.deepcopy(v) for k, v in orig.items() if k != "pages"}
    block["id"] = bid
    if isinstance(block.get("title"), str) and block["title"].strip():
        block["title"] = f"{block['title']} (copy)"
    block["pages"] = pages
    get(ctx.doc, loc.container).insert(loc.index + 1, _remap(block, ids))
    ctx.touch()
    return Invocation(op="delete_block", params={"id": bid, "force": True})
