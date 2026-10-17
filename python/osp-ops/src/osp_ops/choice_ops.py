"""Choice ops: add, delete, move, set, bulk paste.

`owner` is a choice list id, or the id of a single/multi question with inline `choices`.
A choice's identity is its `value` (the code stored in data, semantics.md §2).
"""

from __future__ import annotations

import copy
import re
from typing import Any, Literal

from pydantic import Field

from .doc import (
    CHOICE_LIST,
    QUESTION,
    RefSite,
    choice_value_sites,
    get,
    handle_refs,
    insert_at,
    locate,
)
from .patch import same, to_pointer
from .registry import REVERSE_PATCH, Ctx, Invocation, OpError, Params, op

type ChoiceValue = int | str
type Text = str | dict[str, str]
Index = Field(default=None, ge=0)
MAX_PASTE = 100_000  # characters


def owner_choices(ctx: Ctx, owner: str) -> tuple[list[dict[str, Any]], set[str], str]:
    """The owner's choice list (mutable), the question ids whose answers use it, and a
    pointer to it."""
    loc = locate(ctx, owner, QUESTION, CHOICE_LIST)
    obj = get(ctx.doc, loc.path)
    if loc.kind == CHOICE_LIST:
        users = {
            q["id"]
            for b in ctx.doc.get("blocks", [])
            for page in b["pages"]
            for q in page["items"]
            if q.get("choiceList") == owner
        }
        return obj["choices"], users, to_pointer((*loc.path, "choices"))
    if obj.get("type") not in ("single", "multi", "matrix"):
        raise OpError("op.not_allowed", f"question '{owner}' has no choices", loc.pointer)
    if obj.get("choices") is None:
        shared = obj.get("choiceList")
        raise OpError(
            "op.not_allowed",
            f"question '{owner}' uses the shared list '{shared}'; edit that list instead",
            loc.pointer,
        )
    return obj["choices"], {owner}, to_pointer((*loc.path, "choices"))


def find_choice(choices: list[dict[str, Any]], value: ChoiceValue, ptr: str) -> int:
    for i, c in enumerate(choices):
        if same(c["value"], value):
            return i
    raise OpError("op.not_found", f"no choice with code {value!r}", ptr)


def next_code(choices: list[dict[str, Any]]) -> int:
    ints = [c["value"] for c in choices if type(c["value"]) is int]
    return max(ints, default=0) + 1


def default_label(ctx: Ctx, label: str) -> Text:
    """A plain label for single-language surveys, else one in the default language."""
    md = ctx.doc.get("metadata", {})
    langs = md.get("languages") or []
    if len(langs) <= 1:
        return label
    return {md.get("defaultLanguage") or langs[0]: label}


def _value_refs(ctx: Ctx, users: set[str], value: ChoiceValue) -> list[RefSite]:
    return choice_value_sites(ctx.doc, users, value) if users else []


# --- add / delete ---------------------------------------------------------------------


class AddChoice(Params):
    owner: str
    label: Text = ""
    value: ChoiceValue | None = None  # None: the next integer code
    index: int | None = Index
    media: dict[str, Any] | None = None  # planning/media.md: an image or audio clip


@op("add_choice", AddChoice, label="Add choice", area="choices")
def add_choice(ctx: Ctx, p: AddChoice) -> Invocation:
    """Add a choice (default: the next integer code, at the end), optionally with its
    media (an image or audio clip, `osp_spec.media.Media`)."""
    choices, _, ptr = owner_choices(ctx, p.owner)
    value = next_code(choices) if p.value is None else p.value
    if any(same(c["value"], value) for c in choices):
        raise OpError("op.not_allowed", f"code {value!r} is already used", ptr)
    choice: dict[str, Any] = {"value": value, "label": copy.deepcopy(p.label)}
    if p.media is not None:
        choice["media"] = copy.deepcopy(p.media)
    insert_at(choices, p.index, choice)
    return Invocation(op="delete_choice", params={"owner": p.owner, "value": value, "force": True})


class DeleteChoice(Params):
    owner: str
    value: ChoiceValue
    cascade: bool = False
    force: bool = False


@op("delete_choice", DeleteChoice, label="Delete choice", area="choices")
def delete_choice(ctx: Ctx, p: DeleteChoice) -> Invocation:
    """Delete a choice. Rejected while a condition compares an answer with its code
    (`q == code`, `contains(q, code)`), unless `cascade` (clears those optional
    conditions) or `force`. A list's last choice cannot be deleted."""
    choices, users, ptr = owner_choices(ctx, p.owner)
    i = find_choice(choices, p.value, ptr)
    if len(choices) == 1:
        raise OpError("op.not_allowed", "a choice list needs at least one choice", ptr)
    c = choices.pop(i)
    cascaded = handle_refs(
        ctx,
        _value_refs(ctx, users, p.value),
        cascade=p.cascade,
        force=p.force,
        what=f"code {p.value!r}",
    )
    if cascaded:
        return REVERSE_PATCH
    params: dict[str, Any] = {
        "owner": p.owner,
        "label": c["label"],
        "value": c["value"],
        "index": i,
    }
    if c.get("media") is not None:
        params["media"] = c["media"]
    return Invocation(op="add_choice", params=params)


# --- move / set -----------------------------------------------------------------------


class MoveChoice(Params):
    owner: str
    value: ChoiceValue
    index: int = Field(ge=0)


@op("move_choice", MoveChoice, label="Move choice", area="choices")
def move_choice(ctx: Ctx, p: MoveChoice) -> Invocation:
    """Move a choice to `index` (counted after removing it)."""
    choices, _, ptr = owner_choices(ctx, p.owner)
    i = find_choice(choices, p.value, ptr)
    c = choices.pop(i)
    insert_at(choices, p.index, c)
    return Invocation(op="move_choice", params={"owner": p.owner, "value": p.value, "index": i})


class SetChoice(Params):
    owner: str
    value: ChoiceValue
    new_value: ChoiceValue | None = None  # None: keep the code
    label: Text | None = None  # None: keep the label
    force: bool = False


@op("set_choice", SetChoice, label="Edit choice", area="choices")
def set_choice(ctx: Ctx, p: SetChoice) -> Invocation:
    """Change a choice's label and/or code. Changing a code that conditions compare with
    is rejected unless `force` (the conditions would silently stop matching)."""
    choices, users, ptr = owner_choices(ctx, p.owner)
    i = find_choice(choices, p.value, ptr)
    c = choices[i]
    old = copy.deepcopy(c)
    inverse: dict[str, Any] = {"owner": p.owner, "value": p.value, "force": True}
    if p.new_value is not None and not same(p.new_value, p.value):
        if any(same(o["value"], p.new_value) for o in choices):
            raise OpError("op.not_allowed", f"code {p.new_value!r} is already used", ptr)
        sites = _value_refs(ctx, users, p.value)
        if sites and not p.force:
            raise OpError(
                "op.dangling_ref",
                f"conditions compare with code {p.value!r} at "
                + ", ".join(s.pointer for s in sites[:10])
                + "; update them first, or pass force: true",
                sites[0].pointer,
            )
        c["value"] = p.new_value
        inverse = {**inverse, "value": p.new_value, "new_value": old["value"]}
    if p.label is not None:
        c["label"] = copy.deepcopy(p.label)
        inverse["label"] = old["label"]
    return Invocation(op="set_choice", params=inverse)


# --- bulk paste -----------------------------------------------------------------------

_CODED = re.compile(r"^\s*([^\t]+?)\s*\t\s*(.*?)\s*$")
_INT = re.compile(r"^-?[0-9]{1,15}$")


def parse_paste(text: str, start: int) -> list[tuple[ChoiceValue, str]]:
    """One choice per non-blank line. `code<TAB>label` sets the code (an integer if it
    looks like one); a bare label gets the next integer code, counting from `start`."""
    out: list[tuple[ChoiceValue, str]] = []
    n = start
    for line in text.splitlines():
        if not line.strip():
            continue
        m = _CODED.match(line)
        if m:
            code: ChoiceValue = int(m.group(1)) if _INT.match(m.group(1)) else m.group(1)
            out.append((code, m.group(2)))
            if type(code) is int:
                n = max(n, code + 1)
        else:
            out.append((n, line.strip()))
            n += 1
    return out


class BulkPasteChoices(Params):
    owner: str
    text: str = Field(max_length=MAX_PASTE)
    mode: Literal["replace", "append"] = "replace"
    force: bool = False


@op("bulk_paste_choices", BulkPasteChoices, label="Paste choices", area="choices")
def bulk_paste_choices(ctx: Ctx, p: BulkPasteChoices) -> Invocation:
    """Paste one choice per line (`label`, or `code<TAB>label`). `replace` numbers bare
    labels 1, 2, 3 ...; `append` continues after the highest integer code. Removing a
    code that conditions compare with is rejected unless `force`."""
    choices, users, ptr = owner_choices(ctx, p.owner)
    old = copy.deepcopy(choices)
    start = 1 if p.mode == "replace" else next_code(choices)
    pasted = parse_paste(p.text, start)
    if not pasted:
        raise OpError("op.not_allowed", "nothing to paste: every line is blank", ptr)
    new = [{"value": v, "label": default_label(ctx, label)} for v, label in pasted]
    result = new if p.mode == "replace" else [*choices, *new]
    seen: list[ChoiceValue] = []
    for c in result:
        if any(same(c["value"], s) for s in seen):
            raise OpError("op.not_allowed", f"code {c['value']!r} appears twice", ptr)
        seen.append(c["value"])
    if p.mode == "replace" and not p.force:
        for c in old:
            if not any(same(c["value"], s) for s in seen):
                sites = _value_refs(ctx, users, c["value"])
                if sites:
                    raise OpError(
                        "op.dangling_ref",
                        f"code {c['value']!r} would be removed but conditions compare with it "
                        f"at {sites[0].pointer}; keep it, or pass force: true",
                        sites[0].pointer,
                    )
    choices[:] = result
    return Invocation(
        op="set_property", params={"target": p.owner, "property": "choices", "value": old}
    )
