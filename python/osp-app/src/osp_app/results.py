"""Results viewer aggregation (task V1, ``planning/results-viewer.md``).

All of the V-D5 semantics live here, so the API, CLI and tests share one definition:

- Units are **responses**, never participants.
- Response states stay separate (``answered``, ``unanswered``, ``irrelevant``,
  ``notReached``, ``notInVersion``; plus ``unrecorded``: the stored record has no state
  for the variable, and ``invalid``: answered with a value that does not fit it). The
  denominator is ``answered`` (default) or ``shown`` = answered + unanswered; nothing
  else is ever in it.
- Multiple choice: % = responses that chose the option / the denominator, so the options
  can sum to more than 100 %. An unticked option inside an answered question is "no";
  an unanswered question is missing.
- Choice codes are categories, never measurements: no mean of codes. Declared order is
  kept. Ordered scales (numeric codes in ascending declared order) also get the median
  category and, with at least 4 categories, top-2 / bottom-2 box.
- Versions: one by default (the latest). Several are combined per card when the card's
  variables have the same type and choice codes in every version that has them (matched
  by ids, never by label text); otherwise the card is split into per-version facets with
  a ``versions.incompatible`` warning. A response of a version without the question is
  ``notInVersion``, outside every denominator.
- Languages: aggregates are by ids; labels are in the chosen language (default the
  survey's main language). Free text is never translated.
- Matrix: each row is its own variable with its own states and n.
- Splits: one categorical question (single choice or matrix row) or one assigned
  condition. Every group shares the category order and the numeric bin edges / date
  periods; a missing split value is its own group (``_missing``) unless excluded; each
  group has its own n. No weighting.
- Undefined statistics (SD with n < 2, anything with n = 0) are ``None`` and listed in
  ``notAvailable``, never 0.

Answers are encrypted at rest: each request streams and decrypts every response of the
versions once (``ParticipantStore.stream_responses``) and computes every requested card
in that pass. Results are cached in memory per (tenant, survey, versions, response
watermark, normalised query); a new or deleted response changes the watermark.

Access: ``survey.export`` (owner, editor) only. Every call writes a ``results.read``
audit entry with the actor, the normalised query and the versions, never answer values.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import threading
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from osp_spec import MatrixQuestion, NoteQuestion
from osp_store import ParticipantStore, TenantContext, Version
from osp_targets.data import ExportError, StoredResponse, SurveyVersion
from osp_targets.data.layout import Layout, QuestionInfo, build_layout
from osp_targets.data.view import ResponseView

from .auth.permissions import Action, Actor
from .builder import Builder
from .commands import command
from .errors import InvalidRequest, NotFoundError, Rejected

STATES = (
    "answered",
    "unanswered",
    "irrelevant",
    "notReached",
    "notInVersion",
    "unrecorded",
    "invalid",
)
_ANSWERED, _UNANSWERED, _IRRELEVANT, _NOT_REACHED, _NOT_IN, _UNRECORDED, _INVALID = range(7)
_STATE_INDEX = {"answered": 0, "unanswered": 1, "irrelevant": 2, "not-reached": 3}
MISSING = "_missing"
ALL = "all"
MAX_BINS = 200
MAX_PERIODS = 1000
SLIDER_VALUE_STEPS = 21
CACHE_SIZE = 32
Z95 = 1.959963984540054
# t(0.975, df) for df = 1..30; larger df use a Cornish-Fisher expansion (error < 1e-5).
_T975 = (
    12.706205, 4.302653, 3.182446, 2.776445, 2.570582, 2.446912, 2.364624, 2.306004,
    2.262157, 2.228139, 2.200985, 2.178813, 2.160369, 2.144787, 2.131450, 2.119905,
    2.109816, 2.100922, 2.093024, 2.085963, 2.079614, 2.073873, 2.068658, 2.063899,
    2.059539, 2.055529, 2.051831, 2.048407, 2.045230, 2.042272,
)  # fmt: skip
UNITS = ("day", "week", "month", "year")
CARD_TYPES = ("single", "multi", "integer", "decimal", "slider", "date", "text")


# -- statistics -------------------------------------------------------------------------


def t975(df: int) -> float:
    """The 97.5 % quantile of Student's t with ``df`` degrees of freedom."""
    if df < 1:
        raise ValueError("df must be >= 1")
    if df <= len(_T975):
        return _T975[df - 1]
    z = Z95
    g1 = (z**3 + z) / 4
    g2 = (5 * z**5 + 16 * z**3 + 3 * z) / 96
    g3 = (3 * z**7 + 19 * z**5 + 17 * z**3 - 15 * z) / 384
    return z + g1 / df + g2 / df**2 + g3 / df**3


def wilson(k: int, n: int) -> list[float] | None:
    """Wilson 95 % interval of k / n, in percent; None when n is 0."""
    if n <= 0:
        return None
    p = k / n
    z2 = Z95 * Z95
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = Z95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return [max(0.0, centre - half) * 100, min(1.0, centre + half) * 100]


def quantile(sorted_values: Sequence[float], p: float) -> float | None:
    """Linear interpolation between order statistics (Hyndman-Fan type 7, the default
    in R and NumPy)."""
    n = len(sorted_values)
    if n == 0:
        return None
    h = (n - 1) * p
    lo = math.floor(h)
    hi = min(lo + 1, n - 1)
    return sorted_values[lo] + (h - lo) * (sorted_values[hi] - sorted_values[lo])


def _pct(count: int, n: int) -> float | None:
    return 100 * count / n if n > 0 else None


def _num_text(d: Decimal) -> str:
    """A number as short text: 3, 2.5, -0.25 (no exponent, no trailing zeros)."""
    if d == d.to_integral_value():
        return str(d.quantize(Decimal(1)))
    return format(d.normalize(), "f")


def _float_text(x: float) -> str:
    return _num_text(Decimal(repr(x)))


# -- the query ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Bins:
    width: float | None = None
    count: int | None = None
    unit: str | None = None


@dataclass(frozen=True)
class Query:
    versions: tuple[int, ...] | None = None
    status: str = "complete"
    submitted_from: datetime | None = None
    submitted_to: datetime | None = None
    filters: tuple[tuple[str, frozenset[str]], ...] = ()
    condition: tuple[str, frozenset[str]] | None = None
    split_question: str | None = None
    split_condition: str | None = None
    exclude_missing: bool = False
    denominator: str = "answered"
    intervals: bool = False
    cards: tuple[tuple[str, Bins], ...] | None = None
    language: str | None = None

    def normalised(self, versions: Sequence[int]) -> dict[str, Any]:
        """JSON form with versions resolved: what the hash, the cache and the audit use."""
        return {
            "versions": list(versions),
            "status": self.status,
            "submittedFrom": _iso(self.submitted_from),
            "submittedTo": _iso(self.submitted_to),
            "filters": [{"question": q, "in": sorted(codes)} for q, codes in self.filters],
            "condition": (
                {"variable": self.condition[0], "in": sorted(self.condition[1])}
                if self.condition
                else None
            ),
            "split": (
                {
                    "question": self.split_question,
                    "condition": self.split_condition,
                    "excludeMissing": self.exclude_missing,
                }
                if self.split_question or self.split_condition
                else None
            ),
            "denominator": self.denominator,
            "intervals": self.intervals,
            "cards": (
                None
                if self.cards is None
                else [{"question": q, "bins": [b.width, b.count, b.unit]} for q, b in self.cards]
            ),
            "language": self.language,
        }


def _iso(d: datetime | None) -> str | None:
    return None if d is None else d.astimezone(UTC).isoformat()


def _str(value: Any, what: str, limit: int = 200) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= limit:
        raise InvalidRequest(f"{what} must be a non-empty string of at most {limit} characters")
    return value


def _codes(value: Any, what: str) -> frozenset[str]:
    if not isinstance(value, list | tuple) or not 0 < len(value) <= 500:
        raise InvalidRequest(f"{what} must be a list of 1-500 codes")
    out = set()
    for c in value:
        if isinstance(c, bool) or not isinstance(c, int | str):
            raise InvalidRequest(f"{what}: codes are integers or strings")
        out.add(str(c))
    return frozenset(out)


def _when(value: Any, what: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        d = value
    elif isinstance(value, str):
        try:
            d = datetime.fromisoformat(value)
        except ValueError as exc:
            raise InvalidRequest(f"{what} must be an ISO 8601 date-time") from exc
    else:
        raise InvalidRequest(f"{what} must be an ISO 8601 date-time")
    return d if d.tzinfo is not None else d.replace(tzinfo=UTC)


def _bins(value: Any) -> Bins:
    if value is None:
        return Bins()
    if not isinstance(value, Mapping):
        raise InvalidRequest("bins must be an object")
    width, count, unit = value.get("width"), value.get("count"), value.get("unit")
    if width is not None and (
        isinstance(width, bool)
        or not isinstance(width, int | float)
        or not math.isfinite(width)
        or width <= 0
    ):
        raise InvalidRequest("bins.width must be a positive number")
    if count is not None and (
        isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_BINS
    ):
        raise InvalidRequest(f"bins.count must be an integer from 1 to {MAX_BINS}")
    if unit is not None and unit not in UNITS:
        raise InvalidRequest("bins.unit must be day, week, month or year")
    return Bins(float(width) if width is not None else None, count, unit)


def parse_query(raw: Any) -> Query:
    """A query from its JSON form (the API's ``ResultsQuery``). Bad input is an
    ``InvalidRequest``, never an exception from deeper down (AGENTS.md rule 3)."""
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise InvalidRequest("query must be an object")
    versions = raw.get("versions")
    if versions is not None:
        if (
            not isinstance(versions, list | tuple)
            or not 0 < len(versions) <= 50
            or any(isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in versions)
        ):
            raise InvalidRequest("versions must be a list of 1-50 positive integers")
        versions = tuple(sorted(set(versions)))
    status = raw.get("status") or "complete"
    if status not in ("complete", "all"):
        raise InvalidRequest("status must be complete or all")
    denominator = raw.get("denominator") or "answered"
    if denominator not in ("answered", "shown"):
        raise InvalidRequest("denominator must be answered or shown")
    filters_raw = raw.get("filters") or []
    if not isinstance(filters_raw, list | tuple) or len(filters_raw) > 20:
        raise InvalidRequest("filters must be a list of at most 20 filters")
    merged: dict[str, frozenset[str]] = {}
    for f in filters_raw:
        if not isinstance(f, Mapping):
            raise InvalidRequest("each filter must be an object")
        qid = _str(f.get("question"), "filters[].question")
        codes = _codes(f.get("in"), "filters[].in")
        merged[qid] = merged[qid] & codes if qid in merged else codes  # AND of filters
    condition = None
    cond = raw.get("condition")
    if cond is not None:
        if not isinstance(cond, Mapping):
            raise InvalidRequest("condition must be an object")
        condition = (
            _str(cond.get("variable"), "condition.variable"),
            _codes(cond.get("in"), "condition.in"),
        )
    split_q = split_c = None
    exclude = False
    split = raw.get("split")
    if split is not None:
        if not isinstance(split, Mapping):
            raise InvalidRequest("split must be an object")
        split_q, split_c = split.get("question"), split.get("condition")
        if (split_q is None) == (split_c is None):
            raise InvalidRequest("split needs exactly one of question or condition")
        split_q = _str(split_q, "split.question") if split_q is not None else None
        split_c = _str(split_c, "split.condition") if split_c is not None else None
        exclude = split.get("excludeMissing") is True
    cards = None
    cards_raw = raw.get("cards")
    if cards_raw is not None:
        if not isinstance(cards_raw, list | tuple) or len(cards_raw) > 500:
            raise InvalidRequest("cards must be a list of at most 500 cards")
        out: list[tuple[str, Bins]] = []
        for c in cards_raw:
            if not isinstance(c, Mapping):
                raise InvalidRequest("each card must be an object")
            out.append((_str(c.get("question"), "cards[].question"), _bins(c.get("bins"))))
        cards = tuple(out)
    language = raw.get("language")
    if language is not None:
        language = _str(language, "language", 35)
    return Query(
        versions=versions,
        status=status,
        submitted_from=_when(raw.get("submittedFrom"), "submittedFrom"),
        submitted_to=_when(raw.get("submittedTo"), "submittedTo"),
        filters=tuple(sorted(merged.items())),
        condition=condition,
        split_question=split_q,
        split_condition=split_c,
        exclude_missing=exclude,
        denominator=denominator,
        intervals=raw.get("intervals") is True,
        cards=cards,
        language=language,
    )


def parse_code_filter(text: Any, what: str) -> tuple[str, frozenset[str]]:
    """``<id>:<code>[,<code>...]`` (the text endpoint's query-string filters)."""
    if not isinstance(text, str) or ":" not in text or len(text) > 2000:
        raise InvalidRequest(f"{what} must look like <id>:<code>[,<code>...]")
    qid, _, codes = text.partition(":")
    parts = [c for c in codes.split(",") if c != ""]
    return _str(qid, what), _codes(parts, what)


# -- versions and cards -----------------------------------------------------------------


@dataclass
class VersionInfo:
    version: Version
    layout: Layout
    vars: dict[str, QuestionInfo]  # variable id (incl. matrix rows) -> info
    matrices: dict[str, list[QuestionInfo]]  # matrix id -> its rows in order
    matrix_items: dict[str, MatrixQuestion]
    notes: dict[str, NoteQuestion]
    order: list[str]  # card ids (questions, matrices, notes) in survey order

    @property
    def number(self) -> int:
        return self.version.number


def version_info(v: Version) -> VersionInfo:
    try:
        lay = build_layout(SurveyVersion(v.body, number=v.number, checksum=v.checksum))
    except ExportError as exc:
        raise Rejected(str(exc), exc.diagnostics) from exc
    info = VersionInfo(v, lay, {}, {}, {}, {}, [])
    items = {q.id: q for b in lay.survey.blocks for p in b.pages for q in p.items}
    for q in lay.questions:
        info.vars[q.id] = q
        card = q.matrix or q.id
        if q.matrix:
            info.matrices.setdefault(q.matrix, []).append(q)
            item = items.get(q.matrix)
            if isinstance(item, MatrixQuestion):
                info.matrix_items[q.matrix] = item
        if card not in info.order:
            info.order.append(card)
    for b in lay.survey.blocks:
        for p in b.pages:
            for q in p.items:
                if isinstance(q, NoteQuestion):
                    info.notes[q.id] = q
    return info


def _definition(q: QuestionInfo) -> tuple[str, tuple[str, ...] | None]:
    """What makes a variable's data comparable across versions: its type and choice codes
    (as osp_targets.data.layout does for combined exports, M2-3)."""
    codes = None if q.choices is None else tuple(sorted(str(c.code) for c in q.choices))
    kind = f"slider:{q.scale['valueType']}" if q.scale else q.type
    return kind, codes


def _ordered(codes: Sequence[Any]) -> bool:
    """An ordered scale: every code an integer, ascending in declared order."""
    if len(codes) < 2 or any(isinstance(c, bool) or not isinstance(c, int) for c in codes):
        return False
    return all(a < b for a, b in zip(codes, codes[1:], strict=False))


def _text(value: Mapping[str, str] | None, lang: str, fallback: str) -> str:
    if not value:
        return ""
    return value.get(lang) or value.get(fallback) or next(iter(value.values()), "")


@dataclass
class VarPlan:
    """One variable of a card in one version (a question, or one matrix row)."""

    id: str
    info: QuestionInfo


@dataclass
class Unit:
    """A body of results: the combined versions of a card, or one version's facet."""

    versions: tuple[int, ...]
    var_ids: list[str]  # variable ids in order (matrix rows; else one)
    accs: dict[tuple[str, str], Acc] = field(default_factory=dict)  # (var, group) -> acc
    responses: dict[str, int] = field(default_factory=dict)  # group -> responses

    def acc(self, var: str, group: str) -> Acc:
        a = self.accs.get((var, group))
        if a is None:
            a = self.accs[(var, group)] = Acc()
        return a


@dataclass
class CardPlan:
    question: str
    type: str  # single | multi | integer | decimal | slider | date | text | matrix | note
    bins: Bins
    present: dict[int, VersionInfo]  # versions that contain the question
    ref: VersionInfo  # the newest version that contains it (labels, order)
    compatible: bool
    why: str | None
    units: list[Unit]
    slider_values: list[Decimal] | None = None  # slider frequency bars (<= 21 steps)

    def vars_in(self, vi: VersionInfo) -> list[str]:
        if self.type == "matrix":
            return [q.id for q in vi.matrices.get(self.question, [])]
        return [self.question] if self.question in vi.vars else []

    def unit_for(self, number: int) -> Unit | None:
        for u in self.units:
            if number in u.versions:
                return u
        return None


def _card_type(question: str, vi: VersionInfo) -> str | None:
    if question in vi.matrices:
        return "matrix"
    if question in vi.notes:
        return "note"
    q = vi.vars.get(question)
    if q is None or q.matrix:  # a matrix row is reached through its matrix's card
        return None
    return q.type if q.type in CARD_TYPES else None


def plan_card(question: str, bins: Bins, versions: Sequence[VersionInfo]) -> CardPlan | None:
    present = {vi.number: vi for vi in versions if _card_type(question, vi) is not None}
    if not present:
        return None
    ref = present[max(present)]
    kind = _card_type(question, ref) or "note"
    defs: dict[int, Any] = {}
    for n, vi in present.items():
        t = _card_type(question, vi)
        if t == "matrix":
            defs[n] = (
                "matrix",
                tuple((q.id, _definition(q)) for q in vi.matrices[question]),
            )
        elif t == "note":
            defs[n] = ("note",)
        else:
            defs[n] = _definition(vi.vars[question])
    compatible = len(set(defs.values())) == 1
    why = None
    if not compatible:
        kinds = {n: d[0] for n, d in defs.items()}
        if len(set(kinds.values())) > 1:
            why = (
                "its type differs between versions ("
                + ", ".join(f"v{n}: {k}" for n, k in sorted(kinds.items()))
                + ")"
            )
        elif kind == "matrix":
            why = "its rows or columns (ids / codes) differ between versions"
        else:
            why = "its choice codes differ between versions"
    plan = CardPlan(question, kind, bins, present, ref, compatible, why, [])
    # Every version used is in a unit (absent versions give notInVersion counts).
    if compatible:
        plan.units = [Unit(tuple(vi.number for vi in versions), plan.vars_in(ref))]
    else:
        plan.units = [
            Unit((vi.number,), plan.vars_in(vi)) for vi in versions if vi.number in present
        ]
        absent = tuple(vi.number for vi in versions if vi.number not in present)
        if absent:  # responses of versions without the question: notInVersion only
            plan.units.append(Unit(absent, []))
    if kind == "slider":
        scales = {
            (str(s["min"]), str(s["max"]), str(s["step"]))
            for vi in present.values()
            if (s := vi.vars[question].scale)
        }
        if len(scales) == 1:
            lo, hi, step = (Decimal(x) for x in scales.pop())
            if step > 0 and hi >= lo:
                steps = (hi - lo) / step
                if steps == steps.to_integral_value() and steps + 1 <= SLIDER_VALUE_STEPS:
                    plan.slider_values = [lo + k * step for k in range(int(steps) + 1)]
    return plan


# -- accumulation ------------------------------------------------------------------------


class Acc:
    """Running counts of one variable in one group."""

    __slots__ = ("chosen", "counts", "states", "text_chars", "values")

    def __init__(self) -> None:
        self.states = [0] * 7
        self.counts: dict[str, int] = {}
        self.values: list[Any] = []  # Decimal (numbers) or date
        self.chosen = 0  # multi: options chosen in total
        self.text_chars = 0


def _number(value: Any, integer: bool) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        d = Decimal(value) if not isinstance(value, float) else Decimal(repr(value))
    except InvalidOperation, ValueError:
        return None
    if not d.is_finite():
        return None
    if integer and d != d.to_integral_value():
        return None
    return d


def _date(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _add(acc: Acc, q: QuestionInfo, kind: str, state: str | None, value: Any, plan: Any) -> None:
    """Count one response's answer to one variable (V-D5)."""
    idx = _STATE_INDEX.get(state) if state is not None else None
    if idx is None:
        acc.states[_UNRECORDED] += 1
        return
    if idx != _ANSWERED:
        acc.states[idx] += 1
        return
    ok = True
    if kind == "single":
        key = str(value) if isinstance(value, int | str) and not isinstance(value, bool) else None
        if key is not None and key in plan:
            acc.counts[key] = acc.counts.get(key, 0) + 1
        else:
            ok = False
    elif kind == "multi":
        if isinstance(value, list) and all(
            isinstance(v, int | str) and not isinstance(v, bool) for v in value
        ):
            keys = {str(v) for v in value}
            if keys <= plan:
                for k in keys:
                    acc.counts[k] = acc.counts.get(k, 0) + 1
                acc.chosen += len(keys)
            else:
                ok = False
        else:
            ok = False
    elif kind in ("integer", "decimal", "slider"):
        integer = kind == "integer" or (
            kind == "slider" and q.scale is not None and q.scale.get("valueType") == "integer"
        )
        d = _number(value, integer)
        if d is None or (plan is not None and d not in plan):
            ok = False
        else:
            acc.values.append(d)
    elif kind == "date":
        d = _date(value)
        if d is None:
            ok = False
        else:
            acc.values.append(d)
    elif kind == "text":
        if isinstance(value, str):
            acc.text_chars += len(value)
        else:
            ok = False
    acc.states[_ANSWERED if ok else _INVALID] += 1


# -- binning -----------------------------------------------------------------------------


def _nice(raw: float) -> float:
    """The smallest 1, 2 or 5 x 10^k that is >= raw."""
    if raw <= 0:
        return 1.0
    exp = math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        w = m * 10**exp
        if w >= raw * (1 - 1e-12):
            return float(w)
    return float(10 ** (exp + 1))


def numeric_edges(values: Sequence[float], bins: Bins, integer: bool) -> tuple[list[float], bool]:
    """Shared bin edges for every group: (edges, coarsened). Bins are [lo, hi); the last
    bin also takes a value equal to its upper edge. Default: width 1 for whole numbers
    spanning at most 20, else a 1/2/5 x 10^k width giving about 10 bins."""
    if not values:
        return [], False
    lo_v, hi_v = min(values), max(values)
    span = hi_v - lo_v
    coarsened = False
    if bins.count is not None and bins.width is None:
        width = span / bins.count if span > 0 else 1.0
        edges = [lo_v + i * width for i in range(bins.count + 1)]
        if span == 0:
            edges = [lo_v, lo_v + 1.0]
        return edges, False
    if bins.width is not None:
        width = bins.width
    elif integer and span <= 20:
        width = 1.0
    else:
        width = _nice(span / 10) if span > 0 else 1.0
    if span / width + 1 > MAX_BINS:
        width = _nice(span / (MAX_BINS - 1))
        coarsened = True
    start = math.floor(lo_v / width) * width
    n = int(math.floor((hi_v - start) / width + 1e-9)) + 1
    return [start + i * width for i in range(n + 1)], coarsened


def _bin_index(x: float, edges: Sequence[float]) -> int:
    lo, width_n = edges[0], len(edges) - 1
    width = (edges[-1] - lo) / width_n
    i = int(math.floor((x - lo) / width + 1e-9)) if width > 0 else 0
    return min(max(i, 0), width_n - 1)


def _period(d: date, unit: str) -> str:
    if unit == "day":
        return d.isoformat()
    if unit == "week":
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    if unit == "month":
        return f"{d.year:04d}-{d.month:02d}"
    return f"{d.year:04d}"


def _period_count(a: date, b: date, unit: str) -> int:
    if unit == "day":
        return (b - a).days + 1
    if unit == "week":
        return ((b - timedelta(days=b.weekday())) - (a - timedelta(days=a.weekday()))).days // 7 + 1
    if unit == "month":
        return (b.year - a.year) * 12 + b.month - a.month + 1
    return b.year - a.year + 1


def periods(a: date, b: date, unit: str) -> list[str]:
    """Every period from a to b inclusive (empty ones too, so axes are continuous)."""
    out: list[str] = []
    if unit == "day":
        return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]
    if unit == "week":
        d = a - timedelta(days=a.weekday())
        while d <= b:
            out.append(_period(d, "week"))
            d += timedelta(days=7)
        return out
    if unit == "month":
        y, m = a.year, a.month
        while (y, m) <= (b.year, b.month):
            out.append(f"{y:04d}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out
    return [f"{y:04d}" for y in range(a.year, b.year + 1)]


# -- building the output ----------------------------------------------------------------


def _states(accs: Iterable[Acc]) -> dict[str, int]:
    total = [0] * 7
    for a in accs:
        for i, v in enumerate(a.states):
            total[i] += v
    return dict(zip(STATES, total, strict=True))


def _denominator(acc: Acc, mode: str) -> int:
    return acc.states[_ANSWERED] + (acc.states[_UNANSWERED] if mode == "shown" else 0)


def _numeric_stats(values: list[float], n: int, intervals: bool) -> dict[str, Any]:
    s = sorted(values)
    k = len(s)
    out: dict[str, Any] = {"n": n}
    na: list[str] = []
    for name in ("mean", "median", "q1", "q3", "min", "max"):
        out[name] = None
    if k:
        mean = math.fsum(s) / k
        out.update(
            mean=mean,
            median=quantile(s, 0.5),
            q1=quantile(s, 0.25),
            q3=quantile(s, 0.75),
            min=s[0],
            max=s[-1],
        )
    else:
        na += ["mean", "median", "q1", "q3", "min", "max"]
    if k >= 2:
        mean = out["mean"]
        sd = math.sqrt(math.fsum((x - mean) ** 2 for x in s) / (k - 1))
        out["sd"] = sd
        if intervals:
            half = t975(k - 1) * sd / math.sqrt(k)
            out["meanCi"] = [mean - half, mean + half]
    else:
        out["sd"] = None
        na.append("sd")
        if intervals:
            out["meanCi"] = None
            na.append("meanCi")
    out["notAvailable"] = na
    return out


def _choice_stats(
    acc: Acc, keys: Sequence[str], n: int, ordered: bool, kind: str
) -> dict[str, Any]:
    out: dict[str, Any] = {"n": n, "notAvailable": []}
    answered = acc.states[_ANSWERED]
    if kind == "multi":
        out["meanOptions"] = acc.chosen / answered if answered else None
        if not answered:
            out["notAvailable"].append("meanOptions")
        return out
    counts = [acc.counts.get(k, 0) for k in keys]
    top = max(counts, default=0)
    out["mode"] = [k for k, c in zip(keys, counts, strict=True) if c == top] if top else None
    if not top:
        out["notAvailable"].append("mode")
    if ordered:
        if answered:
            target = (answered + 1) // 2  # the lower median: the ceil(n/2)-th answer
            cum = 0
            for k, c in zip(keys, counts, strict=True):
                cum += c
                if cum >= target:
                    out["median"] = k
                    break
        else:
            out["median"] = None
            out["notAvailable"].append("median")
        if len(keys) >= 4:
            if n:
                out["top2"] = 100 * (counts[-1] + counts[-2]) / n
                out["bottom2"] = 100 * (counts[0] + counts[1]) / n
            else:
                out["top2"] = out["bottom2"] = None
                out["notAvailable"] += ["top2", "bottom2"]
    return out


@dataclass
class Ctx:
    query: Query
    lang: str
    groups: list[tuple[str, str, bool]]  # (key, label, missing)
    warnings: list[dict[str, Any]]


def _cell(key: str, label: str, count: int, n: int, intervals: bool, **extra: Any) -> dict:
    c = {"key": key, "label": label, "count": count, "pct": _pct(count, n), **extra}
    if intervals:
        c["ci"] = wilson(count, n)
    return c


def _unit_data(
    plan: CardPlan, unit: Unit, vi: VersionInfo, cx: Ctx, card_warnings: list[dict]
) -> dict[str, Any]:
    """CardData for one unit (combined versions or one facet). ``vi``: the version whose
    definition and labels the unit shows."""
    q, lang, fb = cx.query, cx.lang, vi.layout.default_language
    kind = plan.type
    data: dict[str, Any] = {
        "states": None,
        "groups": [],
        "rows": None,
        "categories": None,
        "binning": None,
        "binEdges": None,
        "binUnit": None,
    }
    if kind == "note":
        return data
    var_ids = unit.var_ids or plan.vars_in(vi)
    infos = [vi.vars[v] for v in var_ids if v in vi.vars]
    first = infos[0] if infos else None

    def group_list(var: str, cells_for: Any, stats_for: Any) -> list[dict]:
        out = []
        for key, label, missing in cx.groups:
            acc = unit.accs.get((var, key)) or Acc()
            n = _denominator(acc, q.denominator)
            out.append(
                {
                    "key": key,
                    "label": label,
                    "missing": missing,
                    "responses": unit.responses.get(key, 0),
                    "n": n,
                    "states": _states([acc]),
                    "cells": cells_for(acc, n),
                    "stats": stats_for(acc, n),
                }
            )
        return out

    def var_accs(var: str) -> list[Acc]:
        return [a for (v, _g), a in unit.accs.items() if v == var]

    if kind in ("single", "multi", "matrix"):
        choices = (first.choices or []) if first else []
        keys = [str(c.code) for c in choices]
        labels = [_text(c.label, lang, fb) for c in choices]
        ordered = kind != "multi" and _ordered([c.code for c in choices])
        data["categories"] = [
            {"key": k, "code": c.code, "label": lbl}
            for k, c, lbl in zip(keys, choices, labels, strict=True)
        ]
        data["binning"] = "categories"

        def cells(acc: Acc, n: int) -> list[dict]:
            return [
                _cell(k, lbl, acc.counts.get(k, 0), n, q.intervals)
                for k, lbl in zip(keys, labels, strict=True)
            ]

        def stats(acc: Acc, n: int) -> dict:
            return _choice_stats(acc, keys, n, ordered, "multi" if kind == "multi" else "single")

        if kind == "matrix":
            data["rows"] = [
                {
                    "id": r.id,
                    "name": r.name,
                    "label": _text(r.label, lang, fb),
                    "states": _states(var_accs(r.id)),
                    "groups": group_list(r.id, cells, stats),
                }
                for r in infos
            ]
        else:
            data["states"] = _states(var_accs(plan.question))
            data["groups"] = group_list(plan.question, cells, stats)
        return data

    var = plan.question
    data["states"] = _states(var_accs(var))
    if kind in ("integer", "decimal", "slider"):
        if plan.slider_values is not None:
            data["binning"] = "values"
            vkeys = [_num_text(v) for v in plan.slider_values]

            def cells(acc: Acc, n: int) -> list[dict]:
                counts: dict[str, int] = {}
                for v in acc.values:
                    k = _num_text(v)
                    counts[k] = counts.get(k, 0) + 1
                return [
                    _cell(k, k, counts.get(k, 0), n, q.intervals, lo=float(v), hi=float(v))
                    for k, v in zip(vkeys, plan.slider_values or [], strict=True)
                ]
        else:
            data["binning"] = "bins"
            allv = [float(v) for a in var_accs(var) for v in a.values]
            integer = kind == "integer" or bool(
                first and first.scale and first.scale.get("valueType") == "integer"
            )
            edges, coarsened = numeric_edges(allv, plan.bins, integer)
            if coarsened:
                card_warnings.append(
                    {
                        "code": "bins.coarsened",
                        "message": f"More than {MAX_BINS} bins: the bin width was widened.",
                        "question": plan.question,
                    }
                )
            data["binEdges"] = edges
            whole = (
                integer
                and all(float(e).is_integer() for e in edges)
                and (len(edges) < 2 or edges[1] - edges[0] == 1)
            )

            def cells(acc: Acc, n: int) -> list[dict]:
                if len(edges) < 2:
                    return []
                counts = [0] * (len(edges) - 1)
                for v in acc.values:
                    counts[_bin_index(float(v), edges)] += 1
                out = []
                for i, c in enumerate(counts):
                    lo, hi = edges[i], edges[i + 1]
                    label = _float_text(lo) if whole else f"{_float_text(lo)}–{_float_text(hi)}"
                    out.append(_cell(str(i), label, c, n, q.intervals, lo=lo, hi=hi))
                return out

        def stats(acc: Acc, n: int) -> dict:
            return _numeric_stats([float(v) for v in acc.values], n, q.intervals)

        data["groups"] = group_list(var, cells, stats)
        return data

    if kind == "date":
        data["binning"] = "periods"
        alld = [v for a in var_accs(var) for v in a.values]
        unit_name = plan.bins.unit or "month"
        keys: list[str] = []
        if alld:
            a, b = min(alld), max(alld)
            while _period_count(a, b, unit_name) > MAX_PERIODS and unit_name != "year":
                unit_name = UNITS[UNITS.index(unit_name) + 1]
                card_warnings.append(
                    {
                        "code": "bins.coarsened",
                        "message": f"More than {MAX_PERIODS} periods: counted per {unit_name}.",
                        "question": plan.question,
                    }
                )
            keys = periods(a, b, unit_name)
        data["binUnit"] = unit_name

        def cells(acc: Acc, n: int) -> list[dict]:
            counts: dict[str, int] = {}
            for d in acc.values:
                k = _period(d, unit_name)
                counts[k] = counts.get(k, 0) + 1
            return [_cell(k, k, counts.get(k, 0), n, q.intervals) for k in keys]

        def stats(acc: Acc, n: int) -> dict:
            if not acc.values:
                return {
                    "n": n,
                    "earliest": None,
                    "latest": None,
                    "notAvailable": ["earliest", "latest"],
                }
            return {
                "n": n,
                "earliest": min(acc.values).isoformat(),
                "latest": max(acc.values).isoformat(),
                "notAvailable": [],
            }

        data["groups"] = group_list(var, cells, stats)
        return data

    # text: counts only; the verbatim answers come from the text endpoint
    def stats(acc: Acc, n: int) -> dict:
        answered = acc.states[_ANSWERED]
        if not answered:
            return {"n": n, "meanLength": None, "notAvailable": ["meanLength"]}
        return {"n": n, "meanLength": acc.text_chars / answered, "notAvailable": []}

    data["groups"] = group_list(var, lambda _a, _n: [], stats)
    return data


def build_card(plan: CardPlan, cx: Ctx) -> dict[str, Any]:
    ref, lang = plan.ref, cx.lang
    fb = ref.layout.default_language
    warnings: list[dict[str, Any]] = []
    if plan.type == "matrix":
        item = ref.matrix_items.get(plan.question)
        name = (item.name or item.id) if item else plan.question
        label = _text(ref.matrices[plan.question][0].matrix_label, lang, fb)
        choices = ref.matrices[plan.question][0].choices or []
    elif plan.type == "note":
        name = plan.question
        label = _text(ref.layout.text(ref.notes[plan.question].label), lang, fb)
        choices = []
    else:
        info = ref.vars[plan.question]
        name, label, choices = info.name, _text(info.label, lang, fb), info.choices or []
    card: dict[str, Any] = {
        "question": plan.question,
        "name": name,
        "type": plan.type,
        "label": label,
        "ordered": (
            _ordered([c.code for c in choices]) if plan.type in ("single", "matrix") else None
        ),
        "versionsUsed": sorted(plan.present),
        "facets": None,
        "warnings": warnings,
    }
    if plan.compatible:
        card.update(_unit_data(plan, plan.units[0], ref, cx, warnings))
        return card
    warnings.append(
        {
            "code": "versions.incompatible",
            "message": f"Shown per version: {plan.why}. Versions are combined only when "
            "the question and its option codes match.",
            "question": plan.question,
        }
    )
    facets = []
    for unit in plan.units:
        if not unit.var_ids and unit.versions[0] not in plan.present:
            continue  # versions without the question: counted in the states below
        vi = plan.present[unit.versions[0]]
        facets.append({"version": vi.number, **_unit_data(plan, unit, vi, cx, warnings)})
    empty = {
        "states": None,
        "groups": [],
        "rows": None,
        "categories": None,
        "binning": None,
        "binEdges": None,
        "binUnit": None,
    }
    card.update(empty)
    if plan.type not in ("matrix", "note"):
        total = dict.fromkeys(STATES, 0)
        for f in facets:
            for k, v in (f["states"] or {}).items():
                total[k] += v
        for unit in plan.units:
            if unit.versions[0] not in plan.present:
                total["notInVersion"] += sum(unit.responses.values())
        card["states"] = total
    card["facets"] = facets
    return card


# -- the scan ----------------------------------------------------------------------------


@dataclass
class SplitPlan:
    question: str | None
    condition: str | None
    keys: dict[str, str]  # code -> label, declared order
    label: str
    exclude_missing: bool

    def groups(self) -> list[tuple[str, str, bool]]:
        out = [(k, lbl, False) for k, lbl in self.keys.items()]
        if not self.exclude_missing:
            out.append((MISSING, "No answer" if self.question else "No condition", True))
        return out

    def key(self, view: ResponseView) -> str:
        if self.question is not None:
            state, value = view.answer(self.question)
            k = str(value) if state == "answered" and isinstance(value, int | str) else None
        else:
            v = view.condition(self.condition or "")
            k = str(v) if isinstance(v, int | str) and not isinstance(v, bool) else None
        return k if k is not None and k in self.keys else MISSING


def plan_split(q: Query, versions: Sequence[VersionInfo], lang: str) -> SplitPlan | None:
    if q.split_question is not None:
        present = [vi for vi in versions if q.split_question in vi.vars]
        if not present:
            raise InvalidRequest(f"split question {q.split_question!r} not found")
        defs = {_definition(vi.vars[q.split_question]) for vi in present}
        info = present[-1].vars[q.split_question]
        if info.type != "single":
            raise InvalidRequest("split question must be single choice or a matrix row")
        if len(defs) > 1:
            raise InvalidRequest("split question's choice codes differ between versions")
        fb = present[-1].layout.default_language
        keys = {str(c.code): _text(c.label, lang, fb) for c in info.choices or []}
        label = _text(info.label, lang, fb)
        if info.matrix:
            label = f"{_text(info.matrix_label, lang, fb)}: {label}"
        return SplitPlan(q.split_question, None, keys, label, q.exclude_missing)
    if q.split_condition is not None:
        keys: dict[str, str] = {}
        found = False
        for vi in reversed(versions):
            for v in vi.layout.assigned:
                if v.id == q.split_condition:
                    found = True
                    for level in v.levels or []:
                        keys.setdefault(str(level), str(level))
        if not found:
            raise InvalidRequest(f"split condition {q.split_condition!r} not found")
        return SplitPlan(None, q.split_condition, keys, q.split_condition, q.exclude_missing)
    return None


def _check_filters(q: Query, versions: Sequence[VersionInfo]) -> None:
    for qid, _ in q.filters:
        infos = [vi.vars[qid] for vi in versions if qid in vi.vars]
        if not infos:
            raise InvalidRequest(f"filter question {qid!r} not found")
        if any(i.type not in ("single", "multi") for i in infos):
            raise InvalidRequest(f"filter question {qid!r} must be single or multiple choice")
    if q.condition is not None and not any(
        v.id == q.condition[0] for vi in versions for v in vi.layout.assigned
    ):
        raise InvalidRequest(f"condition variable {q.condition[0]!r} not found")


def _keep(view: ResponseView, resp: Any, has_record: bool, q: Query) -> bool:
    if q.status == "complete" and has_record and view.meta("_end") != "complete":
        return False
    at = resp.submitted_at
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    if q.submitted_from is not None and (at is None or at < q.submitted_from):
        return False
    if q.submitted_to is not None and (at is None or at >= q.submitted_to):
        return False
    if q.condition is not None:
        v = view.condition(q.condition[0])
        if isinstance(v, bool) or not isinstance(v, int | str) or str(v) not in q.condition[1]:
            return False
    for qid, codes in q.filters:
        state, value = view.answer(qid)
        if state != "answered":
            return False
        chosen = value if isinstance(value, list) else [value]
        if not any(str(c) in codes for c in chosen if isinstance(c, int | str)):
            return False
    return True


@dataclass
class TextCollect:
    question: str
    items: list[tuple[Any, str, int, str | None, str]] = field(default_factory=list)
    acc: Acc = field(default_factory=Acc)


@dataclass
class ScanResult:
    responses: int
    split_counts: dict[str, int]


def scan(
    builder: Builder,
    ctx: TenantContext,
    versions: Sequence[VersionInfo],
    q: Query,
    plans: Sequence[CardPlan],
    split: SplitPlan | None,
    text: TextCollect | None = None,
) -> ScanResult:
    """The single pass: stream and decrypt each response once, filter it, and count it
    into every card."""
    participants = ParticipantStore(builder.store)
    total = 0
    split_counts: dict[str, int] = {}
    # Per card, what this version needs: (unit, [(var id, info or None, kind, allowed)])
    for vi in versions:
        work = []
        for plan in plans:
            if plan.type == "note":
                continue
            unit = plan.unit_for(vi.number)
            if unit is None:
                continue
            pairs = []
            for vid in unit.var_ids:
                info = vi.vars.get(vid)
                kind = plan.type if plan.type != "matrix" else "single"
                if info is None:
                    pairs.append((vid, None, kind, None))
                    continue
                if kind in ("single", "multi"):
                    allowed: Any = frozenset(str(c.code) for c in info.choices or [])
                elif kind == "slider" and plan.slider_values is not None:
                    allowed = frozenset(plan.slider_values)
                else:
                    allowed = None
                pairs.append((vid, info, kind, allowed))
            work.append((unit, pairs))
        text_info = vi.vars.get(text.question) if text is not None else None
        for resp, full in participants.stream_responses(ctx, vi.version.id, "results"):
            full = full if isinstance(full, Mapping) else None
            record = full.get("record") if full else None
            record = record if isinstance(record, Mapping) else None
            view = ResponseView(
                StoredResponse(
                    response_id=resp.id,
                    record=record,
                    answers=resp.answers,
                    assigned=resp.assigned_conditions,
                    submitted_at=resp.submitted_at,
                ),
                vi.layout,
                None,
            )
            if not _keep(view, resp, record is not None, q):
                continue
            g = split.key(view) if split is not None else ALL
            if g == MISSING and split is not None and split.exclude_missing:
                continue
            total += 1
            split_counts[g] = split_counts.get(g, 0) + 1
            for unit, pairs in work:
                unit.responses[g] = unit.responses.get(g, 0) + 1
                for vid, info, kind, allowed in pairs:
                    acc = unit.acc(vid, g)
                    if info is None:
                        acc.states[_NOT_IN] += 1
                        continue
                    state, value = view.answer(vid)
                    _add(acc, info, kind, state, value, allowed)
            if text is not None:
                if text_info is None:
                    text.acc.states[_NOT_IN] += 1
                else:
                    state, value = view.answer(text.question)
                    _add(text.acc, text_info, "text", state, value, None)
                    if state == "answered" and isinstance(value, str):
                        text.items.append(
                            (resp.submitted_at, resp.id, vi.number, view.meta("_language"), value)
                        )
    return ScanResult(total, split_counts)


# -- cache ------------------------------------------------------------------------------


class ResultsCache:
    """A small LRU of computed results. Keys carry the response watermark, so a new or
    deleted response misses; ``put`` also drops older watermarks of the same survey."""

    def __init__(self, size: int = CACHE_SIZE) -> None:
        self.size = size
        self._d: OrderedDict[tuple, Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple) -> Any:
        with self._lock:
            value = self._d.get(key)
            if value is not None:
                self._d.move_to_end(key)
            return value

    def put(self, key: tuple, value: Any) -> None:
        tenant, survey, _versions, watermark = key[:4]
        with self._lock:
            for k in [k for k in self._d if k[:2] == (tenant, survey) and k[3] != watermark]:
                del self._d[k]
            self._d[key] = value
            self._d.move_to_end(key)
            while len(self._d) > self.size:
                self._d.popitem(last=False)

    def __len__(self) -> int:
        return len(self._d)


_CACHES_LOCK = threading.Lock()


def cache_for(builder: Builder) -> ResultsCache:
    cache = getattr(builder, "_results_cache", None)
    if cache is None:
        with _CACHES_LOCK:
            cache = getattr(builder, "_results_cache", None)
            if cache is None:
                cache = ResultsCache()
                builder._results_cache = cache  # type: ignore[attr-defined]
    return cache


# -- loading ----------------------------------------------------------------------------


@dataclass
class Loaded:
    ctx: TenantContext
    versions: list[VersionInfo]
    watermark: str


_LAYOUTS: OrderedDict[tuple[str, str], VersionInfo] = OrderedDict()


def _version_info_cached(v: Version) -> VersionInfo:
    """Published versions never change, so their parsed layout is kept (bounded)."""
    key = (v.id, v.checksum)
    with _CACHES_LOCK:
        hit = _LAYOUTS.get(key)
    if hit is not None:
        return hit
    info = version_info(v)
    with _CACHES_LOCK:
        _LAYOUTS[key] = info
        while len(_LAYOUTS) > 256:
            _LAYOUTS.popitem(last=False)
    return info


def load(builder: Builder, actor: Actor, survey_id: object, numbers: Any) -> Loaded:
    ctx = builder._locate(actor, survey_id, Action.SURVEY_EXPORT)
    published = builder.store.list_versions(ctx, str(survey_id))
    if not published:
        raise NotFoundError("Nothing published yet.")
    if numbers is None:
        chosen = [max(published, key=lambda v: v.number)]
    else:
        by = {v.number: v for v in published}
        missing = [n for n in numbers if n not in by]
        if missing:
            raise NotFoundError(f"No such published version: {missing[0]}.")
        chosen = [by[n] for n in sorted(numbers)]
    participants = ParticipantStore(builder.store)
    marks = [(v.number, *participants.response_watermark(ctx, v.id)) for v in chosen]
    watermark = hashlib.sha256(json.dumps(marks).encode()).hexdigest()[:16]
    return Loaded(ctx, [_version_info_cached(v) for v in chosen], watermark)


def _language(q: Query, versions: Sequence[VersionInfo], warnings: list[dict]) -> str:
    newest = versions[-1].layout
    if q.language is None:
        return newest.default_language
    if q.language not in newest.languages:
        warnings.append(
            {
                "code": "language.unknown",
                "message": f"The survey has no language {q.language!r}; labels are in "
                f"{newest.default_language!r}.",
                "question": None,
            }
        )
        return newest.default_language
    return q.language


def _default_cards(versions: Sequence[VersionInfo]) -> list[str]:
    """Every question (not notes) of the newest version in survey order, then any that
    only older versions have."""
    out: list[str] = []
    for vi in reversed(versions):
        for card in vi.order:
            if card not in out:
                out.append(card)
    return out


def _now() -> datetime:
    return datetime.now(UTC)


# -- commands ---------------------------------------------------------------------------


@command("survey.results_query", label="Query results", action=Action.SURVEY_EXPORT)
def results_query(
    builder: Builder, actor: Actor, *, survey_id: str, query: Any = None
) -> dict[str, Any]:
    q = parse_query(query)
    loaded = load(builder, actor, survey_id, q.versions)
    versions = loaded.versions
    numbers = [vi.number for vi in versions]
    norm = q.normalised(numbers)
    query_hash = hashlib.sha256(
        json.dumps(norm, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    key = (loaded.ctx.tenant_id, survey_id, tuple(numbers), loaded.watermark, query_hash)
    cache = cache_for(builder)
    result = cache.get(key)
    cached = result is not None
    if result is None:
        result = _compute(builder, loaded, q, survey_id, query_hash)
        cache.put(key, result)
    builder.store.audit(
        loaded.ctx,
        "results.read",
        "survey",
        survey_id,
        {"query": norm, "versions": numbers, "queryHash": query_hash, "cached": cached},
    )
    return {**result, "cached": cached}


def _compute(
    builder: Builder, loaded: Loaded, q: Query, survey_id: str, query_hash: str
) -> dict[str, Any]:
    versions = loaded.versions
    warnings: list[dict[str, Any]] = []
    lang = _language(q, versions, warnings)
    _check_filters(q, versions)
    split = plan_split(q, versions, lang)
    requested = (
        list(q.cards) if q.cards is not None else [(c, Bins()) for c in _default_cards(versions)]
    )
    plans: list[CardPlan] = []
    for question, bins in requested:
        plan = plan_card(question, bins, versions)
        if plan is None:
            warnings.append(
                {
                    "code": "question.not_found",
                    "message": f"No question {question!r} in the versions used.",
                    "question": question,
                }
            )
            continue
        plans.append(plan)
    res = scan(builder, loaded.ctx, versions, q, plans, split)
    groups = split.groups() if split is not None else [(ALL, "All responses", False)]
    cx = Ctx(q, lang, groups, warnings)
    return {
        "surveyId": survey_id,
        "queryHash": query_hash,
        "watermark": loaded.watermark,
        "generatedAt": _now(),
        "versionsUsed": [vi.number for vi in versions],
        "language": lang,
        "languages": list(versions[-1].layout.languages),
        "denominator": q.denominator,
        "responses": res.responses,
        "split": (
            {
                "question": split.question,
                "condition": split.condition,
                "label": split.label,
                "groups": [
                    {"key": k, "label": lbl, "missing": m, "responses": res.split_counts.get(k, 0)}
                    for k, lbl, m in groups
                ],
            }
            if split is not None
            else None
        ),
        "cards": [build_card(p, cx) for p in plans],
        "warnings": warnings,
    }


def _cursor_offset(cursor: Any) -> int:
    if cursor is None or cursor == "":
        return 0
    try:
        raw = base64.urlsafe_b64decode(str(cursor).encode() + b"==").decode()
        offset = int(raw.removeprefix("o:")) if raw.startswith("o:") else -1
    except ValueError, UnicodeDecodeError:
        offset = -1
    if offset < 0:
        raise InvalidRequest("cursor is not valid")
    return offset


def _cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode().rstrip("=")


@command("survey.results_text", label="Read text answers", action=Action.SURVEY_EXPORT)
def results_text(
    builder: Builder,
    actor: Actor,
    *,
    survey_id: str,
    question: str = "",
    versions: Any = None,
    status: str = "complete",
    submitted_from: Any = None,
    submitted_to: Any = None,
    filters: Sequence[str] = (),
    condition: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    ctx = builder._locate(actor, survey_id, Action.SURVEY_EXPORT)
    del ctx  # located again (with versions) by load(); this keeps the 403/404 first
    raw: dict[str, Any] = {
        "versions": versions or None,
        "status": status,
        "submittedFrom": submitted_from,
        "submittedTo": submitted_to,
        "filters": [
            {"question": qid, "in": sorted(codes)}
            for qid, codes in (parse_code_filter(f, "filter") for f in filters or ())
        ],
        "condition": None,
    }
    if condition:
        var, levels = parse_code_filter(condition, "condition")
        raw["condition"] = {"variable": var, "in": sorted(levels)}
    q = parse_query(raw)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise InvalidRequest("limit must be an integer from 1 to 200")
    offset = _cursor_offset(cursor)
    loaded = load(builder, actor, survey_id, q.versions)
    vs = loaded.versions
    present = [vi for vi in vs if question in vi.vars and not vi.vars[question].matrix]
    if not present:
        raise NotFoundError("Question not found.")
    if any(vi.vars[question].type != "text" for vi in present):
        raise InvalidRequest("not a text question")
    numbers = [vi.number for vi in vs]
    norm = q.normalised(numbers)
    norm.update(cards=None, text=question)
    query_hash = hashlib.sha256(
        json.dumps(norm, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    key = (loaded.ctx.tenant_id, survey_id, tuple(numbers), loaded.watermark, "text:" + query_hash)
    cache = cache_for(builder)
    hit = cache.get(key)
    if hit is None:
        _check_filters(q, vs)
        collect = TextCollect(question)
        scan(builder, loaded.ctx, vs, q, [], None, collect)
        collect.items.sort(key=lambda i: (i[0] is None, i[0] or datetime.min, i[1]))
        hit = (collect.items, _states([collect.acc]))
        cache.put(key, hit)
    items, states = hit
    page = items[offset : offset + limit]
    next_offset = offset + len(page)
    info = present[-1].vars[question]
    fb = present[-1].layout.default_language
    builder.store.audit(
        loaded.ctx,
        "results.read",
        "survey",
        survey_id,
        {
            "kind": "text",
            "question": question,
            "query": norm,
            "versions": numbers,
            "offset": offset,
            "returned": len(page),
        },
    )
    return {
        "question": question,
        "name": info.name,
        "label": _text(info.label, fb, fb),
        "versionsUsed": [vi.number for vi in present],
        "states": states,
        "total": len(items),
        "items": [
            {
                "responseId": rid,
                "version": number,
                "submittedAt": at,
                "language": language if isinstance(language, str) else None,
                "value": value,
            }
            for at, rid, number, language, value in page
        ],
        "nextCursor": _cursor(next_offset) if next_offset < len(items) else None,
        "watermark": loaded.watermark,
    }
