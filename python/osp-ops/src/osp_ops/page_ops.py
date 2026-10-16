"""Page and block ops: add, delete, rename, move."""

from __future__ import annotations

import copy
from typing import Any

from pydantic import Field, JsonValue

from .doc import (
    BLOCK,
    IDENT,
    PAGE,
    claim_id,
    delete_with_refs,
    fresh_id,
    get,
    insert_at,
    locate,
    subtree_ids,
    taken_names,
)
from .question_ops import QuestionType, new_question
from .registry import REVERSE_PATCH, Ctx, Invocation, OpError, Params, op

Index = Field(default=None, ge=0)


def _new_page(ctx: Ctx, pid: str, qtype: str, also: set[str]) -> dict[str, Any]:
    # A page needs at least one item (osp-spec), so a new page starts with one question.
    qid = fresh_id(ctx.doc, "q", also={pid, *also})
    return {"id": pid, "items": [new_question(qid, qtype)]}


def _adopt(ctx: Ctx, obj: dict[str, Any], prefix: str, explicit: str | None) -> str:
    oid = obj.get("id") if isinstance(obj.get("id"), str) else explicit
    oid = claim_id(ctx, oid, prefix)
    obj["id"] = oid
    return oid


# --- pages ----------------------------------------------------------------------------


class AddPage(Params):
    block: str
    index: int | None = Index
    id: str | None = None
    question_type: QuestionType = "text"
    page: dict[str, JsonValue] | None = None  # a full page object (used by undo)


@op("add_page", AddPage, label="Add page", area="pages")
def add_page(ctx: Ctx, p: AddPage) -> Invocation:
    """Add a page to a block, starting with one new question (pages are never empty)."""
    pages = get(ctx.doc, locate(ctx, p.block, BLOCK).path)["pages"]
    if p.page is not None:
        page = copy.deepcopy(dict(p.page))
        pid = _adopt(ctx, page, "page", p.id)
    else:
        pid = claim_id(ctx, p.id, "page")
        page = _new_page(ctx, pid, p.question_type, set())
    insert_at(pages, p.index, page)
    ctx.touch()
    return Invocation(op="delete_page", params={"id": pid, "force": True})


class DeleteById(Params):
    id: str
    cascade: bool = False
    force: bool = False


@op("delete_page", DeleteById, label="Delete page", area="pages")
def delete_page(ctx: Ctx, p: DeleteById) -> Invocation:
    """Delete a page and its questions (dangling-reference policy as `delete_question`).
    A block's last page cannot be deleted: delete the block instead."""
    loc = locate(ctx, p.id, PAGE)
    pages = get(ctx.doc, loc.container)
    block_id = get(ctx.doc, loc.container[:-1])["id"]
    if len(pages) == 1:
        raise OpError(
            "op.not_allowed",
            f"'{p.id}' is the only page of block '{block_id}'; delete the block instead",
            loc.pointer,
        )
    gone = subtree_ids(get(ctx.doc, loc.path))
    page, cascaded = delete_with_refs(
        ctx, loc, gone, cascade=p.cascade, force=p.force, what=f"page '{p.id}'"
    )
    if cascaded:
        return REVERSE_PATCH
    return Invocation(op="add_page", params={"block": block_id, "index": loc.index, "page": page})


class RenamePage(Params):
    id: str
    new_id: str


@op("rename_page", RenamePage, label="Rename page", area="pages")
def rename_page(ctx: Ctx, p: RenamePage) -> Invocation:
    """Change a page's id. Pages have no title in osp-survey 0.1 and nothing refers to
    a page id, so this is safe."""
    loc = locate(ctx, p.id, PAGE)
    if p.new_id != p.id:
        if not IDENT.match(p.new_id) or len(p.new_id) > 64:
            raise OpError("op.params", f"{p.new_id[:64]!r} is not a valid id", "/new_id")
        if p.new_id in taken_names(ctx.doc):
            raise OpError("op.duplicate_id", f"id {p.new_id!r} is already used", "/new_id")
        get(ctx.doc, loc.path)["id"] = p.new_id
        ctx.touch()
    return Invocation(op="rename_page", params={"id": p.new_id, "new_id": p.id})


class MovePage(Params):
    id: str
    block: str
    index: int | None = Index  # position in the destination after removal; None = end


@op("move_page", MovePage, label="Move page", area="pages")
def move_page(ctx: Ctx, p: MovePage) -> Invocation:
    """Move a page within its block or to another block (a block may not be left empty)."""
    loc = locate(ctx, p.id, PAGE)
    src = get(ctx.doc, loc.container)
    from_block = get(ctx.doc, loc.container[:-1])["id"]
    if len(src) == 1 and from_block != p.block:
        raise OpError(
            "op.not_allowed", f"moving '{p.id}' would leave block '{from_block}' empty", loc.pointer
        )
    dest = get(ctx.doc, locate(ctx, p.block, BLOCK).path)["pages"]
    page = src.pop(loc.index)
    insert_at(dest, p.index, page)
    ctx.touch()
    return Invocation(op="move_page", params={"id": p.id, "block": from_block, "index": loc.index})


# --- blocks ---------------------------------------------------------------------------


class AddBlock(Params):
    index: int | None = Index
    id: str | None = None
    title: str | None = None
    question_type: QuestionType = "text"
    block: dict[str, JsonValue] | None = None  # a full block object (used by undo)


@op("add_block", AddBlock, label="Add block", area="blocks")
def add_block(ctx: Ctx, p: AddBlock) -> Invocation:
    """Add a block with one page and one question. It is not placed in the flow: follow
    with `insert_flow_node` (in the same transaction) to show it."""
    blocks = ctx.doc.setdefault("blocks", [])
    if p.block is not None:
        block = copy.deepcopy(dict(p.block))
        bid = _adopt(ctx, block, "block", p.id)
    else:
        bid = claim_id(ctx, p.id, "block")
        pid = fresh_id(ctx.doc, "page", also={bid})
        page = _new_page(ctx, pid, p.question_type, {bid})
        block = {"id": bid, "pages": [page]}
        if p.title is not None:
            block = {"id": bid, "title": p.title, "pages": [page]}
    insert_at(blocks, p.index, block)
    ctx.touch()
    return Invocation(op="delete_block", params={"id": bid, "force": True})


@op("delete_block", DeleteById, label="Delete block", area="blocks")
def delete_block(ctx: Ctx, p: DeleteById) -> Invocation:
    """Delete a block, its pages and questions. Rejected while the flow, a quota or a
    condition refers to it, unless `cascade` (also removes its flow nodes) or `force`."""
    loc = locate(ctx, p.id, BLOCK)
    gone = subtree_ids(get(ctx.doc, loc.path))
    block, cascaded = delete_with_refs(
        ctx, loc, gone, cascade=p.cascade, force=p.force, what=f"block '{p.id}'"
    )
    if cascaded:
        return REVERSE_PATCH
    return Invocation(op="add_block", params={"index": loc.index, "block": block})


class RenameBlock(Params):
    id: str
    title: str | None  # None removes the title


@op("rename_block", RenameBlock, label="Rename block", area="blocks")
def rename_block(ctx: Ctx, p: RenameBlock) -> Invocation:
    """Set a block's builder-only title (None removes it). Its id does not change."""
    block = get(ctx.doc, locate(ctx, p.id, BLOCK).path)
    absent = "title" not in block
    old = block.get("title")
    if p.title is None:
        block.pop("title", None)
    else:
        block["title"] = p.title
    params: dict[str, Any] = {"target": p.id, "property": "title"}
    params.update({"unset": True} if absent else {"value": old})
    return Invocation(op="set_property", params=params)


class MoveBlock(Params):
    id: str
    index: int = Field(ge=0)


@op("move_block", MoveBlock, label="Move block", area="blocks")
def move_block(ctx: Ctx, p: MoveBlock) -> Invocation:
    """Reorder the block list (the builder's outline). Participants see blocks in flow
    order, which `move_flow_node` changes."""
    loc = locate(ctx, p.id, BLOCK)
    blocks = get(ctx.doc, loc.container)
    block = blocks.pop(loc.index)
    insert_at(blocks, p.index, block)
    ctx.touch()
    return Invocation(op="move_block", params={"id": p.id, "index": loc.index})
