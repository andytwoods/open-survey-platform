"""Question ops: add, delete, duplicate, move."""

from __future__ import annotations

import copy
from typing import Any, Literal

from pydantic import Field, JsonValue

from .doc import (
    PAGE,
    PIPE,
    QUESTION,
    claim_id,
    delete_with_refs,
    fresh_id,
    get,
    insert_at,
    locate,
    subtree_ids,
)
from .registry import REVERSE_PATCH, Ctx, Invocation, OpError, Params, op

type QuestionType = Literal[
    "integer", "decimal", "text", "single", "multi", "date", "matrix", "slider", "note"
]
Index = Field(default=None, ge=0)

DEFAULT_LABEL = "New question"
DEFAULT_CHOICES: list[dict[str, Any]] = [{"value": 1, "label": "Option 1"}]
DEFAULT_ROWS: list[dict[str, Any]] = [
    {"id": "r1", "label": "Row 1"},
    {"id": "r2", "label": "Row 2"},
]


def new_question(qid: str, qtype: str, label: JsonValue = None) -> dict[str, Any]:
    q: dict[str, Any] = {"id": qid, "type": qtype}
    q["label"] = DEFAULT_LABEL if label is None else copy.deepcopy(label)
    if qtype in ("single", "multi", "matrix"):
        q["choices"] = copy.deepcopy(DEFAULT_CHOICES)
    if qtype == "matrix":
        q["rows"] = copy.deepcopy(DEFAULT_ROWS)
    return q


def _page_of(ctx: Ctx, page_id: str) -> list[Any]:
    return get(ctx.doc, locate(ctx, page_id, PAGE).path)["items"]


def _owner_page_id(ctx: Ctx, qpath: tuple[Any, ...]) -> str:
    return get(ctx.doc, qpath[:-2])["id"]


# --- add ------------------------------------------------------------------------------


class AddQuestion(Params):
    page: str
    type: QuestionType = "text"
    index: int | None = Index
    id: str | None = None
    label: str | dict[str, str] | None = None
    question: dict[str, JsonValue] | None = None  # a full question object (used by undo)


@op("add_question", AddQuestion, label="Add question", area="questions")
def add_question(ctx: Ctx, p: AddQuestion) -> Invocation:
    """Insert a new question into a page (default: at the end). With `question`, insert
    that object as given (an id is generated if it has none)."""
    items = _page_of(ctx, p.page)
    if p.question is not None:
        q = copy.deepcopy(dict(p.question))
        qid = claim_id(ctx, q.get("id") if isinstance(q.get("id"), str) else p.id, "q")
        q["id"] = qid
    else:
        qid = claim_id(ctx, p.id, "q")
        q = new_question(qid, p.type, p.label)
    insert_at(items, p.index, q)
    ctx.touch()
    return Invocation(op="delete_question", params={"id": qid, "force": True})


# --- delete ---------------------------------------------------------------------------


class DeleteQuestion(Params):
    id: str
    cascade: bool = False
    force: bool = False


@op("delete_question", DeleteQuestion, label="Delete question", area="questions")
def delete_question(ctx: Ctx, p: DeleteQuestion) -> Invocation:
    """Delete a question. Rejected while conditions, piping or other questions refer to
    it, unless `cascade` (clear those conditions, drop the `${id}` pipes) or `force`."""
    loc = locate(ctx, p.id, QUESTION)
    page_id = _owner_page_id(ctx, loc.path)
    if len(get(ctx.doc, loc.container)) == 1:
        raise OpError(
            "op.not_allowed",
            f"'{p.id}' is the only question on page '{page_id}'; delete the page instead",
            loc.pointer,
        )
    q, cascaded = delete_with_refs(
        ctx,
        loc,
        subtree_ids(get(ctx.doc, loc.path)),  # a grid: its row variables too
        cascade=p.cascade,
        force=p.force,
        what=f"question '{p.id}'",
    )
    if cascaded:
        return REVERSE_PATCH
    return Invocation(
        op="add_question", params={"page": page_id, "index": loc.index, "question": q}
    )


# --- duplicate ------------------------------------------------------------------------


class DuplicateQuestion(Params):
    id: str
    new_id: str | None = None


def _rename_self(node: Any, old: str, new: str) -> Any:
    """Point the copy's own references (`constraint` on itself, `${old}` pipes) at it."""
    if isinstance(node, dict):
        if node.get("kind") == "ref" and node.get("id") == old:
            return {**node, "id": new}
        return {k: _rename_self(v, old, new) for k, v in node.items()}
    if isinstance(node, list):
        return [_rename_self(v, old, new) for v in node]
    if isinstance(node, str):
        return PIPE.sub(lambda m: f"${{{new}}}" if m.group(1).strip() == old else m.group(0), node)
    return node


@op("duplicate_question", DuplicateQuestion, label="Duplicate question", area="questions")
def duplicate_question(ctx: Ctx, p: DuplicateQuestion) -> Invocation:
    """Copy a question to just after itself, with a new id and no explicit `name`
    (so its data name is the new id). The copy's references to itself follow it."""
    loc = locate(ctx, p.id, QUESTION)
    if p.new_id is None:
        new_id = fresh_id(ctx.doc, f"{p.id[:58]}_copy", exact_first=True)
    else:
        new_id = claim_id(ctx, p.new_id, "q")
    orig = get(ctx.doc, loc.path)
    copy_ = {k: _rename_self(v, p.id, new_id) for k, v in orig.items() if k not in ("id", "name")}
    copy_ = {"id": new_id, **copy_}
    get(ctx.doc, loc.container).insert(loc.index + 1, copy_)
    ctx.touch()
    return Invocation(op="delete_question", params={"id": new_id, "force": True})


# --- move -----------------------------------------------------------------------------


class MoveQuestion(Params):
    id: str
    page: str  # destination page (any block)
    index: int | None = Index  # position in the destination after removal; None = end


@op("move_question", MoveQuestion, label="Move question", area="questions")
def move_question(ctx: Ctx, p: MoveQuestion) -> Invocation:
    """Move a question within its page or to another page (in any block). A page may not
    be left empty: delete or fill it first."""
    loc = locate(ctx, p.id, QUESTION)
    from_page = _owner_page_id(ctx, loc.path)
    src = get(ctx.doc, loc.container)
    if len(src) == 1 and from_page != p.page:
        raise OpError(
            "op.not_allowed", f"moving '{p.id}' would leave page '{from_page}' empty", loc.pointer
        )
    dest = _page_of(ctx, p.page)
    q = src.pop(loc.index)
    insert_at(dest, p.index, q)
    ctx.touch()
    return Invocation(
        op="move_question", params={"id": p.id, "page": from_page, "index": loc.index}
    )
