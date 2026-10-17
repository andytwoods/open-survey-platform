"""Matrix row ops: add, rename, move, set required, delete (task B15).

A row of matrix `m` is the single-choice variable `m_<row id>` (semantics.md §2, C2c-1),
so a row id is never changed once made: renaming changes only its label. A new row's id
is claimed like any other id: its variable `m_<row id>` must be free among all ids and
names (case-insensitively, as data names compare).
"""

from __future__ import annotations

import copy
from typing import Any

from osp_expr.ast import KEYWORDS
from osp_spec import RESERVED_NAMES
from pydantic import Field

from .doc import IDENT, QUESTION, get, handle_refs, insert_at, locate, ref_sites, taken_names
from .patch import to_pointer
from .registry import REVERSE_PATCH, Ctx, Invocation, OpError, Params, op

type Text = str | dict[str, str]
Index = Field(default=None, ge=0)
MAX_ID = 64


def _matrix(ctx: Ctx, qid: str) -> tuple[dict[str, Any], tuple[Any, ...]]:
    loc = locate(ctx, qid, QUESTION)
    q = get(ctx.doc, loc.path)
    if q.get("type") != "matrix":
        raise OpError("op.not_allowed", f"question '{qid}' is not a grid (matrix)", loc.pointer)
    return q, loc.path


def _find(q: dict[str, Any], path: tuple[Any, ...], row: str) -> int:
    for i, r in enumerate(q["rows"]):
        if r["id"] == row:
            return i
    raise OpError("op.not_found", f"grid '{q['id']}' has no row {row[:64]!r}", to_pointer(path))


def _free(ctx: Ctx, q: dict[str, Any], row: str) -> str | None:
    """Why `row` cannot be a new row id of `q`, or None."""
    if not IDENT.match(row):
        return f"{row[:64]!r} is not a valid row id"
    if any(r["id"] == row for r in q["rows"]):
        return f"row id {row!r} is already used in '{q['id']}'"
    var = f"{q['id']}_{row}"
    name = f"{q.get('name') or q['id']}_{row}"
    if len(var) > MAX_ID or len(name) > MAX_ID:
        return f"the row variable '{var[:70]}' would be longer than {MAX_ID} characters"
    taken = {t.lower() for t in taken_names(ctx.doc)}
    if var.lower() in taken or name.lower() in taken:
        return f"the row variable '{var}' is already used"
    if var in KEYWORDS or var.lower() in RESERVED_NAMES:
        return f"the row variable '{var}' is a reserved word"
    return None


def _fresh_row(ctx: Ctx, q: dict[str, Any]) -> str:
    n = len(q["rows"]) + 1
    while _free(ctx, q, f"r{n}") is not None:
        n += 1
        if n > 100_000:  # an id would be too long long before this
            raise OpError("op.not_allowed", "no free row id", "")
    return f"r{n}"


# --- add / delete ---------------------------------------------------------------------


class AddMatrixRow(Params):
    question: str
    id: str | None = None  # None: the first free `r<n>`
    label: Text = ""
    required: bool | None = None  # None: the matrix's `required`
    index: int | None = Index


@op("add_matrix_row", AddMatrixRow, label="Add grid row", area="rows")
def add_matrix_row(ctx: Ctx, p: AddMatrixRow) -> Invocation:
    """Add a row to a grid (matrix) question (default: id `r<n>`, at the end). The row's
    variable `<grid id>_<row id>` must be a free id."""
    q, path = _matrix(ctx, p.question)
    if p.id is None:
        rid = _fresh_row(ctx, q)
    else:
        why = _free(ctx, q, p.id)
        if why:
            code = "op.params" if not IDENT.match(p.id) else "op.duplicate_id"
            raise OpError(code, why, "/id")
        rid = p.id
    row: dict[str, Any] = {"id": rid, "label": copy.deepcopy(p.label)}
    if p.required is not None:
        row["required"] = p.required
    insert_at(q["rows"], p.index, row)
    return Invocation(
        op="delete_matrix_row", params={"question": p.question, "row": rid, "force": True}
    )


class DeleteMatrixRow(Params):
    question: str
    row: str
    cascade: bool = False
    force: bool = False


@op("delete_matrix_row", DeleteMatrixRow, label="Delete grid row", area="rows")
def delete_matrix_row(ctx: Ctx, p: DeleteMatrixRow) -> Invocation:
    """Delete a grid row. Rejected while conditions or piping refer to its variable
    (`<grid id>_<row id>`), unless `cascade` (clear those optional conditions, drop the
    pipes) or `force`. A grid's last row cannot be deleted."""
    q, path = _matrix(ctx, p.question)
    i = _find(q, path, p.row)
    if len(q["rows"]) == 1:
        raise OpError(
            "op.not_allowed", "a grid needs at least one row", to_pointer((*path, "rows"))
        )
    row_path = (*path, "rows", i)
    sites = ref_sites(ctx.doc, {f"{p.question}_{p.row}"}, exclude=row_path)
    cascaded = handle_refs(
        ctx, sites, cascade=p.cascade, force=p.force, what=f"row '{p.row}' of '{p.question}'"
    )
    # Cascade never edits the grid's own rows list, so the paths still hold.
    q = get(ctx.doc, path)
    row = q["rows"].pop(i)
    if cascaded:
        return REVERSE_PATCH
    inverse: dict[str, Any] = {
        "question": p.question,
        "id": row["id"],
        "label": row["label"],
        "index": i,
    }
    if row.get("required") is not None:
        inverse["required"] = row["required"]
    return Invocation(op="add_matrix_row", params=inverse)


# --- move / rename / required ---------------------------------------------------------


class MoveMatrixRow(Params):
    question: str
    row: str
    index: int = Field(ge=0)


@op("move_matrix_row", MoveMatrixRow, label="Move grid row", area="rows")
def move_matrix_row(ctx: Ctx, p: MoveMatrixRow) -> Invocation:
    """Move a grid row to `index` (counted after removing it)."""
    q, path = _matrix(ctx, p.question)
    i = _find(q, path, p.row)
    row = q["rows"].pop(i)
    insert_at(q["rows"], p.index, row)
    return Invocation(
        op="move_matrix_row", params={"question": p.question, "row": p.row, "index": i}
    )


class RenameMatrixRow(Params):
    question: str
    row: str
    label: Text


@op("rename_matrix_row", RenameMatrixRow, label="Rename grid row", area="rows")
def rename_matrix_row(ctx: Ctx, p: RenameMatrixRow) -> Invocation:
    """Set a grid row's label (a string, or one text per language). The row id, and so
    its variable and data column, stay the same."""
    q, path = _matrix(ctx, p.question)
    row = q["rows"][_find(q, path, p.row)]
    old = row["label"]
    row["label"] = copy.deepcopy(p.label)
    return Invocation(
        op="rename_matrix_row", params={"question": p.question, "row": p.row, "label": old}
    )


class SetMatrixRowRequired(Params):
    question: str
    row: str
    required: bool | None  # None: follow the matrix's `required`


@op("set_matrix_row_required", SetMatrixRowRequired, label="Set grid row required", area="rows")
def set_matrix_row_required(ctx: Ctx, p: SetMatrixRowRequired) -> Invocation:
    """Make a grid row required (true), optional (false), or follow the grid's own
    `required` (null)."""
    q, path = _matrix(ctx, p.question)
    row = q["rows"][_find(q, path, p.row)]
    old = row.get("required")
    if p.required is None:
        row.pop("required", None)
    else:
        row["required"] = p.required
    return Invocation(
        op="set_matrix_row_required",
        params={"question": p.question, "row": p.row, "required": old},
    )
