"""Compose a bank-item fragment from a lab's own copy of an instrument (task QB5, the
"Add a licensed instrument privately" wizard of planning/question-bank.md §1.7, §6).

Pure (L2): the lab's item lines plus a response scale and a scoring recipe (usually a
stub's, `stubs.py`) become an `osp_spec.bank.Fragment`: one block, one page, the items
as a matrix (one shared scale) or as single-choice questions (one per item, with inline
options when each item has its own wording), a shared choice list, and the recipe as
computed variables (`<prefix>_total`, `<prefix>_<subscale>`): reversed items as
`(min + max) - item`, sums or means, an optional offset and factor (SUS: `(sum - 10) *
2.5`). Nothing here is validated beyond its own shape; the caller runs
`osp_spec.bank.check_bank_item` on the whole document, as for every bank item.

Item lines: `Item text` or, for item-specific options, `Item text | option for min | …
| option for max` (one option per scale point, in score order).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from osp_spec import Diagnostic

from .stubs import InstrumentStub

Layout = Literal["matrix", "single"]
Aggregate = Literal["sum", "mean"]

MAX_ITEMS = 200
MAX_PREFIX = 40  # leaves room for `_q123`, `_total`, `_<subscale>` within 64 chars
MAX_LINE = 2000
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_KEYWORDS = frozenset({"and", "or", "not", "null", "true", "false"})


@dataclass(frozen=True)
class ComposeRequest:
    """What the wizard sends. `items` are the pasted lines; `prefix` becomes the ids
    (`<prefix>`, `<prefix>_q1`, `<prefix>_scale`, `<prefix>_total`)."""

    prefix: str
    title: str
    items: list[str]
    layout: Layout = "matrix"
    stem: str | None = None  # the instruction above the items, if any
    scale_min: int = 0
    scale_max: int = 3
    labels: list[str] | None = None  # one per scale point; default: the values as text
    reversed: list[int] = field(default_factory=list)  # 1-based
    subscales: dict[str, list[int]] = field(default_factory=dict)
    aggregate: Aggregate | None = "sum"
    total: bool = True
    offset: int = 0
    factor: str | None = None
    language: str | None = None  # None: plain strings; else `{lang: text}` maps
    per_item: bool = False  # every line must carry its own options (a per-item stub)


def prefix_from(text: str) -> str:
    """An id prefix from an abbreviation or title: `BDI-II` -> `bdi_ii`; `10-item X` ->
    `i_10_item_x`. Empty input gives `instrument`."""
    stem = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()[:MAX_PREFIX]
    if not stem:
        return "instrument"
    if not _IDENT.match(stem):
        stem = f"i_{stem}"[:MAX_PREFIX]
    return stem


def request_from_stub(
    stub: InstrumentStub,
    items: list[str],
    *,
    layout: Layout = "matrix",
    stem: str | None = None,
    labels: list[str] | None = None,
    prefix: str | None = None,
    title: str | None = None,
    language: str | None = None,
) -> ComposeRequest:
    """A request carrying the stub's response format and scoring recipe."""
    s = stub.scoring
    return ComposeRequest(
        prefix=prefix or prefix_from(stub.abbreviation),
        title=title or stub.abbreviation,
        items=items,
        layout="single" if stub.response.kind == "per-item" else layout,
        stem=stem,
        scale_min=stub.response.min,
        scale_max=stub.response.max,
        labels=labels,
        reversed=list(s.reversed),
        subscales={k: list(v) for k, v in s.subscales.items()},
        aggregate=s.aggregate,
        total=s.total,
        offset=s.offset,
        factor=s.factor,
        language=language,
        per_item=stub.response.kind == "per-item",
    )


def _diag(code: str, pointer: str, message: str) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, pointer=pointer)


@dataclass(frozen=True)
class _Item:
    label: str
    options: list[str] | None  # item-specific wording, one per scale point


def parse_items(lines: list[str]) -> list[_Item]:
    """Non-empty lines, each `text` or `text | opt | opt …` (a `|` splits options)."""
    out: list[_Item] = []
    for raw in lines:
        if not isinstance(raw, str):
            continue
        line = " ".join(raw.split())
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        label = parts[0]
        options = [p for p in parts[1:]] if len(parts) > 1 else None
        out.append(_Item(label, options))
    return out


def _check(req: ComposeRequest, items: list[_Item]) -> list[Diagnostic]:
    d: list[Diagnostic] = []
    if (
        not isinstance(req.prefix, str)
        or not _IDENT.match(req.prefix)
        or len(req.prefix) > MAX_PREFIX
        or req.prefix in _KEYWORDS
    ):
        d.append(
            _diag(
                "bank.compose_prefix",
                "/prefix",
                f"the id prefix must be letters, digits and _ (at most {MAX_PREFIX})",
            )
        )
    if not isinstance(req.title, str) or not req.title.strip():
        d.append(_diag("bank.compose_title", "/title", "a title is needed"))
    n = len(items)
    if n == 0:
        d.append(_diag("bank.compose_items", "/items", "paste at least one item, one per line"))
    if n > MAX_ITEMS:
        d.append(_diag("bank.too_large", "/items", f"at most {MAX_ITEMS} items ({n} given)"))
    for i, it in enumerate(items):
        if len(it.label) > MAX_LINE or any(len(o) > MAX_LINE for o in it.options or []):
            d.append(_diag("bank.compose_items", f"/items/{i}", "a line is too long"))
        if not it.label:
            d.append(_diag("bank.compose_items", f"/items/{i}", "an item has no text"))
    if (
        type(req.scale_min) is not int
        or type(req.scale_max) is not int
        or req.scale_max <= req.scale_min
        or req.scale_max - req.scale_min > 20
    ):
        d.append(
            _diag(
                "bank.compose_scale", "/scale", "the scale needs min < max over at most 21 points"
            )
        )
        return d
    points = req.scale_max - req.scale_min + 1
    if req.labels is not None and len(req.labels) != points:
        d.append(
            _diag(
                "bank.compose_scale",
                "/scale/labels",
                f"{points} option labels are needed, one per scale point ({len(req.labels)} given)",
            )
        )
    per_item = [i for i, it in enumerate(items) if it.options is not None]
    if req.per_item and len(per_item) != n:
        d.append(
            _diag(
                "bank.compose_items",
                "/items",
                "each item of this instrument has its own options: write them after the item "
                f"text as `text | option | …` ({points} options)",
            )
        )
    if per_item:
        if len(per_item) != n:
            d.append(
                _diag(
                    "bank.compose_items",
                    "/items",
                    "either every item has its own options after a | or none does",
                )
            )
        for i in per_item:
            k = len(items[i].options or [])
            if k != points:
                d.append(
                    _diag(
                        "bank.compose_items",
                        f"/items/{i}",
                        f"item {i + 1} needs {points} options after the |, one per scale point "
                        f"({k} given)",
                    )
                )
        if req.layout == "matrix":
            d.append(
                _diag(
                    "bank.compose_layout",
                    "/layout",
                    "items with their own options can't share a grid: use one question per item",
                )
            )
    sets = [("/scoring/reversed", list(req.reversed))] + [
        (f"/scoring/subscales/{name}", list(v)) for name, v in req.subscales.items()
    ]
    for ptr, idx in sets:
        bad = [i for i in idx if type(i) is not int or not 1 <= i <= max(n, 1)]
        if bad:
            d.append(_diag("bank.compose_scoring", ptr, f"item numbers {bad} are outside 1-{n}"))
        if len(set(idx)) != len(idx):
            d.append(_diag("bank.compose_scoring", ptr, "an item number repeats"))
    for name, idx in req.subscales.items():
        if not idx:
            d.append(
                _diag("bank.compose_scoring", f"/scoring/subscales/{name}", "the subscale is empty")
            )
        if not _IDENT.match(_var_suffix(name)) or len(req.prefix) + 1 + len(_var_suffix(name)) > 64:
            d.append(
                _diag("bank.compose_scoring", f"/scoring/subscales/{name}", "not a usable name")
            )
    if req.factor is not None:
        try:
            f = Decimal(req.factor)
            if not f.is_finite():
                raise InvalidOperation
        except InvalidOperation, ValueError, TypeError:
            d.append(_diag("bank.compose_scoring", "/scoring/factor", "factor must be a number"))
    if type(req.offset) is not int:
        d.append(_diag("bank.compose_scoring", "/scoring/offset", "offset must be a whole number"))
    if req.aggregate not in ("sum", "mean", None):
        d.append(_diag("bank.compose_scoring", "/scoring/aggregate", "sum, mean or none"))
    return d


def _var_suffix(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower() or "score"


def _text(req: ComposeRequest, s: str) -> Any:
    return {req.language: s} if req.language else s


def _ref(req: ComposeRequest, i: int) -> dict[str, Any]:
    return {"kind": "ref", "id": f"{req.prefix}_q{i}"}


def _item_expr(req: ComposeRequest, i: int) -> dict[str, Any]:
    ref = _ref(req, i)
    if i in req.reversed:
        return {
            "kind": "arith",
            "op": "-",
            "left": {"kind": "int", "value": req.scale_min + req.scale_max},
            "right": ref,
        }
    return ref


def _sum(terms: list[dict[str, Any]]) -> dict[str, Any]:
    out = terms[0]
    for t in terms[1:]:
        out = {"kind": "arith", "op": "+", "left": out, "right": t}
    return out


def _recipe(req: ComposeRequest, indices: list[int]) -> dict[str, Any]:
    expr = _sum([_item_expr(req, i) for i in indices])
    if req.aggregate == "mean":
        expr = {
            "kind": "arith",
            "op": "/",
            "left": expr,
            "right": {"kind": "int", "value": len(indices)},
        }
    if req.offset:
        expr = {
            "kind": "arith",
            "op": "+",
            "left": expr,
            "right": {"kind": "int", "value": req.offset},
        }
    if req.factor is not None:
        f = Decimal(req.factor)
        lit: dict[str, Any] = (
            {"kind": "int", "value": int(f)}
            if f == f.to_integral_value()
            else {"kind": "decimal", "value": str(f)}
        )
        expr = {"kind": "arith", "op": "*", "left": expr, "right": lit}
    return expr


def compose_fragment(req: ComposeRequest) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    """The fragment for `req`, or `(None, diagnostics)`. Never raises."""
    try:
        items = parse_items(list(req.items) if isinstance(req.items, list) else [])
        problems = _check(req, items)
        if problems:
            return None, problems
        p = req.prefix
        n = len(items)
        values = list(range(req.scale_min, req.scale_max + 1))
        labels = req.labels if req.labels is not None else [str(v) for v in values]
        per_item = items[0].options is not None
        choice_lists: list[dict[str, Any]] = []
        questions: list[dict[str, Any]] = []
        if req.stem and req.layout == "single":
            questions.append({"id": f"{p}_stem", "type": "note", "label": _text(req, req.stem)})
        if req.layout == "matrix" and not per_item:
            choice_lists.append(
                {
                    "id": f"{p}_scale",
                    "choices": [
                        {"value": v, "label": _text(req, lab)}
                        for v, lab in zip(values, labels, strict=True)
                    ],
                }
            )
            questions.append(
                {
                    "id": p,
                    "type": "matrix",
                    "label": _text(req, req.stem or req.title),
                    "choiceList": f"{p}_scale",
                    "rows": [
                        {"id": f"q{i}", "label": _text(req, it.label)}
                        for i, it in enumerate(items, 1)
                    ],
                }
            )
        else:
            if not per_item:
                choice_lists.append(
                    {
                        "id": f"{p}_scale",
                        "choices": [
                            {"value": v, "label": _text(req, lab)}
                            for v, lab in zip(values, labels, strict=True)
                        ],
                    }
                )
            for i, it in enumerate(items, 1):
                q: dict[str, Any] = {
                    "id": f"{p}_q{i}",
                    "type": "single",
                    "label": _text(req, it.label),
                }
                if it.options is not None:
                    q["choices"] = [
                        {"value": v, "label": _text(req, lab)}
                        for v, lab in zip(values, it.options, strict=True)
                    ]
                else:
                    q["choiceList"] = f"{p}_scale"
                questions.append(q)
        variables: list[dict[str, Any]] = []
        if req.aggregate is not None:
            if req.total:
                variables.append(
                    {
                        "id": f"{p}_total",
                        "kind": "computed",
                        "expr": _recipe(req, list(range(1, n + 1))),
                    }
                )
            for name, idx in req.subscales.items():
                variables.append(
                    {
                        "id": f"{p}_{_var_suffix(name)}",
                        "kind": "computed",
                        "expr": _recipe(req, idx),
                    }
                )
        fragment = {
            "choiceLists": choice_lists,
            "variables": variables,
            "block": {
                "id": f"{p}_block",
                "title": req.title,
                "pages": [{"id": f"{p}_page", "items": questions}],
            },
        }
        return fragment, []
    except Exception as exc:  # pragma: no cover - the safety net (golden rule 3)
        return None, [_diag("bank.compose_failed", "", f"could not compose: {exc!r}"[:200])]


__all__ = [
    "MAX_ITEMS",
    "ComposeRequest",
    "compose_fragment",
    "parse_items",
    "prefix_from",
    "request_from_stub",
]
