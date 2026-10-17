"""Runtime plan compiler: a validated `osp-survey` → the plain JSON the browser engine runs.

The plan (`contract/runtime-plan.schema.json`, TS types in `web/engine/src/plan.ts`) is what
`web/engine` executes (planning/runtime-design.md §3). Compared with the survey it:

- resolves ids: a block node carries its page ids, a choice question carries its choices
  (inline or from its `choiceList`), a quota check carries its quota id (quotas are a map);
- flattens: `items`, `pages`, `blocks`, `variables` and `quotas` are maps keyed by id, and
  `questions` lists every answerable question id in flow order (the export column order);
- splits a `matrix` into its rows (semantics.md §2, C2c-1): the matrix item (on the page)
  lists its row ids in `rows`; each row is its own `single` item `<matrix id>_<row id>`
  with `matrix` pointing back, the matrix's columns as `choices`, and its own `required`.
  Rows (not the matrix) are in `questions`. A row has no `showIf`: it is relevant exactly
  when its matrix is;
- a `slider` item carries `valueType`, `min`, `max`, `step` and its end labels;
- embeds expressions as `osp-expr` AST JSON (the browser never parses text syntax);
- splits every translatable text into segments per language: a plain string, or
  `{"pipe": id}` for `${id}` (semantics.md §8). The engine fills pipes; the renderer
  HTML-escapes the filled values;
- records `planVersion`, `engineVersion` (the engine API major the plan targets) and a
  `checksum` (SHA-256 of the canonical JSON of the plan without `checksum`).

Pure: no I/O. `compile_plan` raises `PlanError` only for a survey `osp_spec` rejects;
`compile_survey` never raises and returns diagnostics instead (AGENTS.md rule 3).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from osp_spec import Diagnostic, Survey, has_errors, parse
from osp_spec.model import (
    AssignedVariable,
    AssignNode,
    BlockNode,
    BranchNode,
    Choice,
    ComputedVariable,
    EmbeddedVariable,
    EndNode,
    FlowNode,
    MatrixQuestion,
    MultiQuestion,
    NoteQuestion,
    QuotaCheckNode,
    RandomiserNode,
    SingleQuestion,
    SliderQuestion,
    matrix_row_id,
    matrix_row_name,
    matrix_row_required,
)

__all__ = [
    "ENGINE_VERSION",
    "PLAN_VERSION",
    "PlanError",
    "canonical_json",
    "checksum",
    "compile_plan",
    "compile_survey",
    "embed_theme",
    "expr_json",
    "runtime_config",
    "seed_node",
    "seed_version",
    "segments",
]

PLAN_VERSION = "osp-runtime-plan/1"
"""Plan format version. A breaking change to the format needs a new number."""

ENGINE_VERSION = "1"
"""Major version of the engine API (`web/engine`) this plan targets."""

_PIPE = re.compile(r"\$\{([^}]*)\}")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Built-in `$` variables (runtime-design.md §7a): `${$trial}`, `${$position.index}`.
_BUILTIN = re.compile(r"^\$(trial|position\.index|position\.of|pagesDone|language|device)$")

type Json = Any
type Segment = str | dict[str, str]


class PlanError(ValueError):
    """The survey has error diagnostics, so no plan can be built."""

    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        super().__init__(f"survey has {len(diagnostics)} error diagnostic(s)")
        self.diagnostics = diagnostics


# --- Canonical JSON and checksum -------------------------------------------------------


def canonical_json(value: Json) -> str:
    """Sorted keys, no whitespace, UTF-8 text kept as is. `web/engine` mirrors this."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def checksum(plan: Json) -> str:
    """`sha256:<hex>` of the canonical JSON of `plan` without its `checksum` field."""
    body = {k: v for k, v in plan.items() if k != "checksum"}
    return "sha256:" + hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


MAX_SAFE_INT = 2**53 - 1


def _safe_ints(node: Json) -> Json:
    if isinstance(node, dict):
        out = {k: _safe_ints(v) for k, v in node.items()}
        v = out.get("value")
        if out.get("kind") == "int" and isinstance(v, int) and abs(v) > MAX_SAFE_INT:
            out["value"] = str(v)
        return out
    if isinstance(node, list):
        return [_safe_ints(x) for x in node]
    return node


def expr_json(expr: Any) -> Json:
    """An `osp-expr` AST as plan JSON. An integer literal beyond ±(2^53 − 1) is written as
    decimal text, because a browser's JSON parser would round it to a double."""
    return _safe_ints(expr.model_dump(mode="json", by_alias=True))


def seed_node(assign_node_id: str, variable_id: str) -> str:
    """The `node_id` for the seeded draw of one assigned variable: `<assign node>/<variable>`.

    semantics.md §7 (C2-5, R1-2): one independent stream per variable. The server
    (`RuntimeConfig.seedNode`) and the browser engine (plan `variables[id].seedNode`) both
    take it from here, so they draw the same level.
    """
    return f"{assign_node_id}/{variable_id}"


def runtime_config(plan: Json, *, save_mode: str | None = None) -> Json:
    """The `RuntimeConfig` JSON (`osp_runtime.config`) the session service needs beside the
    plan: survey-version string, save mode, resume expiry, one `simple` assignment per
    assigned variable (with its `seedNode`) and one entry per `quotaCheck` node.

    osp-survey/0.1 models neither balanced allocation nor weights, so every assignment is
    `simple` with equal weights. The save mode and resume expiry come from the survey's
    settings (semantics.md §5); `save_mode` overrides the save mode if given.
    """
    quotas = []

    def walk(nodes: list[Json]) -> None:
        for n in nodes:
            if n["type"] == "quotaCheck":
                q = plan["quotas"].get(n["quota"], {})
                quotas.append({"node": n["id"], "quota": n["quota"], "limit": q.get("limit", 0)})
            elif n["type"] == "branch":
                walk(n["then"])
                walk(n["else"])
            elif n["type"] == "randomiser":
                walk(n["children"])

    walk(plan["flow"])
    assignments = [
        {
            "variable": v["id"],
            "levels": list(v["levels"]),
            "method": "simple",
            "seedNode": v["seedNode"],
        }
        for v in plan["variables"].values()
        if v["kind"] == "assigned"
    ]
    settings = plan.get("settings", {})
    return {
        "surveyVersion": plan["survey"]["seedVersion"],
        "saveMode": save_mode or settings.get("saveMode", "every-page"),
        "resumeExpiryDays": settings.get("resumeExpiryDays", 30),
        "assignments": assignments,
        "quotas": quotas,
    }


def seed_version(survey: Survey) -> str:
    """The `surveyVersion` string fed to `node_seed` (semantics.md §7, R1-1): the published
    version number as decimal text, or `"draft"` for an unpublished survey (preview, tests).
    """
    return str(survey.version) if survey.version is not None else "draft"


# --- Text ------------------------------------------------------------------------------


def segments(text: str) -> list[Segment]:
    """Split one string at `${...}` pipes. Invalid pipes stay literal text."""
    out: list[Segment] = []
    pos = 0
    for m in _PIPE.finditer(text):
        inner = m.group(1).strip()
        if not (_IDENT.match(inner) or _BUILTIN.match(inner)):
            continue
        if m.start() > pos:
            out.append(text[pos : m.start()])
        out.append({"pipe": inner})
        pos = m.end()
    if pos < len(text):
        out.append(text[pos:])
    return out


class _Compiler:
    def __init__(self, survey: Survey) -> None:
        self.s = survey
        md = survey.metadata
        self.languages = list(md.languages)
        self.default = md.defaultLanguage or md.languages[0]
        self.lists = {cl.id: cl.choices for cl in survey.choiceLists}
        self.items: dict[str, Json] = {}
        self.pages: dict[str, Json] = {}
        self.blocks: dict[str, Json] = {}
        self.questions: list[str] = []
        self.seed_nodes: dict[str, str] = {}

    def text(self, text: str | dict[str, str] | None) -> Json:
        """Translatable text → `{language: segments}` for every survey language.

        A missing translation falls back to the default language, then to any language
        (osp-spec reports missing translations; the plan never has holes).
        """
        if text is None:
            return None
        if isinstance(text, str):
            return {lang: segments(text) for lang in self.languages}
        fallback = text.get(self.default)
        if fallback is None:
            fallback = next(iter(text.values()), "")
        return {lang: segments(text.get(lang, fallback)) for lang in self.languages}

    @staticmethod
    def expr(e: Any) -> Json:
        return None if e is None else expr_json(e)

    def choices(self, choices: list[Choice]) -> list[Json]:
        return [{"value": c.value, "label": self.text(c.label)} for c in choices]

    # -- items, pages, blocks ---------------------------------------------------------

    def item(self, q: Any, page_id: str) -> Json:
        out: dict[str, Json] = {"id": q.id, "type": q.type, "page": page_id}
        out["label"] = self.text(q.label)
        if q.help is not None:
            out["help"] = self.text(q.help)
        if q.showIf is not None:
            out["showIf"] = self.expr(q.showIf)
        if isinstance(q, NoteQuestion):
            return out
        out["name"] = q.name or q.id
        out["required"] = q.required
        if isinstance(q, MatrixQuestion):
            out["rows"] = [matrix_row_id(q.id, r.id) for r in q.rows]
            out["choices"] = self.choices(self.columns(q))
            return out
        if q.constraint is not None:
            out["constraint"] = self.expr(q.constraint)
        if q.constraintMessage is not None:
            out["constraintMessage"] = self.text(q.constraintMessage)
        if isinstance(q, SliderQuestion):
            out["valueType"] = q.valueType
            out["step"] = q.step
            for key in ("minLabel", "maxLabel"):
                text = getattr(q, key)
                if text is not None:
                    out[key] = self.text(text)
        for key in ("min", "max"):
            bound = getattr(q, key, None)
            if bound is not None:
                out[key] = bound  # an int, or decimal text
        if isinstance(q, SingleQuestion | MultiQuestion):
            source = q.choices if q.choices is not None else self.lists.get(q.choiceList or "")
            out["choices"] = self.choices(source or [])
            out["choiceOrder"] = q.choiceOrder
        return out

    def columns(self, q: MatrixQuestion) -> list[Choice]:
        source = q.choices if q.choices is not None else self.lists.get(q.choiceList or "")
        return source or []

    def rows(self, q: MatrixQuestion, page_id: str) -> list[Json]:
        """One `single` item per matrix row (C2c-1)."""
        choices = self.choices(self.columns(q))
        return [
            {
                "id": matrix_row_id(q.id, r.id),
                "type": "single",
                "page": page_id,
                "label": self.text(r.label),
                "name": matrix_row_name(q, r.id),
                "required": matrix_row_required(q, r),
                "choices": choices,
                "choiceOrder": "fixed",
                "matrix": q.id,
            }
            for r in q.rows
        ]

    def block(self, block_id: str) -> list[str]:
        """Page ids of a block, compiling the block on first use."""
        if block_id in self.blocks:
            return self.blocks[block_id]["pages"]
        block = next((b for b in self.s.blocks if b.id == block_id), None)
        page_ids: list[str] = []
        if block is not None:
            for page in block.pages:
                page_ids.append(page.id)
                for q in page.items:
                    self.items[q.id] = self.item(q, page.id)
                    if isinstance(q, MatrixQuestion):
                        for row in self.rows(q, page.id):
                            self.items[row["id"]] = row
                            self.questions.append(row["id"])
                    elif not isinstance(q, NoteQuestion):
                        self.questions.append(q.id)
                self.pages[page.id] = {
                    "id": page.id,
                    "block": block_id,
                    "items": [q.id for q in page.items],
                    "itemOrder": page.itemOrder,
                }
                if page.showIf is not None:
                    self.pages[page.id]["showIf"] = self.expr(page.showIf)
        self.blocks[block_id] = {"id": block_id, "pages": page_ids}
        return page_ids

    # -- flow -------------------------------------------------------------------------

    def node(self, n: FlowNode) -> Json:
        match n:
            case BlockNode():
                return {"type": "block", "id": n.id, "block": n.block, "pages": self.block(n.block)}
            case BranchNode():
                return {
                    "type": "branch",
                    "id": n.id,
                    "if": self.expr(n.if_),
                    "then": [self.node(c) for c in n.then],
                    "else": [self.node(c) for c in n.else_],
                }
            case RandomiserNode():
                out = {"type": "randomiser", "id": n.id}
                out["children"] = [self.node(c) for c in n.children]
                out["pick"] = n.pick
                return out
            case AssignNode():
                for var in n.variables:
                    self.seed_nodes.setdefault(var, seed_node(n.id, var))
                return {"type": "assign", "id": n.id, "variables": list(n.variables)}
            case QuotaCheckNode():
                return {"type": "quotaCheck", "id": n.id, "quota": n.quota}
            case EndNode():
                out = {"type": "end", "id": n.id, "outcome": n.outcome}
                if n.message is not None:
                    out["message"] = self.text(n.message)
                return out
        raise AssertionError(f"unknown flow node {type(n).__name__}")  # pragma: no cover

    def variable(self, v: Any) -> Json:
        out: dict[str, Json] = {"id": v.id, "kind": v.kind, "name": v.name or v.id}
        match v:
            case EmbeddedVariable():
                out |= {"valueType": v.valueType, "source": v.source, "param": v.param}
                out["default"] = v.default
            case AssignedVariable():
                out["levels"] = list(v.levels)
                out["seedNode"] = self.seed_nodes.get(v.id, v.id)
            case ComputedVariable():
                out["expr"] = self.expr(v.expr)
        return out

    def run(self) -> Json:
        s = self.s
        flow = [self.node(n) for n in s.flow]
        quotas: dict[str, Json] = {}
        for q in s.quotas:
            on_full: dict[str, Json] = {"outcome": q.onFull.outcome, "block": q.onFull.block}
            on_full["pages"] = self.block(q.onFull.block) if q.onFull.block else []
            quotas[q.id] = {
                "id": q.id,
                "when": self.expr(q.when),
                "limit": q.limit,
                "countOn": q.countOn,
                "onFull": on_full,
            }
        plan: dict[str, Json] = {
            "planVersion": PLAN_VERSION,
            "engineVersion": ENGINE_VERSION,
            "checksum": "",
            "survey": {
                "id": s.id,
                "version": s.version,
                "specVersion": s.specVersion,
                "seedVersion": seed_version(s),
            },
            "languages": self.languages,
            "defaultLanguage": self.default,
            "title": self.text(s.metadata.title),
            "settings": {
                "backNavigation": s.settings.backNavigation,
                "saveMode": s.settings.saveMode,
                "localCopy": s.settings.localCopy,
                "resumeExpiryDays": s.settings.resumeExpiryDays,
            },
            "items": self.items,
            "questions": self.questions,
            "pages": self.pages,
            "blocks": self.blocks,
            "variables": {v.id: self.variable(v) for v in s.variables},
            "quotas": quotas,
            "flow": flow,
        }
        plan["checksum"] = checksum(plan)
        return plan


def embed_theme(plan: Json, theme: Json) -> Json:
    """A copy of `plan` with `theme` (a validated `osp_spec.theme.Theme` as JSON) at
    `plan.theme` and the checksum recomputed. The caller resolves and guards the theme
    (publish: survey theme, else the lab default, else the "clean" preset; runtime-design
    §6a); the plan only carries it, so the participant page needs no second fetch."""
    out = {**plan, "theme": theme}
    out["checksum"] = checksum(out)
    return out


def compile_plan(survey: Survey) -> Json:
    """Compile a parsed survey. Raises `PlanError` if `osp_spec` reports errors."""
    diagnostics = parse(survey.model_dump(mode="json", by_alias=True))[1]
    if has_errors(diagnostics):
        raise PlanError([d for d in diagnostics if d.severity == "error"])
    return _Compiler(survey).run()


def compile_survey(data: Any) -> tuple[Json | None, list[Diagnostic]]:
    """Validate raw survey JSON and compile it. Never raises."""
    survey, diagnostics = parse(data)
    if survey is None or has_errors(diagnostics):
        return None, diagnostics
    try:
        return _Compiler(survey).run(), diagnostics
    except Exception as exc:  # never crash on input (AGENTS.md rule 3)
        from osp_spec.diagnostics import make

        return None, [*diagnostics, make("internal.error", "", f"plan: {type(exc).__name__}")]
