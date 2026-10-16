"""Helpers over the survey as plain JSON: locating objects by id, fresh ids, and finding
(and repairing) references. Ops only run on structurally valid surveys, so the shapes
here are the `osp-spec` model's shapes.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from osp_expr.ast import KEYWORDS
from osp_spec import RESERVED_NAMES

from .patch import to_pointer
from .registry import Ctx, OpError, diag

type Json = Any
type Path = tuple[str | int, ...]

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PIPE = re.compile(r"\$\{([^}]*)\}")

# Kinds of addressable object.
QUESTION, PAGE, BLOCK, CHOICE_LIST, VARIABLE, QUOTA, NODE = (
    "question",
    "page",
    "block",
    "choiceList",
    "variable",
    "quota",
    "node",
)


@dataclass(frozen=True)
class Loc:
    kind: str
    path: Path  # path to the object itself; path[:-1] is its list, path[-1] its index

    @property
    def container(self) -> Path:
        return self.path[:-1]

    @property
    def index(self) -> int:
        i = self.path[-1]
        assert isinstance(i, int)
        return i

    @property
    def pointer(self) -> str:
        return to_pointer(self.path)


# --- paths ----------------------------------------------------------------------------


def get(doc: Json, path: Path) -> Json:
    cur = doc
    for p in path:
        cur = cur[p]
    return cur


def flow_nodes(nodes: list[Json], path: Path) -> Iterator[tuple[Path, Json]]:
    """Every flow node with its path, depth first, parents before children."""
    for i, n in enumerate(nodes):
        np = (*path, i)
        yield np, n
        if n.get("type") == "branch":
            yield from flow_nodes(n.get("then", []), (*np, "then"))
            yield from flow_nodes(n.get("else", []), (*np, "else"))
        elif n.get("type") == "randomiser":
            yield from flow_nodes(n.get("children", []), (*np, "children"))


def build_index(doc: Json) -> dict[str, Loc]:
    """Id -> location. With duplicate ids (a broken survey) the first one wins."""
    out: dict[str, Loc] = {}

    def claim(id_: Any, loc: Loc) -> None:
        if isinstance(id_, str):
            out.setdefault(id_, loc)

    for i, cl in enumerate(doc.get("choiceLists", [])):
        claim(cl["id"], Loc(CHOICE_LIST, ("choiceLists", i)))
    for i, b in enumerate(doc.get("blocks", [])):
        claim(b["id"], Loc(BLOCK, ("blocks", i)))
        for j, page in enumerate(b["pages"]):
            claim(page["id"], Loc(PAGE, ("blocks", i, "pages", j)))
            for k, q in enumerate(page["items"]):
                claim(q["id"], Loc(QUESTION, ("blocks", i, "pages", j, "items", k)))
    for i, v in enumerate(doc.get("variables", [])):
        claim(v["id"], Loc(VARIABLE, ("variables", i)))
    for i, quota in enumerate(doc.get("quotas", [])):
        claim(quota["id"], Loc(QUOTA, ("quotas", i)))
    for path, n in flow_nodes(doc.get("flow", []), ("flow",)):
        claim(n["id"], Loc(NODE, path))
    return out


def locate(ctx: Ctx, id_: str, *kinds: str) -> Loc:
    loc = ctx.index().get(id_)
    if loc is None or (kinds and loc.kind not in kinds):
        what = " or ".join(kinds) if kinds else "object"
        raise OpError("op.not_found", f"no {what} with id {id_[:64]!r}")
    return loc


def taken_names(doc: Json) -> set[str]:
    """Every id and explicit variable name in use, plus the survey id."""
    names = set(build_index(doc))
    names.add(doc.get("id", ""))
    for b in doc.get("blocks", []):
        for page in b["pages"]:
            for q in page["items"]:
                if isinstance(q.get("name"), str):
                    names.add(q["name"])
    for v in doc.get("variables", []):
        if isinstance(v.get("name"), str):
            names.add(v["name"])
    return names


def fresh_id(
    doc: Json, prefix: str, *, exact_first: bool = False, also: set[str] | None = None
) -> str:
    """The first free id `prefix1`, `prefix2` ... (or `prefix` itself if `exact_first`).
    Free means not an id or name in use (or in `also`), not an expression keyword, not
    reserved. Compared case-insensitively, like data names."""
    taken = {t.lower() for t in taken_names(doc) | (also or set())}

    def free(c: str) -> bool:
        return (
            c.lower() not in taken
            and c not in KEYWORDS
            and c.lower() not in RESERVED_NAMES
            and len(c) <= 64
        )

    if exact_first and free(prefix):
        return prefix
    n = 1
    while not free(f"{prefix}{n}"):
        n += 1
    return f"{prefix}{n}"


def claim_id(ctx: Ctx, id_: str | None, prefix: str) -> str:
    """A caller-chosen id (checked: valid identifier, not in use) or a fresh one."""
    if id_ is None:
        return fresh_id(ctx.doc, prefix)
    if not IDENT.match(id_) or len(id_) > 64:
        raise OpError("op.params", f"{id_[:64]!r} is not a valid id", "/id")
    if id_ in taken_names(ctx.doc):
        raise OpError("op.duplicate_id", f"id {id_!r} is already used", "/id")
    return id_


def insert_at(lst: list[Json], index: int | None, item: Json) -> int:
    """Insert (None = append). Returns the index used. Index may equal len (append)."""
    if index is None:
        lst.append(item)
        return len(lst) - 1
    if index > len(lst):
        raise OpError("op.not_allowed", f"index {index} is past the end (length {len(lst)})")
    lst.insert(index, item)
    return index


# --- text and expression sites --------------------------------------------------------

TEXT_KEYS_QUESTION = ("label", "help", "constraintMessage")


def text_sites(doc: Json) -> Iterator[tuple[Path, Json]]:
    """Every translatable `Text` value in the survey, with its path."""
    md = doc.get("metadata", {})
    for key in ("title", "description"):
        if md.get(key) is not None:
            yield ("metadata", key), md[key]
    for i, cl in enumerate(doc.get("choiceLists", [])):
        for k, c in enumerate(cl["choices"]):
            yield ("choiceLists", i, "choices", k, "label"), c["label"]
    for i, b in enumerate(doc.get("blocks", [])):
        for j, page in enumerate(b["pages"]):
            for k, q in enumerate(page["items"]):
                qp: Path = ("blocks", i, "pages", j, "items", k)
                for key in TEXT_KEYS_QUESTION:
                    if q.get(key) is not None:
                        yield (*qp, key), q[key]
                for m, c in enumerate(q.get("choices") or []):
                    yield (*qp, "choices", m, "label"), c["label"]
    for path, n in flow_nodes(doc.get("flow", []), ("flow",)):
        if n.get("type") == "end" and n.get("message") is not None:
            yield (*path, "message"), n["message"]


def strings_of(text: Json, path: Path) -> Iterator[tuple[Path, str]]:
    """The plain strings of a `Text` (a string, or one per language)."""
    if isinstance(text, str):
        yield path, text
    elif isinstance(text, dict):
        for lang, s in text.items():
            if isinstance(s, str):
                yield (*path, lang), s


def expr_sites(doc: Json) -> Iterator[tuple[Path, bool, Json]]:
    """Every expression with its path and whether the field is required."""
    for i, b in enumerate(doc.get("blocks", [])):
        for j, page in enumerate(b["pages"]):
            for k, q in enumerate(page["items"]):
                for key in ("showIf", "constraint"):
                    if q.get(key) is not None:
                        yield ("blocks", i, "pages", j, "items", k, key), False, q[key]
    for i, v in enumerate(doc.get("variables", [])):
        if v.get("kind") == "computed":
            yield ("variables", i, "expr"), True, v["expr"]
    for i, quota in enumerate(doc.get("quotas", [])):
        yield ("quotas", i, "when"), True, quota["when"]
    for path, n in flow_nodes(doc.get("flow", []), ("flow",)):
        if n.get("type") == "branch":
            yield (*path, "if"), True, n["if"]


def expr_refs(e: Json) -> set[str]:
    """Ids referenced by an expression in its JSON form."""
    out: set[str] = set()
    stack = [e]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if cur.get("kind") == "ref" and isinstance(cur.get("id"), str):
                out.add(cur["id"])
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return out


def pipe_refs(s: str) -> set[str]:
    return {m.group(1).strip() for m in PIPE.finditer(s)}


# --- references to deleted objects ----------------------------------------------------


@dataclass(frozen=True)
class RefSite:
    """A place that refers to `target`. `kind` says how cascade repairs it:
    expr (clear the optional condition), expr_required (cannot repair), pipe (drop the
    `${id}`), choice_list (inline the list's choices), flow_block / quota_check (remove the
    flow node), on_full_block (clear `onFull.block`), assign_var (drop the variable, and
    the assign node if it becomes empty)."""

    path: Path
    kind: str
    target: str

    @property
    def pointer(self) -> str:
        return to_pointer(self.path)


def ref_sites(doc: Json, ids: set[str], exclude: Path | None = None) -> list[RefSite]:
    """Every place referring to one of `ids`, outside the subtree at `exclude` (the object
    being deleted, whose own references go with it)."""
    out = _ref_sites(doc, ids)
    if exclude is None:
        return out
    n = len(exclude)
    return [s for s in out if s.path[:n] != exclude]


def _ref_sites(doc: Json, ids: set[str]) -> list[RefSite]:
    out: list[RefSite] = []
    for path, required, e in expr_sites(doc):
        for t in sorted(expr_refs(e) & ids):
            out.append(RefSite(path, "expr_required" if required else "expr", t))
    for path, text in text_sites(doc):
        for sp, s in strings_of(text, path):
            for t in sorted(pipe_refs(s) & ids):
                out.append(RefSite(sp, "pipe", t))
    for i, b in enumerate(doc.get("blocks", [])):
        for j, page in enumerate(b["pages"]):
            for k, q in enumerate(page["items"]):
                if q.get("choiceList") in ids:
                    p: Path = ("blocks", i, "pages", j, "items", k, "choiceList")
                    out.append(RefSite(p, "choice_list", q["choiceList"]))
    for i, quota in enumerate(doc.get("quotas", [])):
        blk = quota["onFull"].get("block")
        if blk in ids:
            out.append(RefSite(("quotas", i, "onFull", "block"), "on_full_block", blk))
    for path, n in flow_nodes(doc.get("flow", []), ("flow",)):
        t = n.get("type")
        if t == "block" and n["block"] in ids:
            out.append(RefSite((*path, "block"), "flow_block", n["block"]))
        elif t == "quotaCheck" and n["quota"] in ids:
            out.append(RefSite((*path, "quota"), "quota_check", n["quota"]))
        elif t == "assign":
            for k, vid in enumerate(n["variables"]):
                if vid in ids:
                    out.append(RefSite((*path, "variables", k), "assign_var", vid))
    return out


def choice_value_sites(doc: Json, question_ids: set[str], value: Json) -> list[RefSite]:
    """Expressions that compare one of `question_ids` with the choice code `value`
    (`q == value`, `value != q`, `contains(q, value)`)."""
    out: list[RefSite] = []
    for path, required, e in expr_sites(doc):
        if _mentions_code(e, question_ids, value):
            out.append(RefSite(path, "expr_required" if required else "expr", str(value)))
    return out


def _literal_is(node: Json, value: Json) -> bool:
    if not isinstance(node, dict):
        return False
    lit = node.get("value")
    if node.get("kind") == "int":
        return type(lit) is int and type(value) is int and lit == value
    if node.get("kind") == "text":
        return isinstance(lit, str) and isinstance(value, str) and lit == value
    return False


def _is_ref_to(node: Json, ids: set[str]) -> bool:
    return isinstance(node, dict) and node.get("kind") == "ref" and node.get("id") in ids


def _mentions_code(e: Json, ids: set[str], value: Json) -> bool:
    stack = [e]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            k = cur.get("kind")
            if k == "compare":
                left, right = cur.get("left"), cur.get("right")
                if (_is_ref_to(left, ids) and _literal_is(right, value)) or (
                    _is_ref_to(right, ids) and _literal_is(left, value)
                ):
                    return True
            elif k == "contains":
                if _is_ref_to(cur.get("ref"), ids) and _literal_is(cur.get("value"), value):
                    return True
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return False


def _path_key(path: Path) -> tuple[tuple[int, int | str], ...]:
    return tuple((0, p) if isinstance(p, int) else (1, p) for p in path)


def handle_refs(
    ctx: Ctx,
    sites: list[RefSite],
    *,
    cascade: bool,
    force: bool,
    what: str,
    inline: dict[str, list[Json]] | None = None,
) -> bool:
    """Apply the dangling-reference policy to `sites` (found in `ctx.doc` after the
    delete). Returns True if cascade changed anything. Sets `ctx.check_dangling` so the
    registry's validator guard backs this walker up."""
    ctx.check_dangling = not force
    if not sites or force:
        return False
    if not cascade:
        listed = ", ".join(s.pointer for s in sites[:10])
        more = f" (+{len(sites) - 10} more)" if len(sites) > 10 else ""
        raise OpError(
            "op.dangling_ref",
            f"{what} is still referenced at {listed}{more}; "
            "fix those first, or pass cascade: true to repair them",
            sites[0].pointer,
            *[diag("op.dangling_ref", f"refers to '{s.target}'", s.pointer) for s in sites],
        )
    blocked = [s for s in sites if s.kind == "expr_required"]
    if blocked:
        raise OpError(
            "op.cascade_blocked",
            f"{what} is used by required expressions that cascade cannot clear: "
            + ", ".join(s.pointer for s in blocked[:10]),
            blocked[0].pointer,
        )
    for s in sorted(sites, key=lambda s: _path_key(s.path), reverse=True):
        _repair(ctx.doc, s, inline or {})
    ctx.touch()
    return True


def _repair(doc: Json, s: RefSite, inline: dict[str, list[Json]]) -> None:
    parent = get(doc, s.path[:-1])
    key = s.path[-1]
    if s.kind in ("expr", "on_full_block"):
        parent.pop(key, None)
    elif s.kind == "pipe":
        parent[key] = PIPE.sub(
            lambda m: "" if m.group(1).strip() == s.target else m.group(0), parent[key]
        )
    elif s.kind == "choice_list":
        parent.pop("choiceList", None)
        parent["choices"] = copy.deepcopy(inline.get(s.target, []))
    elif s.kind in ("flow_block", "quota_check"):
        _remove_node(doc, s.path[:-1])
    elif s.kind == "assign_var":
        parent.pop(key)
        if not parent:
            _remove_node(doc, s.path[:-2])


def delete_with_refs(
    ctx: Ctx,
    loc: Loc,
    ids: set[str],
    *,
    cascade: bool,
    force: bool,
    what: str,
    inline: dict[str, list[Json]] | None = None,
) -> tuple[Json, bool]:
    """Delete the object at `loc` (whose subtree holds `ids`) under the dangling-reference
    policy. References are found and repaired *before* the delete, so diagnostics point
    into the survey the user sees; repairs never touch the object's own list. Returns the
    deleted object and whether cascade changed anything."""
    sites = ref_sites(ctx.doc, ids, exclude=loc.path)
    cascaded = handle_refs(ctx, sites, cascade=cascade, force=force, what=what, inline=inline)
    obj = get(ctx.doc, loc.container).pop(loc.index)
    ctx.touch()
    return obj, cascaded


def subtree_ids(obj: Json) -> set[str]:
    """Ids of a block, page or question and everything inside it."""
    out: set[str] = set()
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if isinstance(cur.get("id"), str) and cur.get("kind") != "ref":
                out.add(cur["id"])
            stack.extend(v for k, v in cur.items() if k in ("pages", "items"))
        elif isinstance(cur, list):
            stack.extend(cur)
    return out


def _remove_node(doc: Json, node_path: Path) -> None:
    lst = get(doc, node_path[:-1])
    lst.pop(node_path[-1])


def strip_languages(doc: Json, langs: set[str]) -> int:
    """Remove translations in `langs` from every Text. Returns how many were removed."""
    n = 0
    for path, text in list(text_sites(doc)):
        if isinstance(text, dict):
            for lang in [k for k in text if k in langs]:
                del get(doc, path)[lang]
                n += 1
    return n


def translations_in(doc: Json, langs: set[str]) -> list[str]:
    """Pointers to translations in `langs`."""
    out: list[str] = []
    for path, text in text_sites(doc):
        if isinstance(text, dict):
            out.extend(to_pointer((*path, k)) for k in text if k in langs)
    return out
