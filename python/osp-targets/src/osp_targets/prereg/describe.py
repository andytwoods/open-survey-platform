"""The preregistration description of one published version, as data. Pure, deterministic.

Everything here is derived from the survey document (and the layout the codebook already
builds): the structure (blocks, pages, questions), a walk of the flow, the randomisation
and assignment design (semantics.md §7), the quotas (§6), and the **planned exclusions**:
what the platform records about every response that a researcher can exclude on, read off
the settings (§5, §10, §11) and the flow's end outcomes. Nothing reads a clock, and
nothing here invents a rule: each exclusion names the column or record it rests on.
"""

from __future__ import annotations

from typing import Any

from osp_spec import (
    AssignNode,
    BlockNode,
    BranchNode,
    EndNode,
    NoteQuestion,
    QuotaCheckNode,
    RandomiserNode,
)

from ..data.layout import Layout, build_layout
from ..data.model import SurveyVersion

FORMAT = "osp-prereg/1"

SEED_SCHEME = (
    "Each session gets a random positive integer seed, drawn by the server at session "
    "start and recorded with the response (`_seed`). Every random decision has its own "
    "stream, seeded from the published version number, the session seed and the decision's "
    "id (SHA-256 of a netstring triple, reduced to a Park-Miller seed). Orders are "
    "inside-out Fisher-Yates shuffles of that stream (the XForms `randomize()` algorithm); "
    "an assignment is one uniform draw from it. A realised order or assignment is fixed "
    "the first time the participant reaches it and never re-rolled on back, refresh or "
    "resume. Every response records its realised orders and assigned conditions, so each "
    "can be recomputed from the seed (see the reproducibility package's `replay.py`)."
)
ASSIGNMENT_METHOD = (
    "Simple randomisation: each assigned variable is an independent, uniform draw over "
    "its levels, made by the server when the participant first reaches the assign node "
    "(or by the participant's engine from the same stream, recorded as `seeded`). "
    "Allocation is not balanced, blocked or weighted: osp-survey/0.1 models none of these, "
    "so the realised group sizes vary by chance. Quotas can cap a group but do not "
    "balance it."
)

RETENTION_TEXT = {
    "days-after-close": "Participant data is deleted {days} days after the survey closes.",
    "after-date": "Participant data is deleted after {until}.",
    "indefinite": "Participant data is kept until the researcher deletes it (an explicit "
    "choice, not a default).",
}


def _text(lay: Layout, value: Any) -> dict[str, str]:
    return lay.text(value) if isinstance(value, str | dict) else {}


def _block_summary(lay: Layout, block_id: str) -> dict[str, Any]:
    block = next((b for b in lay.survey.blocks if b.id == block_id), None)
    if block is None:
        return {"id": block_id, "title": None, "pages": [], "questions": 0, "notes": 0}
    pages = []
    questions = notes = 0
    for p in block.pages:
        qs = [q for q in p.items if not isinstance(q, NoteQuestion)]
        ns = len(p.items) - len(qs)
        questions += len(qs)
        notes += ns
        pages.append(
            {
                "id": p.id,
                "title": _text(lay, p.title) or None,
                "itemOrder": p.itemOrder,
                "showIf": lay.expr_text(p.showIf),
                "questions": [lay.names.get(q.id, q.id) for q in qs],
                "notes": ns,
            }
        )
    return {
        "id": block.id,
        "title": block.title,
        "pages": pages,
        "questions": questions,
        "notes": notes,
    }


def _walk(lay: Layout, nodes: Any, depth: int, out: list[dict[str, Any]]) -> None:
    """A depth-first outline of the flow: one entry per node, ``then`` before ``else``."""
    blocks = {b.id: b for b in lay.survey.blocks}
    quotas = {q.id: q for q in lay.survey.quotas}
    for node in nodes:
        entry: dict[str, Any] = {"depth": depth, "type": node.type, "id": node.id}
        if isinstance(node, BlockNode):
            b = blocks.get(node.block)
            pages = len(b.pages) if b else 0
            qs = (
                sum(len([q for q in p.items if not isinstance(q, NoteQuestion)]) for p in b.pages)
                if b
                else 0
            )
            entry |= {
                "block": node.block,
                "title": b.title if b else None,
                "pages": pages,
                "questions": qs,
            }
            entry["text"] = (
                f"Block `{node.block}`"
                + (f" ({b.title})" if b and b.title else "")
                + f": {pages} page{'s' if pages != 1 else ''}, "
                + f"{qs} question{'s' if qs != 1 else ''}"
            )
            out.append(entry)
        elif isinstance(node, BranchNode):
            entry |= {"if": lay.expr_text(node.if_)}
            entry["text"] = f"If `{entry['if']}`:"
            out.append(entry)
            _walk(lay, node.then, depth + 1, out)
            if node.else_:
                out.append({"depth": depth, "type": "else", "id": node.id, "text": "Otherwise:"})
                _walk(lay, node.else_, depth + 1, out)
        elif isinstance(node, RandomiserNode):
            n = len(node.children)
            entry |= {"children": n, "pick": node.pick, "column": f"_order.blocks.{node.id}"}
            shown = f"show {node.pick} of them" if node.pick else "show all of them"
            entry["text"] = (
                f"Randomiser `{node.id}`: shuffle the order of its {n} children "
                f"({shown}); recorded in `_order.blocks.{node.id}`"
            )
            out.append(entry)
            _walk(lay, node.children, depth + 1, out)
        elif isinstance(node, AssignNode):
            names = [lay.names.get(v, v) for v in node.variables]
            entry |= {"variables": names}
            entry["text"] = (
                f"Assign `{node.id}`: each of {', '.join(f'`{v}`' for v in names)} gets one "
                "level by an independent uniform seeded draw"
            )
            out.append(entry)
        elif isinstance(node, QuotaCheckNode):
            q = quotas.get(node.quota)
            entry |= {"quota": node.quota}
            if q is not None:
                full = f"outcome `{q.onFull.outcome}`"
                if q.onFull.block:
                    full = f"show block `{q.onFull.block}`, then {full}"
                entry["text"] = (
                    f"Quota check `{node.id}`: quota `{q.id}` (limit {q.limit} complete "
                    f"responses while `{lay.expr_text(q.when)}`); when full: {full}"
                )
            else:
                entry["text"] = f"Quota check `{node.id}`: quota `{node.quota}`"
            out.append(entry)
        elif isinstance(node, EndNode):
            entry |= {"outcome": node.outcome, "message": _text(lay, node.message) or None}
            entry["text"] = f"End `{node.id}`: outcome `{node.outcome}`"
            out.append(entry)


def _outcomes(flow: list[dict[str, Any]], lay: Layout) -> list[dict[str, Any]]:
    """Every way a session can end, with the `_end` value it records."""
    by: dict[str, dict[str, Any]] = {}

    def add(outcome: str, source: str, where: str) -> None:
        entry = by.setdefault(outcome, {"outcome": outcome, "sources": []})
        entry["sources"].append({"kind": source, "id": where})

    for n in flow:
        if n["type"] == "end":
            add(n["outcome"], "end node", n["id"])
    add("complete", "end of flow", "(implicit end)")
    for q in lay.survey.quotas:
        add(q.onFull.outcome, "quota full", q.id)
    if lay.survey.consent is not None:
        add(lay.survey.consent.declineOutcome, "consent declined", "consent")
    return [by[k] for k in sorted(by, key=lambda o: (o != "complete", o))]


def _exclusions(lay: Layout, outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the platform records that a researcher can exclude on. Each rule names its
    evidence (a column, an outcome, a record) and whether it applies to this design."""
    s = lay.survey.settings
    rules: list[dict[str, Any]] = []

    def rule(rid: str, title: str, text: str, *, evidence: str, applies: bool = True) -> None:
        rules.append(
            {"id": rid, "title": title, "applies": applies, "evidence": evidence, "text": text}
        )

    every_page = s.saveMode == "every-page"
    rule(
        "incomplete",
        "Incomplete sessions",
        "Only submitted responses are exported; a participant who stops before the final "
        "submit is never a row in the data. "
        + (
            "Answers were saved on every page, so drop-outs exist as partial sessions on "
            "the server (visible to the researcher, never exported) and attrition can be "
            "reported."
            if every_page
            else "Nothing was sent before the final submit (end-only saving), so drop-outs "
            "are invisible and attrition cannot be reported."
        ),
        evidence="submitted responses only; server session counts"
        if every_page
        else "submitted responses only",
    )
    rule(
        "late",
        "Late submissions",
        f"A session's holds (its quota place and resume link) expire after "
        f"{s.resumeExpiryDays} idle day{'s' if s.resumeExpiryDays != 1 else ''}. A response "
        "that arrives after that is still accepted but flagged, so the researcher decides "
        "whether to keep it.",
        evidence="`_late` column",
    )
    rule(
        "after_close",
        "Submitted after the survey closed",
        "A session that started before the survey was closed may still finish; its "
        "response is flagged.",
        evidence="`_after_close` column",
    )
    other = [o for o in outcomes if o["outcome"] != "complete"]
    rule(
        "outcome",
        "Non-complete endings",
        "Every response records how its session ended. Endings other than `complete` "
        + (
            "in this design: "
            + "; ".join(
                f"`{o['outcome']}` ("
                + ", ".join(f"{src['kind']} `{src['id']}`" for src in o["sources"])
                + ")"
                for o in other
            )
            + "."
            if other
            else "do not exist in this design: every session that submits ends `complete`."
        ),
        evidence="`_end` column",
        applies=bool(other),
    )
    quotas = lay.survey.quotas
    rule(
        "quota_full",
        "Quota full",
        (
            "A participant who reaches a full quota is shown at most one block and then "
            "ended with the quota's outcome; no further answers are collected. Quotas count "
            "completed responses; a place is held at the check and released after "
            f"{s.resumeExpiryDays} idle days, so slightly more than the limit can complete "
            "if held places are resumed late (those responses are flagged `_late`). "
            + "; ".join(f"`{q.id}`: limit {q.limit}, outcome `{q.onFull.outcome}`" for q in quotas)
            + "."
            if quotas
            else "This design has no quotas."
        ),
        evidence="`_end` column (the quota's outcome)",
        applies=bool(quotas),
    )
    consent = lay.survey.consent
    rule(
        "declined",
        "Consent declined",
        (
            f"Declining the consent page ends the session with outcome "
            f"`{consent.declineOutcome}`; no response and no answers are recorded, "
            + (
                "and an anonymous count of declines is kept."
                if consent.countDeclines
                else "and declines are not counted (the option is off)."
            )
            if consent is not None
            else "This version has no consent page: consent is taken elsewhere, and the "
            "platform records nothing about it."
        ),
        evidence="no response row; decline count"
        if consent is not None and consent.countDeclines
        else "no response row",
        applies=consent is not None,
    )
    rule(
        "withdrawn",
        "Withdrawn responses",
        "A participant can withdraw from the end screen or the resume link: the response "
        "and its session are deleted, and the audit log keeps only the reason and the "
        "number of responses deleted, never an answer. A researcher may also delete one "
        "response on request. Withdrawn responses therefore never appear in an export.",
        evidence="audit log (`response.delete`), no response row",
    )
    rule(
        "conflict",
        "Two devices, diverging copies",
        "When a stale copy of a session saves after another device moved on, the server's "
        "copy wins; the losing copy is kept encrypted for a limited time and is excluded "
        "from every export.",
        evidence="excluded automatically",
        applies=every_page,
    )
    rule(
        "missing",
        "Missing answers",
        "Every question in a response is in exactly one state: `answered`, `unanswered` "
        "(shown, left empty), `irrelevant` (hidden by its condition) or `not-reached`. The "
        "CSV writes an empty cell plus a `<name>__state` column; no numeric missing codes "
        "are ever written, so a listwise or per-variable exclusion can be stated in terms "
        "of these states.",
        evidence="`<name>__state` columns",
    )
    ret = s.retention
    rule(
        "retention",
        "Data retention",
        (
            RETENTION_TEXT[ret.kind].format(days=ret.days, until=ret.until)
            if ret is not None
            else "No retention policy is set (publishing requires one; this document "
            "describes a version without it)."
        ),
        evidence="settings.retention",
        applies=ret is not None,
    )
    return rules


def prereg_data(version: SurveyVersion) -> dict[str, Any]:
    """The preregistration description of ``version``. Raises ``ExportError`` only when
    the survey is not a valid osp-survey document (like the codebook)."""
    lay = build_layout(version)
    s = lay.survey
    md = s.metadata
    flow: list[dict[str, Any]] = []
    _walk(lay, s.flow, 0, flow)
    outcomes = _outcomes(flow, lay)
    blocks = [_block_summary(lay, b.id) for b in s.blocks]
    placed = {n["block"] for n in flow if n["type"] == "block"}
    settings = s.settings
    return {
        "format": FORMAT,
        "survey": {
            "id": s.id,
            "title": lay.text(md.title),
            "description": lay.text(md.description) if md.description is not None else None,
            "version": lay.number,
            "checksum": lay.checksum,
            "languages": lay.languages,
            "defaultLanguage": lay.default_language,
            "license": md.license,
            "ddi": md.ddi,
            # The instruments used, derived at publish (question-bank.md lead decision 1).
            **(
                {
                    "instruments": [
                        i.model_dump(mode="json", by_alias=True, exclude_none=True)
                        for i in md.instruments
                    ]
                }
                if md.instruments
                else {}
            ),
        },
        "structure": {
            "blocks": blocks,
            "unplacedBlocks": sorted(b.id for b in s.blocks if b.id not in placed),
            "pages": sum(len(b["pages"]) for b in blocks),
            "questions": sum(b["questions"] for b in blocks),
            "notes": sum(b["notes"] for b in blocks),
            "choiceLists": [cl.id for cl in s.choiceLists],
        },
        "flow": flow,
        "outcomes": outcomes,
        "randomisation": {
            "seedScheme": SEED_SCHEME,
            "randomisers": [
                {
                    "id": r.id,
                    "children": r.children,
                    "blocks": r.blocks,
                    "pick": r.pick,
                    "column": f"_order.blocks.{r.id}",
                }
                for r in lay.randomisers
            ],
            "orders": [
                {
                    "column": o.column,
                    "kind": o.kind,
                    "node": o.node,
                    "of": o.of,
                    **({"pick": o.pick} if o.pick else {}),
                }
                for o in lay.orders
            ],
            "assignment": {
                "method": ASSIGNMENT_METHOD,
                "nodes": [
                    {"id": n["id"], "variables": n["variables"]}
                    for n in flow
                    if n["type"] == "assign"
                ],
                "conditions": [
                    {"name": v.name, "id": v.id, "levels": v.levels} for v in lay.assigned
                ],
            },
            "quotas": [
                {
                    "id": q.id,
                    "when": lay.expr_text(q.when),
                    "limit": q.limit,
                    "countOn": q.countOn,
                    "onFull": {"block": q.onFull.block, "outcome": q.onFull.outcome},
                }
                for q in s.quotas
            ],
        },
        "settings": {
            "saveMode": settings.saveMode,
            "localCopy": settings.localCopy,
            "backNavigation": settings.backNavigation,
            "resumeExpiryDays": settings.resumeExpiryDays,
            "retention": (
                settings.retention.model_dump(mode="json", exclude_none=True)
                if settings.retention is not None
                else None
            ),
            "consent": s.consent is not None,
            "hooks": s.hooks is not None,
        },
        "exclusions": _exclusions(lay, outcomes),
        "questions": [
            {
                "name": q.name,
                "id": q.id,
                "type": q.type,
                "label": q.label,
                "block": q.block,
                "page": q.page,
                "required": q.required,
                "showIf": q.show_if,
                "choices": None if q.choices is None else [c.code for c in q.choices],
                "choiceOrder": q.choice_order,
            }
            for q in lay.questions
        ],
    }


__all__ = ["ASSIGNMENT_METHOD", "FORMAT", "SEED_SCHEME", "prereg_data"]
