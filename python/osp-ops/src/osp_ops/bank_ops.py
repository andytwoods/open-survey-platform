"""Question bank ops (planning/question-bank.md §4): insert a bank item's fragment into a
survey as one op (one undo step), and drop the provenance an inserted object carries.

`insert_bank_item` takes the fragment of a bank item (`osp_spec.bank.Fragment`: one
question, page or block with the shared choice lists it uses and its computed scoring
variables) and a `Source` record. It checks the fragment on its own first (nothing that
refers outside it, nothing a survey could not hold), claims a free id for everything in
it (the fragment's own ids where free, else `_2`, `_3` ...), points every expression ref,
`${pipe}` and `choiceList` at the new ids, reuses a choice list the survey already has
with the same choices, appends the rest, writes `source` on the inserted object (its
page's and its block's questions inherit it: `osp_spec.bank.sources`) and, for a block,
optionally places a flow node. The inverse is the exact reverse patch, so undo removes
everything the insert added and nothing else.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from typing import Any

from osp_spec import Source
from osp_spec.bank import canonical_json, check_fragment, fragment_checksum, fragment_kind
from pydantic import Field, JsonValue, ValidationError

from .doc import (
    BLOCK,
    NODE,
    PAGE,
    QUESTION,
    get,
    insert_at,
    is_free_id,
    locate,
    remap_ids,
)
from .registry import REVERSE_PATCH, Ctx, Invocation, OpError, Params, diag, op

Index = Field(default=None, ge=0)
ID_MAX = 64


class FlowPlacement(Params):
    """Where a block's flow node goes: right after node `after` (in that node's list), or
    at the end of the top-level flow when `after` is null."""

    after: str | None = None


class InsertBankItem(Params):
    fragment: dict[str, JsonValue]  # osp_spec.bank.Fragment as JSON
    source: dict[str, JsonValue]  # osp_spec.Source: {bank, version, library, checksum?}
    page: str | None = None  # a question's destination page
    block: str | None = None  # a page's destination block
    index: int | None = Index  # position in the destination list; None = end
    flow: FlowPlacement | None = None  # a block's flow node; None = not placed in the flow


# --- id claiming ------------------------------------------------------------------------


class _Claims:
    """Fresh ids for the fragment: the fragment's own where free, else `_2`, `_3` ...
    Records old -> new (incl. matrix row variables) for `remap_ids`."""

    def __init__(self, ctx: Ctx) -> None:
        self.ctx = ctx
        self.ids: dict[str, str] = {}
        self.names: dict[str, str] = {}
        self.assigned: set[str] = set()

    def free(self, candidate: str, rows: Sequence[str]) -> bool:
        return all(
            is_free_id(self.ctx.doc, c, also=self.assigned)
            for c in (candidate, *(f"{candidate}_{r}" for r in rows))
        )

    def pick(self, base: str, rows: Sequence[str] = ()) -> str:
        if self.free(base, rows):
            self.assigned.add(base)
            return base
        n = 2
        while True:
            suffix = f"_{n}"
            cand = f"{base[: ID_MAX - len(suffix)]}{suffix}"
            if self.free(cand, rows):
                self.assigned.add(cand)
                return cand
            n += 1

    def claim(self, old: str, rows: Sequence[str] = ()) -> str:
        new = self.pick(old, rows)
        self.ids[old] = new
        for r in rows:
            self.ids[f"{old}_{r}"] = f"{new}_{r}"
        return new

    def claim_name(self, name: str) -> None:
        if name not in self.names:
            self.names[name] = self.pick(name)


def _rows(q: dict[str, Any]) -> list[str]:
    if q.get("type") != "matrix":
        return []
    return [r["id"] for r in q.get("rows") or [] if isinstance(r, dict)]


def _claim_object(claims: _Claims, obj: dict[str, Any], kind: str) -> None:
    claims.claim(obj["id"], _rows(obj) if kind == "question" else [])
    if kind == "question":
        if isinstance(obj.get("name"), str):
            claims.claim_name(obj["name"])
        return
    for child in obj["pages"] if kind == "block" else obj["items"]:
        _claim_object(claims, child, "page" if kind == "block" else "question")


def _rebuild(obj: dict[str, Any], kind: str, claims: _Claims) -> dict[str, Any]:
    """The object with its new ids (and names), without any `source` it carried."""
    children = {"block": "pages", "page": "items"}.get(kind)
    out: dict[str, Any] = {"id": claims.ids[obj["id"]]}
    for k, v in obj.items():
        if k in ("id", "source", children):
            continue
        out[k] = copy.deepcopy(v)
    if kind == "question" and isinstance(out.get("name"), str):
        out["name"] = claims.names[out["name"]]
    if children is not None:
        out[children] = [
            _rebuild(c, "page" if kind == "block" else "question", claims) for c in obj[children]
        ]
    return out


# --- insert_bank_item -------------------------------------------------------------------


def _checked_fragment(raw: dict[str, Any]) -> tuple[dict[str, Any], str]:
    fragment = copy.deepcopy(raw)
    errors = [d for d in check_fragment(fragment) if d.severity == "error"]
    if errors:
        first, *rest = errors
        raise OpError(
            "op.params",
            f"the fragment cannot be inserted: {first.message}",
            "/fragment" + first.pointer,
            *[diag("op.params", d.message, "/fragment" + d.pointer) for d in rest[:19]],
        )
    kind = fragment_kind(fragment)
    assert kind is not None  # check_fragment guarantees exactly one object
    return fragment, kind


def _source(raw: dict[str, Any], fragment: dict[str, Any], local_id: str) -> dict[str, Any]:
    try:
        src = Source.model_validate(raw)
    except ValidationError as err:
        e = err.errors(include_url=False, include_input=False)[0]
        where = "/source" + "".join(f"/{part}" for part in e["loc"] if isinstance(part, str))
        raise OpError("op.params", f"source: {str(e['msg'])[:200]}", where) from None
    out = src.model_dump(mode="json", exclude_none=True)
    out["item"] = local_id  # the id the object had inside the fragment
    out.setdefault("checksum", fragment_checksum(fragment))
    return out


def _destination(ctx: Ctx, p: InsertBankItem, kind: str) -> list[Any]:
    given = {"page": p.page, "block": p.block, "flow": p.flow}
    wanted = {"question": "page", "page": "block", "block": "flow"}[kind]
    for key, value in given.items():
        if value is not None and key != wanted:
            raise OpError("op.params", f"`{key}` does not apply when inserting a {kind}", f"/{key}")
    if kind == "question":
        if p.page is None:
            raise OpError("op.params", "a question needs a destination `page`", "/page")
        return get(ctx.doc, locate(ctx, p.page, PAGE).path)["items"]
    if kind == "page":
        if p.block is None:
            raise OpError("op.params", "a page needs a destination `block`", "/block")
        return get(ctx.doc, locate(ctx, p.block, BLOCK).path)["pages"]
    return ctx.doc.setdefault("blocks", [])


@op("insert_bank_item", InsertBankItem, label="Insert bank item", area="bank")
def insert_bank_item(ctx: Ctx, p: InsertBankItem) -> Invocation:
    """Insert a bank item's fragment (a question into `page`, a page into `block`, or a
    block, optionally placed in the flow with `flow`) with its choice lists and scoring
    variables, under fresh ids where the fragment's clash, and `source` set on it. A
    fragment that refers outside itself, or that a survey could not hold, is rejected
    whole. One op, one undo."""
    fragment, kind = _checked_fragment(dict(p.fragment))
    obj = fragment[kind]
    source = _source(dict(p.source), fragment, obj["id"])
    dest = _destination(ctx, p, kind)
    flow_list: list[Any] | None = None
    flow_index: int | None = None
    if kind == "block" and p.flow is not None:
        if p.flow.after is None:
            flow_list = ctx.doc.setdefault("flow", [])
        else:
            loc = locate(ctx, p.flow.after, NODE)
            flow_list, flow_index = get(ctx.doc, loc.container), loc.index + 1

    claims = _Claims(ctx)
    _claim_object(claims, obj, kind)
    # A choice list with the same choices as one the survey has is reused, not added.
    existing: dict[str, str] = {}
    for cl in ctx.doc.get("choiceLists") or []:
        existing.setdefault(canonical_json(cl["choices"]), cl["id"])
    new_lists: list[dict[str, Any]] = []
    for cl in fragment.get("choiceLists") or []:
        key = canonical_json(cl["choices"])
        if key in existing:
            claims.ids[cl["id"]] = existing[key]
        else:
            existing[key] = claims.claim(cl["id"])
            new_lists.append({**copy.deepcopy(cl), "id": existing[key]})
    new_vars: list[dict[str, Any]] = []
    for v in fragment.get("variables") or []:
        new_vars.append({**copy.deepcopy(v), "id": claims.claim(v["id"])})
        if isinstance(v.get("name"), str):
            claims.claim_name(v["name"])
            new_vars[-1]["name"] = claims.names[v["name"]]
    inserted = remap_ids(_rebuild(obj, kind, claims), claims.ids)
    inserted["source"] = source
    if new_lists:
        ctx.doc.setdefault("choiceLists", []).extend(remap_ids(new_lists, claims.ids))
    if new_vars:
        ctx.doc.setdefault("variables", []).extend(remap_ids(new_vars, claims.ids))
    insert_at(dest, p.index, inserted)
    if flow_list is not None:
        node_id = claims.pick(f"n_{inserted['id'][: ID_MAX - 2]}")
        insert_at(flow_list, flow_index, {"type": "block", "id": node_id, "block": inserted["id"]})
    ctx.touch()
    return REVERSE_PATCH


# --- clear_source -----------------------------------------------------------------------


class ClearSource(Params):
    target: str  # a question, page or block id


@op("clear_source", ClearSource, label="Detach from bank item", area="bank")
def clear_source(ctx: Ctx, p: ClearSource) -> Invocation:
    """Drop the bank provenance (`source`) of a question, page or block, for an
    instrument edited so far that it should no longer be listed as that bank item.
    Rejected when the target carries none (an inherited source is cleared on the page or
    block that holds it). Undo puts it back."""
    loc = locate(ctx, p.target, QUESTION, PAGE, BLOCK)
    obj = get(ctx.doc, loc.path)
    if obj.get("source") is None:
        raise OpError(
            "op.not_applicable", f"'{p.target[:64]}' carries no bank provenance", loc.pointer
        )
    del obj["source"]
    ctx.touch()
    return REVERSE_PATCH
