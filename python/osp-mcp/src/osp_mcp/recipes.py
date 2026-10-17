"""Typed drafting requests -> op invocations (pure; no store, no I/O).

An AI agent gets a few typed tools (add a block with its pages, add a page with its
questions, add a question with its choices, …) on top of the generic ``apply_ops``. Each
tool here turns into one transaction of ordinary osp-ops invocations, so everything is
validated by osp-ops and undoable as one step, exactly as if the researcher had done it in
the builder. Nothing here invents behaviour: a request that osp-ops or osp-spec would
refuse comes back as their diagnostics.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from osp_ops.condition_ops import to_ast
from osp_ops.doc import fresh_id
from osp_ops.registry import OpError
from pydantic import BaseModel, ConfigDict, Field, JsonValue

type QuestionType = Literal[
    "integer", "decimal", "text", "single", "multi", "date", "matrix", "slider", "note"
]
type Text = str | dict[str, str]

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChoiceSpec(Spec):
    """One option. ``value`` is the code stored in the data; it defaults to 1, 2, 3, …"""

    label: Text
    value: int | str | None = None


class RowSpec(Spec):
    """One matrix row (a sub-question with its own variable ``<matrix id>_<row id>``)."""

    id: str
    label: Text


class QuestionSpec(Spec):
    """A question to add. Anything osp-survey allows that has no field here (``name``,
    ``min``, ``max``, ``help``, ``shuffleChoices``, …) goes in ``properties`` and is
    validated by the survey model like every other edit."""

    type: QuestionType = "text"
    label: Text = Field(description="What participants read. Notes show it as text.")
    id: str | None = Field(
        default=None,
        description="Variable/data name. Letters, digits and _ (not starting with a digit); "
        "generated from the page id when omitted.",
    )
    required: bool = False
    help: Text | None = None
    choices: list[str | ChoiceSpec] | None = Field(
        default=None,
        description="single, multi and matrix only; a shared list is `choiceList` in properties",
    )
    rows: list[str | RowSpec] | None = Field(default=None, description="matrix only")
    showIf: str | None = Field(
        default=None,
        description="Condition text, e.g. `age >= 18 and answered(consent)`; the question "
        "is shown only while it is true.",
    )
    properties: dict[str, JsonValue] | None = Field(
        default=None, description="Further osp-survey fields for this question type"
    )


class PageSpec(Spec):
    id: str | None = None
    title: Text | None = Field(default=None, description="A heading shown above the items")
    questions: list[QuestionSpec] = Field(min_length=1)
    showIf: str | None = None


def _ident(value: str, what: str) -> str:
    if not isinstance(value, str) or not IDENT.match(value) or len(value) > 64:
        raise ValueError(
            f"{what} id {str(value)[:40]!r} must be letters, digits and _ "
            "(not starting with a digit), at most 64 characters"
        )
    return value


def _choices(spec: list[str | ChoiceSpec]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    used: set[Any] = set()
    next_code = 1
    for c in spec:
        if isinstance(c, str):
            label: Text = c
            value: Any = None
        else:
            label, value = c.label, c.value
        if value is None:
            while next_code in used:
                next_code += 1
            value = next_code
        used.add(value)
        out.append({"value": value, "label": label})
    return out


def _rows(spec: list[str | RowSpec]) -> list[dict[str, Any]]:
    out = []
    for i, r in enumerate(spec):
        if isinstance(r, str):
            out.append({"id": f"r{i + 1}", "label": r})
        else:
            out.append({"id": _ident(r.id, "row"), "label": r.label})
    return out


def condition_ast(text: str, what: str) -> Any:
    """Condition text -> the canonical expression AST (osp-expr), or ``ValueError``."""
    try:
        return to_ast(text)
    except OpError as exc:
        raise ValueError(f"{what} condition does not parse: {exc.diagnostics[0].message}") from exc


def question_object(spec: QuestionSpec, qid: str) -> dict[str, Any]:
    """The osp-survey question object for ``spec``; the survey model validates it."""
    q: dict[str, Any] = {"id": qid, "type": spec.type, "label": spec.label}
    if spec.required:
        q["required"] = True
    if spec.help is not None:
        q["help"] = spec.help
    if spec.showIf is not None:
        q["showIf"] = condition_ast(spec.showIf, f"question {qid!r}")
    if spec.choices is not None:
        q["choices"] = _choices(spec.choices)
    elif spec.type in ("single", "multi", "matrix") and not (
        spec.properties and "choiceList" in spec.properties
    ):
        q["choices"] = [{"value": 1, "label": "Option 1"}]
    if spec.rows is not None:
        q["rows"] = _rows(spec.rows)
    elif spec.type == "matrix":
        q["rows"] = [{"id": "r1", "label": "Row 1"}]
    for key, value in (spec.properties or {}).items():
        if key in ("id", "type"):
            raise ValueError(f"properties may not set {key!r}")
        q[key] = value
    return q


def _page_object(body: Any, spec: PageSpec, pid: str, taken: set[str]) -> dict[str, Any]:
    items = []
    for q in spec.questions:
        if q.id is not None:
            qid = _ident(q.id, "question")
        else:
            qid = fresh_id(body, f"{pid}_q", also=taken)
        taken.add(qid)
        items.append(question_object(q, qid))
    page: dict[str, Any] = {"id": pid, "items": items}
    if spec.title is not None:
        page["title"] = spec.title
    if spec.showIf is not None:
        page["showIf"] = condition_ast(spec.showIf, f"page {pid!r}")
    return page


def add_block_ops(
    body: Any,
    block_id: str,
    *,
    title: str | None = None,
    pages: list[PageSpec] | None = None,
    in_flow: bool = True,
    flow_index: int | None = None,
) -> list[dict[str, Any]]:
    """``add_block`` (with the pages given, else one starter page) and, by default, the
    ``insert_flow_node`` that shows it, in one transaction."""
    bid = _ident(block_id, "block")
    taken = {bid}
    params: dict[str, Any] = {"id": bid}
    if title is not None:
        params["title"] = title
    if pages:
        page_objs = []
        for p in pages:
            pid = (
                _ident(p.id, "page") if p.id is not None else fresh_id(body, f"{bid}_p", also=taken)
            )
            taken.add(pid)
            page_objs.append(_page_object(body, p, pid, taken))
        block: dict[str, Any] = {"id": bid, "pages": page_objs}
        if title is not None:
            block["title"] = title
        params = {"id": bid, "block": block}
    ops: list[dict[str, Any]] = [{"op": "add_block", "params": params}]
    if in_flow:
        node_params: dict[str, Any] = {"node": {"type": "block", "block": bid}}
        if flow_index is not None:
            node_params["index"] = flow_index
        ops.append({"op": "insert_flow_node", "params": node_params})
    return ops


def add_page_ops(
    body: Any, block: str, spec: PageSpec, *, index: int | None = None
) -> list[dict[str, Any]]:
    """One ``add_page`` with the whole page object (questions, title, showIf)."""
    pid = _ident(spec.id, "page") if spec.id is not None else fresh_id(body, "page")
    page = _page_object(body, spec, pid, {pid})
    params: dict[str, Any] = {"block": block, "id": pid, "page": page}
    if index is not None:
        params["index"] = index
    return [{"op": "add_page", "params": params}]


def add_question_ops(
    body: Any, page: str, spec: QuestionSpec, *, index: int | None = None
) -> list[dict[str, Any]]:
    """One ``add_question`` with the whole question object."""
    qid = _ident(spec.id, "question") if spec.id is not None else fresh_id(body, "q")
    params: dict[str, Any] = {"page": page, "id": qid, "question": question_object(spec, qid)}
    if index is not None:
        params["index"] = index
    return [{"op": "add_question", "params": params}]
