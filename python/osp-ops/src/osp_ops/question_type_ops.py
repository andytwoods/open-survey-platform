"""`change_question_type`: turn a question into another type, in place.

What a question *is* stays: its id, variable name, label, help, `showIf` (and every
translation of its texts). What depends on the type is converted where it means the same
thing, else dropped, else filled with the new type's defaults:

- single <-> multi keep their choices (inline or a shared list) and choice order;
  single/multi -> matrix keep them as the columns and get default rows; matrix ->
  single/multi keep the columns and drop the rows.
- Any other type -> single/multi/matrix gets the default choices (and rows).
- A choice question -> anything without choices drops them.
- integer <-> decimal keep `min`/`max` (a decimal bound that is not a whole number is
  dropped going to integer); integer/decimal -> slider carry both bounds when they make a
  usable track (min < max, a whole number of steps), else the slider's 0-100; slider ->
  integer/decimal keep the track ends as bounds. A slider's step and end labels, a text
  question's `multiline` and anything else the new type lacks are dropped.
- `required` stays wherever the new type has it; `constraint` (and its message) stays
  only between number types (integer, decimal, slider), the only case where a test of the
  answer still means the same. A note keeps only its texts and `showIf`.

Changing the type can break what other parts of the survey say about this answer: a
condition `q == 1` once `q` is text, `contains(q, 2)` once `q` is single, a pipe or a
condition naming a note or a matrix, a matrix row id that no longer exists. Those are
found by validating the survey before and after: any new type, reference or choice-code
problem means the change is rejected (`op.type_conflict`, one diagnostic per place)
unless `force` (the problems then stay in the draft for the researcher to fix).

The inverse puts the previous question back exactly: `change_question_type` with the
full old object as `question` (and `force`, since it restores a survey that was valid).
"""

from __future__ import annotations

import copy
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any

from osp_spec import validate
from pydantic import JsonValue

from .doc import QUESTION, expr_sites, get, locate, strings_of, text_sites
from .patch import to_pointer
from .property_ops import QUESTION_CLASSES, model_fields
from .question_ops import DEFAULT_CHOICES, DEFAULT_ROWS, QuestionType
from .registry import Ctx, Invocation, OpError, Params, diag, op

CHOICE_TYPES = frozenset({"single", "multi"})
WITH_COLUMNS = frozenset({"single", "multi", "matrix"})
NUMBER_TYPES = frozenset({"integer", "decimal", "slider"})
# Kept from the old question whenever the new type has the field.
IDENTITY_KEYS = ("help", "showIf", "name", "required", "media")
# New validator problems that mean "something that referred to this answer broke".
BREAKING_CODES = frozenset(
    {"expr.type", "ref.no_value", "ref.unknown", "ref.unknown_choice_code", "pipe.invalid"}
)
SLIDER_DEFAULT = (0, 100)


def _num(v: Any) -> Decimal | None:
    if isinstance(v, bool) or not isinstance(v, (int, str)):
        return None
    try:
        return Decimal(v)
    except InvalidOperation:
        return None


def _as_int(v: Any) -> int | None:
    """`v` as an integer bound, if it is a whole number."""
    if type(v) is int:
        return v
    d = _num(v)
    if d is None or d != d.to_integral_value() or abs(d) > 2**53 - 1:
        return None
    return int(d)


def convert(old: dict[str, Any], new_type: str) -> dict[str, Any]:
    """The question `old` as a `new_type` question (see the module docstring)."""
    old_type = old.get("type")
    fields = set(model_fields(QUESTION_CLASSES[new_type]))
    q: dict[str, Any] = {"id": old["id"], "type": new_type, "label": copy.deepcopy(old["label"])}
    for key in IDENTITY_KEYS:
        if key in old and key in fields:
            q[key] = copy.deepcopy(old[key])
    if old_type in NUMBER_TYPES and new_type in NUMBER_TYPES:
        for key in ("constraint", "constraintMessage"):
            if key in old:
                q[key] = copy.deepcopy(old[key])

    # Choices (columns for a matrix).
    if new_type in WITH_COLUMNS:
        if old_type in WITH_COLUMNS:
            for key in ("choiceList", "choices"):
                if key in old:
                    q[key] = copy.deepcopy(old[key])
            if new_type in CHOICE_TYPES and old_type in CHOICE_TYPES and "choiceOrder" in old:
                q["choiceOrder"] = old["choiceOrder"]
        if "choiceList" not in q and "choices" not in q:
            q["choices"] = copy.deepcopy(DEFAULT_CHOICES)
    if new_type == "matrix":
        q["rows"] = copy.deepcopy(old["rows"] if old_type == "matrix" else DEFAULT_ROWS)

    # Numbers.
    if new_type == "integer" and old_type in NUMBER_TYPES:
        for key in ("min", "max"):
            v = _as_int(old.get(key))
            if v is not None:
                q[key] = v
    elif new_type == "decimal" and old_type in NUMBER_TYPES:
        for key in ("min", "max"):
            if key in old and _num(old[key]) is not None:
                q[key] = old[key]
    elif new_type == "slider":
        q.update(_slider_track(old))
    return q


def _slider_track(old: dict[str, Any]) -> dict[str, Any]:
    if old.get("type") not in ("integer", "decimal"):
        return {}
    value_type = "decimal" if old["type"] == "decimal" else "integer"
    lo, hi = _num(old.get("min")), _num(old.get("max"))
    track: dict[str, Any] = {"valueType": value_type}
    usable = (
        lo is not None
        and hi is not None
        and lo < hi
        and (hi - lo) % 1 == 0
        and (value_type == "decimal" or (lo % 1 == 0 and hi % 1 == 0))
    )
    if usable:
        track["min"], track["max"] = old["min"], old["max"]
    else:
        track["min"], track["max"] = SLIDER_DEFAULT
    return track


def _breaking(before: list[Any], after: list[Any]) -> list[Any]:
    seen = Counter((d.code, d.pointer, d.message) for d in before if d.code in BREAKING_CODES)
    out = []
    for d in after:
        if d.code not in BREAKING_CODES:
            continue
        key = (d.code, d.pointer, d.message)
        if seen[key] > 0:
            seen[key] -= 1
        else:
            out.append(d)
    return out


def _site_of(pointer: str, sites: list[str]) -> str:
    """The condition or text a diagnostic points into (type errors point at a part)."""
    inside = [s for s in sites if pointer == s or pointer.startswith(s + "/")]
    return max(inside, key=len, default=pointer)


def _sites(doc: Any) -> list[str]:
    out = [to_pointer(path) for path, _, _ in expr_sites(doc)]
    for path, text in text_sites(doc):
        out.extend(to_pointer(sp) for sp, _ in strings_of(text, path))
    return out


class ChangeQuestionType(Params):
    id: str
    type: QuestionType
    force: bool = False
    # The exact question to put in its place (used by undo): its id and type must match.
    question: dict[str, JsonValue] | None = None


@op("change_question_type", ChangeQuestionType, label="Change question type", area="questions")
def change_question_type(ctx: Ctx, p: ChangeQuestionType) -> Invocation:
    """Change a question's type in place, keeping its id, variable name, texts (with their
    translations) and `showIf`, converting what carries over (choices between single,
    multi and matrix; bounds between number types) and dropping the rest. Rejected
    (`op.type_conflict`) when conditions or piping elsewhere would stop making sense for
    the new type, unless `force`. With `question`, puts that exact object in its place."""
    loc = locate(ctx, p.id, QUESTION)
    old = get(ctx.doc, loc.path)
    if p.question is not None:
        new = copy.deepcopy(dict(p.question))
        if new.get("id") != p.id or new.get("type") != p.type:
            raise OpError(
                "op.params", "question must have the same id and the given type", "/question"
            )
    elif old.get("type") == p.type:
        raise OpError("op.not_allowed", f"'{p.id}' is already a {p.type} question", loc.pointer)
    else:
        new = convert(old, p.type)

    previous = copy.deepcopy(old)
    container = get(ctx.doc, loc.container)
    container[loc.index] = new
    ctx.touch()
    ctx.check_dangling = not p.force

    if not p.force:
        broken = _breaking(validate(ctx.before), validate(ctx.doc))
        if broken:
            # One diagnostic per condition or text (a type error points into a part of it).
            sites = _sites(ctx.doc)
            by_site: dict[str, list[str]] = {}
            for d in broken:
                by_site.setdefault(_site_of(d.pointer, sites), []).append(d.message)
            places = sorted(by_site)
            n = len(places)
            raise OpError(
                "op.type_conflict",
                f"changing '{p.id}' to {p.type} would break {n} "
                f"{'reference' if n == 1 else 'references'} to its answer "
                f"(conditions or piping): {', '.join(places[:10])}"
                f"{f' (+{n - 10} more)' if n > 10 else ''}; "
                "fix them first, or pass force: true",
                loc.pointer,
                *[diag("op.type_conflict", "; ".join(by_site[s]), s) for s in places],
            )
    return Invocation(
        op="change_question_type",
        params={"id": p.id, "type": previous["type"], "question": previous, "force": True},
    )
