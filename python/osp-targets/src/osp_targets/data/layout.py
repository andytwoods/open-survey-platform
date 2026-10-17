"""What a version exports: its variables in survey order, and the CSV columns they become.

Survey order is the runtime plan's export order (``osp_runtime.plan``: ``questions``): a
depth-first walk of the flow, ``then`` before ``else``, randomiser children, pages and items
in document order. A block that is not in the flow is never reached and has no column.
Exports use each variable's ``name`` (default: its ``id``); records are keyed by ``id``.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from typing import Any

from osp_expr import references, to_text
from osp_expr.ast import EXPR_ADAPTER
from osp_spec import (
    AssignedVariable,
    BlockNode,
    BranchNode,
    ComputedVariable,
    Diagnostic,
    EmbeddedVariable,
    FlowNode,
    MatrixQuestion,
    MultiQuestion,
    NoteQuestion,
    RandomiserNode,
    SingleQuestion,
    SliderQuestion,
    Survey,
    matrix_row_id,
    matrix_row_name,
    matrix_row_required,
    parse,
)

from .model import CsvOptions, ExportError, SurveyVersion

STATE_SUFFIX = "__state"


@dataclass(frozen=True)
class ChoiceInfo:
    code: Any
    label: dict[str, str]


@dataclass(frozen=True)
class QuestionInfo:
    id: str
    name: str
    type: str
    label: dict[str, str]
    help: dict[str, str] | None
    required: bool
    show_if: str | None
    constraint: str | None
    constraint_message: dict[str, str] | None
    choices: list[ChoiceInfo] | None
    choice_order: str | None
    page: str
    block: str
    # A matrix row (semantics.md §2, C2c-1): the matrix's id and text; the row is a
    # single-choice variable of its own, `<matrix name>_<row id>`.
    matrix: str | None = None
    matrix_label: dict[str, str] | None = None
    # A slider (C2c-3): {"valueType", "min", "max", "step"}.
    scale: dict[str, Any] | None = None
    # The lab's own annotations on the question (planning/property-profiles.md §5); a
    # matrix row carries its matrix's.
    custom: dict[str, Any] | None = None
    # Question-bank provenance (question-bank.md §2.3): {bank, version, library} of the
    # question's own source, else its page's, else its block's; a matrix row has its matrix's.
    source: dict[str, Any] | None = None


@dataclass(frozen=True)
class VariableInfo:
    id: str
    name: str
    kind: str  # assigned | embedded | computed
    levels: list[Any] | None = None
    value_type: str | None = None
    param: str | None = None
    default: Any = None
    expr: str | None = None
    # computed: the question ids it reads, following other computed variables (for its
    # state when the record has none, semantics C2-6)
    inputs: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrderInfo:
    column: str
    kind: str  # blocks | items | choices
    node: str  # randomiser id, page id or question id (the record's key)
    of: list[str]  # what is ordered: child node ids, item ids or choice codes (as text)
    pick: int | None = None


@dataclass(frozen=True)
class RandomiserInfo:
    id: str
    children: list[str]
    blocks: list[list[str]]  # blocks under each child, for the codebook
    pick: int | None


@dataclass
class Layout:
    survey: Survey
    number: int | None
    checksum: str | None
    languages: list[str]
    default_language: str
    questions: list[QuestionInfo] = field(default_factory=list)
    assigned: list[VariableInfo] = field(default_factory=list)
    embedded: list[VariableInfo] = field(default_factory=list)
    computed: list[VariableInfo] = field(default_factory=list)
    orders: list[OrderInfo] = field(default_factory=list)
    randomisers: list[RandomiserInfo] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)  # id -> export name

    @property
    def title(self) -> str:
        return self.text(self.survey.metadata.title).get(self.default_language, "")

    def text(self, value: str | dict[str, str] | None) -> dict[str, str]:
        """Translatable text as ``{language: text}`` for every survey language (a plain
        string applies to all of them; a missing translation falls back like the plan)."""
        if value is None:
            return {}
        if isinstance(value, str):
            return dict.fromkeys(self.languages, value)
        fallback = value.get(self.default_language, next(iter(value.values()), ""))
        return {lang: value.get(lang, fallback) for lang in self.languages}

    def expr_text(self, expr: Any) -> str | None:
        """An expression in text syntax, with references printed as export names."""
        if expr is None:
            return None
        try:
            data = _rename_refs(EXPR_ADAPTER.dump_python(expr, mode="json"), self.names)
            return to_text(EXPR_ADAPTER.validate_python(data))
        except Exception:  # an odd name: fall back to ids rather than fail the codebook
            try:
                return to_text(expr)
            except Exception:
                return "(unprintable expression)"


def _rename_refs(node: Any, names: dict[str, str]) -> Any:
    if isinstance(node, dict):
        out = {k: _rename_refs(v, names) for k, v in node.items()}
        if out.get("kind") == "ref" and isinstance(out.get("id"), str):
            out["id"] = names.get(out["id"], out["id"])
        return out
    if isinstance(node, list):
        return [_rename_refs(v, names) for v in node]
    return node


def _source(*objs: Any) -> dict[str, Any] | None:
    """The nearest `source` of a question, its page, its block (as {bank, version, library})."""
    for o in objs:
        src = getattr(o, "source", None)
        if src is not None:
            return {"bank": src.bank, "version": src.version, "library": src.library}
    return None


def parse_version(version: SurveyVersion) -> Survey:
    survey = version.survey
    if isinstance(survey, Survey):
        return survey
    model, diagnostics = parse(survey)
    if model is None:
        raise ExportError("The survey version is not a valid osp-survey document.", diagnostics)
    return model


def build_layout(version: SurveyVersion, split: Collection[str] = ()) -> Layout:
    """The layout of one version. ``split``: export names exported as ``<name>_v<N>`` in
    this version (a combined export of versions whose type or choices differ, M2-3)."""
    s = parse_version(version)
    md = s.metadata
    lay = Layout(
        survey=s,
        number=version.number if version.number is not None else s.version,
        checksum=version.checksum,
        languages=list(md.languages),
        default_language=md.defaultLanguage or md.languages[0],
    )
    lists = {cl.id: cl.choices for cl in s.choiceLists}
    blocks = {b.id: b for b in s.blocks}
    for b in s.blocks:
        for p in b.pages:
            for q in p.items:
                if isinstance(q, MatrixQuestion):
                    for row in q.rows:
                        lay.names[matrix_row_id(q.id, row.id)] = matrix_row_name(q, row.id)
                elif not isinstance(q, NoteQuestion):
                    lay.names[q.id] = q.name or q.id
    for v in s.variables:
        lay.names[v.id] = v.name or v.id
    if split:
        suffix = version_suffix(lay)
        for b in s.blocks:
            for p in b.pages:
                for qid in _variable_ids(p.items):
                    if qid in lay.names and lay.names[qid] in split:
                        lay.names[qid] += suffix
    seen_blocks: set[str] = set()

    def add_block(block_id: str) -> None:
        block = blocks.get(block_id)
        if block is None or block_id in seen_blocks:
            return
        seen_blocks.add(block_id)
        for page in block.pages:
            if page.itemOrder == "shuffle":
                lay.orders.append(
                    OrderInfo(
                        f"_order.items.{page.id}", "items", page.id, [q.id for q in page.items]
                    )
                )
            for q in page.items:
                if isinstance(q, NoteQuestion):
                    continue
                if isinstance(q, MatrixQuestion):
                    source = q.choices if q.choices is not None else lists.get(q.choiceList or "")
                    columns = [ChoiceInfo(c.value, lay.text(c.label)) for c in source or []]
                    for row in q.rows:
                        rid = matrix_row_id(q.id, row.id)
                        lay.questions.append(
                            QuestionInfo(
                                id=rid,
                                name=lay.names[rid],
                                type="single",
                                label=lay.text(row.label),
                                help=lay.text(q.help) if q.help is not None else None,
                                required=matrix_row_required(q, row),
                                show_if=lay.expr_text(q.showIf),
                                constraint=None,
                                constraint_message=None,
                                choices=columns,
                                choice_order="fixed",
                                page=page.id,
                                block=block_id,
                                matrix=q.id,
                                matrix_label=lay.text(q.label),
                                custom=dict(q.custom) if q.custom else None,
                                source=_source(q, page, block),
                            )
                        )
                    continue
                choices = None
                order = None
                if isinstance(q, SingleQuestion | MultiQuestion):
                    source = q.choices if q.choices is not None else lists.get(q.choiceList or "")
                    choices = [ChoiceInfo(c.value, lay.text(c.label)) for c in source or []]
                    order = q.choiceOrder
                    if order == "shuffle":
                        name = lay.names[q.id]
                        lay.orders.append(
                            OrderInfo(
                                f"_order.choices.{name}",
                                "choices",
                                q.id,
                                [str(c.code) for c in choices],
                            )
                        )
                lay.questions.append(
                    QuestionInfo(
                        id=q.id,
                        name=lay.names[q.id],
                        type=q.type,
                        label=lay.text(q.label),
                        help=lay.text(q.help) if q.help is not None else None,
                        required=q.required,
                        show_if=lay.expr_text(q.showIf),
                        constraint=lay.expr_text(q.constraint),
                        constraint_message=(
                            lay.text(q.constraintMessage)
                            if q.constraintMessage is not None
                            else None
                        ),
                        choices=choices,
                        choice_order=order,
                        page=page.id,
                        block=block_id,
                        scale=(
                            {
                                "valueType": q.valueType,
                                "min": q.min,
                                "max": q.max,
                                "step": q.step,
                            }
                            if isinstance(q, SliderQuestion)
                            else None
                        ),
                        custom=dict(q.custom) if q.custom else None,
                        source=_source(q, page, block),
                    )
                )

    def blocks_under(n: FlowNode) -> list[str]:
        match n:
            case BlockNode():
                return [n.block]
            case BranchNode():
                return [b for c in [*n.then, *n.else_] for b in blocks_under(c)]
            case RandomiserNode():
                return [b for c in n.children for b in blocks_under(c)]
            case _:
                return []

    def walk(nodes: list[FlowNode]) -> None:
        for n in nodes:
            match n:
                case BlockNode():
                    add_block(n.block)
                case BranchNode():
                    walk(n.then)
                    walk(n.else_)
                case RandomiserNode():
                    lay.randomisers.append(
                        RandomiserInfo(
                            n.id,
                            [c.id for c in n.children],
                            [blocks_under(c) for c in n.children],
                            n.pick,
                        )
                    )
                    lay.orders.append(
                        OrderInfo(
                            f"_order.blocks.{n.id}",
                            "blocks",
                            n.id,
                            [c.id for c in n.children],
                            n.pick,
                        )
                    )
                    walk(n.children)
                case _:
                    pass

    walk(s.flow)
    for quota in s.quotas:  # a quota's "when full" block comes after the flow, as in the plan
        if quota.onFull.block:
            add_block(quota.onFull.block)
    for v in s.variables:
        name = v.name or v.id
        match v:
            case AssignedVariable():
                lay.assigned.append(VariableInfo(v.id, name, "assigned", levels=list(v.levels)))
            case EmbeddedVariable():
                lay.embedded.append(
                    VariableInfo(
                        v.id,
                        name,
                        "embedded",
                        value_type=v.valueType,
                        param=v.param,
                        default=v.default,
                    )
                )
            case ComputedVariable():
                lay.computed.append(
                    VariableInfo(
                        v.id,
                        name,
                        "computed",
                        expr=lay.expr_text(v.expr),
                        inputs=_question_inputs(s, v.id),
                    )
                )
    return lay


def _question_inputs(s: Survey, var_id: str) -> tuple[str, ...]:
    """Question ids a computed variable reads, following computed variables (cycles cut)."""
    exprs = {v.id: v.expr for v in s.variables if isinstance(v, ComputedVariable)}
    questions = {qid for b in s.blocks for p in b.pages for qid in _variable_ids(p.items)}
    out: list[str] = []
    seen: set[str] = set()
    stack = [var_id]
    while stack:
        vid = stack.pop()
        if vid in seen or vid not in exprs:
            continue
        seen.add(vid)
        for ref in references(exprs[vid]):
            if ref in questions and ref not in out:
                out.append(ref)
            elif ref in exprs:
                stack.append(ref)
    return tuple(out)


def _variable_ids(items: Sequence[Any]) -> list[str]:
    """Ids of the variables a page's items hold: a matrix holds one per row (C2c-1)."""
    out: list[str] = []
    for q in items:
        if isinstance(q, MatrixQuestion):
            out += [matrix_row_id(q.id, row.id) for row in q.rows]
        elif not isinstance(q, NoteQuestion):
            out.append(q.id)
    return out


# -- pooling versions (semantics M2-3) ----------------------------------------------------


def _definition(q: QuestionInfo) -> tuple[str, tuple[str, ...] | None]:
    """What makes a question's data comparable across versions: its type and choice codes."""
    codes = None if q.choices is None else tuple(sorted(str(c.code) for c in q.choices))
    kind = f"slider:{q.scale['valueType']}" if q.scale else q.type
    return (kind, codes)


def split_names(layouts: Sequence[Layout]) -> set[str]:
    """Export names of questions whose type or choice codes differ between versions; each
    version exports them under its own ``<name>_v<N>`` columns."""
    defs: dict[str, set[tuple[str, tuple[str, ...] | None]]] = {}
    for lay in layouts:
        for q in lay.questions:
            defs.setdefault(q.name, set()).add(_definition(q))
    return {name for name, d in defs.items() if len(d) > 1}


def version_suffix(lay: Layout) -> str:
    """``_v<N>``, N the version number (0 for a draft)."""
    return f"_v{lay.number if lay.number is not None else 0}"


# -- CSV columns ------------------------------------------------------------------------


@dataclass(frozen=True)
class Column:
    header: str
    group: str  # meta | condition | question | state | variable | order
    var: str | None  # export name of the variable it belongs to, if any
    cell: Callable[[Any], Any]  # ResponseView -> raw cell value (formatted later)


META_COLUMNS: list[tuple[str, str]] = [
    ("_response_id", "Response id (server)."),
    ("_session_id", "Participant session id (pseudonymous)."),
    ("_version", "Published survey version the response belongs to (semantics §9)."),
    ("_version_checksum", "Checksum of that version's survey document."),
    ("_plan_checksum", "Checksum of the runtime plan the participant's browser ran."),
    ("_engine_version", "Version of the participant engine (web/engine)."),
    (
        "_allocation_mode",
        "How conditions were assigned: server (our server, at session start), seeded "
        "(the engine drew at least one condition from the session seed), or "
        "limesurvey-native.",
    ),
    ("_save_mode", "every-page or end-only (runtime-design §5.0)."),
    ("_seed", "Session seed (positive integer, semantics §7); reproduces every order."),
    ("_started_at", "Session start, UTC, ISO 8601."),
    ("_submitted_at", "Submission accepted by the server, UTC, ISO 8601."),
    (
        "_late",
        "true if the server accepted the submit after the session had expired (its quota "
        "holds were released or its resume link had expired); a late response is not "
        "counted toward quotas (semantics S-2). Set by the server, never by the browser.",
    ),
    (
        "_after_close",
        "true if the response was submitted after the survey was closed; empty if not known.",
    ),
    ("_end", "End outcome reached (e.g. complete); empty if none was recorded."),
    ("_language", "Language the participant used."),
]


# Only for a version with a consent page (semantics.md §11). A declined session leaves no
# response and a withdrawn one is deleted, so every row here is a consented one.
CONSENT_COLUMNS: list[tuple[str, str]] = [
    (
        "_consent_version",
        "The consent text the participant agreed to: sha256 checksum of the consent page's "
        "texts (every language) as published. A changed wording is a new version.",
    ),
    ("_consented_at", "When the participant agreed (server clock), UTC, ISO 8601."),
]


def meta_columns(lay: Layout) -> list[tuple[str, str]]:
    """The meta columns of a version: the consent columns only if it has a consent page."""
    return META_COLUMNS + (CONSENT_COLUMNS if lay.survey.consent is not None else [])


def csv_columns(lay: Layout, opts: CsvOptions) -> list[Column]:
    cols: list[Column] = []
    for header, _ in meta_columns(lay):
        cols.append(Column(header, "meta", None, lambda r, h=header: r.meta(h)))
    for v in lay.assigned:
        cols.append(Column(v.name, "condition", v.name, lambda r, i=v.id: r.condition(i)))
    for q in lay.questions:
        if q.type == "multi" and opts.multi == "columns":
            for c in q.choices or []:
                cols.append(
                    Column(
                        f"{q.name}_{c.code}",
                        "question",
                        q.name,
                        lambda r, i=q.id, code=c.code: r.multi_flag(i, code),
                    )
                )
        else:
            cols.append(Column(q.name, "question", q.name, lambda r, i=q.id: r.value(i)))
        if opts.state_columns:
            cols.append(
                Column(q.name + STATE_SUFFIX, "state", q.name, lambda r, i=q.id: r.state(i))
            )
    for v in [*lay.embedded, *lay.computed]:
        cols.append(Column(v.name, "variable", v.name, lambda r, i=v.id: r.variable(i)))
        if opts.state_columns:
            cols.append(
                Column(
                    v.name + STATE_SUFFIX,
                    "state",
                    v.name,
                    lambda r, i=v.id: r.variable_state(i),
                )
            )
    for o in lay.orders:
        cols.append(Column(o.column, "order", None, lambda r, o=o: r.order(o)))
    clashes = _clashes([c.header for c in cols])
    if clashes:
        raise ExportError(
            "Two columns would get the same name: " + ", ".join(clashes) + ".",
            [
                Diagnostic(
                    severity="error",
                    code="export.column_clash",
                    message=(
                        f"column {h!r} appears twice (a multi choice column <var>_<code> "
                        "matches another variable's name?); rename a variable or export "
                        "multi answers as codes in one cell"
                    ),
                    pointer="",
                )
                for h in clashes
            ],
        )
    return cols


def _clashes(headers: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for h in headers:
        if h in seen and h not in out:
            out.append(h)
        seen.add(h)
    return out
