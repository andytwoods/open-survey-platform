"""Semantic validator. `validate(anything)` returns diagnostics and never raises.

Two stages:
1. Structure: pydantic parses the input into `Survey`. Failures become `schema.*`
   diagnostics with JSON pointers into the input, and stage 2 is skipped.
2. Semantics: ids, names, languages, choices, flow and references.

Reference ordering rule (planning/semantics.md §3, decision C2-1): number every question
in **flow order** (a depth-first walk of `flow`; `then` before `else`, randomiser children in
document order, pages and items in document order). An expression or piped label may only
refer to a question or `assigned` variable with a lower number than its own site, or to a
question on the **same page** (either direction):
- a question's `showIf`, `constraint` and texts sit at that question's number; only
  `constraint` may refer to the question itself; same-page `showIf` references must not
  form a cycle (`ref.cycle`);
- a page-level `showIf` sits just before the page's first item, so it may refer only to
  earlier pages;
- a branch `if`, a quota checked by a `quotaCheck`, and an `end` message sit just after
  everything earlier in the walk;
- an `assigned` variable is numbered at its `assign` node, an `embedded` one is available
  from the start, and a `computed` one counts as late as its latest input.
Earlier-but-not-guaranteed targets (another child of the same randomiser, the other arm of
a branch) are warnings: the reference is legal but often `null` (semantics.md §3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date as _date
from decimal import Decimal, InvalidOperation
from typing import Any

from osp_expr.ast import KEYWORDS
from pydantic import ValidationError

from . import expr as ex
from .diagnostics import Diagnostic, make, pointer
from .model import (
    SPEC_VERSION,
    AssignedVariable,
    AssignNode,
    BlockNode,
    BranchNode,
    Choice,
    ComputedVariable,
    DecimalQuestion,
    EmbeddedVariable,
    EndNode,
    FlowNode,
    IntegerQuestion,
    MultiQuestion,
    NoteQuestion,
    Question,
    QuotaCheckNode,
    RandomiserNode,
    SingleQuestion,
    Survey,
    Text,
)
from .reserved import reserved_reason

try:
    from osp_expr.values import canonical_decimal as _canonical_decimal
except ImportError:  # pragma: no cover
    _canonical_decimal = None

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PIPE = re.compile(r"\$\{([^}]*)\}")
# Built-in `$` variables usable in piping (semantics.md §8, R6-3; runtime-design §7a).
BUILTIN_PIPES = frozenset(
    {"$trial", "$position.index", "$position.of", "$pagesDone", "$language", "$device"}
)

# A path element: (kind, node id, arm). kind is "branch" | "randomiser" | "quota".
PathElem = tuple[str, str, int]


def validate(data: Any) -> list[Diagnostic]:
    """Diagnostics for any input (a parsed JSON value). Never raises."""
    return parse(data)[1]


def parse(data: Any) -> tuple[Survey | None, list[Diagnostic]]:
    """The parsed survey (None if structurally invalid) and its diagnostics. Never raises."""
    try:
        return _parse(data)
    except Exception as exc:  # never crash on input (AGENTS.md rule 3)
        return None, [make("internal.error", "", f"validator failed: {type(exc).__name__}")]


def _parse(data: Any) -> tuple[Survey | None, list[Diagnostic]]:
    if isinstance(data, dict) and "specVersion" in data:
        version = data["specVersion"]
        if isinstance(version, str) and version != SPEC_VERSION:
            msg = f"unsupported specVersion {version[:40]!r}; expected {SPEC_VERSION!r}"
            return None, [make("spec.unsupported_version", "/specVersion", msg)]
    try:
        survey = Survey.model_validate(data)
    except ValidationError as err:
        return None, _schema_diagnostics(err, data)
    return survey, _Checker(survey).run()


# --- Stage 1: pydantic errors -> diagnostics -------------------------------------------

_TYPE_CODES = {
    "missing": "schema.missing",
    "union_tag_not_found": "schema.missing",
    "extra_forbidden": "schema.extra",
    "literal_error": "schema.enum",
    "union_tag_invalid": "schema.enum",
    "string_pattern_mismatch": "schema.pattern",
}


def _schema_code(kind: str) -> str:
    if kind in _TYPE_CODES:
        return _TYPE_CODES[kind]
    if kind.endswith("_type") or kind in ("model_attributes_type", "is_instance_of"):
        return "schema.type"
    return "schema.value"


def _schema_diagnostics(err: ValidationError, data: Any) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    seen: set[tuple[str, str]] = set()
    for e in err.errors(include_url=False, include_input=False):
        kind = e["type"]
        code = _schema_code(kind)
        parts = _loc_to_parts(e["loc"], data, keep_last=kind in ("missing", "extra_forbidden"))
        if kind in ("union_tag_not_found", "union_tag_invalid"):
            disc = str((e.get("ctx") or {}).get("discriminator", "type")).strip("'\"")
            parts.append(disc)
        ptr = pointer(*parts)
        if (code, ptr) in seen:
            continue
        seen.add((code, ptr))
        out.append(make(code, ptr, str(e["msg"])))
    return out


def _loc_to_parts(loc: tuple[Any, ...], data: Any, *, keep_last: bool) -> list[str | int]:
    """Map a pydantic `loc` onto the input, dropping union tags and member labels."""
    parts: list[str | int] = []
    cur = data
    for i, elem in enumerate(loc):
        last = i == len(loc) - 1
        if isinstance(cur, dict):
            if elem in (cur.get("type"), cur.get("kind")) and not (last and elem in cur):
                continue  # discriminated-union tag
            if isinstance(elem, str) and elem in cur:
                parts.append(elem)
                cur = cur[elem]
                continue
        elif isinstance(cur, list) and isinstance(elem, int) and 0 <= elem < len(cur):
            parts.append(elem)
            cur = cur[elem]
            continue
        if last and keep_last and isinstance(elem, (str, int)):
            parts.append(elem)
        # anything else is a union member label such as "str" or "dict[...]"
    return parts


# --- Stage 2: semantic checks ----------------------------------------------------------


@dataclass
class _QInfo:
    q: Question
    ptr: str
    page: str = ""
    pos: int | None = None
    path: tuple[PathElem, ...] = ()


@dataclass
class _VInfo:
    v: EmbeddedVariable | AssignedVariable | ComputedVariable
    ptr: str
    pos: int | None = None  # assigned: position of its assign node
    path: tuple[PathElem, ...] = ()


@dataclass
class _Site:
    """Where an expression or piped text sits, for reference checks."""

    ptr: str
    refs: list[str]
    pos: int | None  # None: no ordering check
    path: tuple[PathElem, ...] = ()
    self_id: str | None = None
    allow_self: bool = False
    page: str | None = None  # same-page references are allowed in either direction


@dataclass
class _Checker:
    s: Survey
    out: list[Diagnostic] = field(default_factory=list)
    questions: dict[str, _QInfo] = field(default_factory=dict)
    variables: dict[str, _VInfo] = field(default_factory=dict)
    blocks: dict[str, int] = field(default_factory=dict)
    choice_lists: dict[str, int] = field(default_factory=dict)
    quotas: dict[str, int] = field(default_factory=dict)
    placed_blocks: set[str] = field(default_factory=set)
    used_lists: set[str] = field(default_factory=set)
    used_quotas: set[str] = field(default_factory=set)
    sites: list[_Site] = field(default_factory=list)
    code_sites: list[tuple[ex.Expression, str]] = field(default_factory=list)
    counter: int = 0
    _cpos: dict[str, int | None] = field(default_factory=dict)
    _env: dict[str, str] | None = None

    def emit(self, code: str, ptr: str, message: str) -> None:
        self.out.append(make(code, ptr, message))

    def run(self) -> list[Diagnostic]:
        self._index()
        self._languages()
        self._names()
        self._choices()
        self._variables()
        self._quotas_static()
        self._flow()
        self._unplaced()
        self._computed_cycles()
        self._references()
        self._same_page_cycles()
        self._settings()
        self._consent()
        self._choice_codes()
        unique: dict[tuple[str, str, str], Diagnostic] = {}
        for d in self.out:
            unique.setdefault((d.code, d.pointer, d.message), d)
        return list(unique.values())

    # -- index and identity ---------------------------------------------------------

    def _index(self) -> None:
        seen: set[str] = set()

        def claim(id_: str, ptr: str) -> bool:
            if id_ in seen:
                self.emit("id.duplicate", ptr + "/id", f"id '{id_}' is already used")
                return False
            seen.add(id_)
            if id_ in KEYWORDS:
                self.emit(
                    "id.reserved",
                    ptr + "/id",
                    f"'{id_}' is an expression keyword, so conditions could not refer to it",
                )
            return True

        for i, cl in enumerate(self.s.choiceLists):
            if claim(cl.id, pointer("choiceLists", i)):
                self.choice_lists[cl.id] = i
        for i, b in enumerate(self.s.blocks):
            bp = pointer("blocks", i)
            if claim(b.id, bp):
                self.blocks[b.id] = i
            for j, page in enumerate(b.pages):
                pp = bp + pointer("pages", j)
                claim(page.id, pp)
                for k, q in enumerate(page.items):
                    qp = pp + pointer("items", k)
                    if claim(q.id, qp):
                        self.questions[q.id] = _QInfo(q, qp, page.id)
        for i, v in enumerate(self.s.variables):
            vp = pointer("variables", i)
            if claim(v.id, vp):
                self.variables[v.id] = _VInfo(v, vp)
        for i, quota in enumerate(self.s.quotas):
            if claim(quota.id, pointer("quotas", i)):
                self.quotas[quota.id] = i

        def nodes(ns: list[FlowNode], ptr: str) -> None:
            for i, n in enumerate(ns):
                np = ptr + pointer(i)
                claim(n.id, np)
                if isinstance(n, BranchNode):
                    nodes(n.then, np + "/then")
                    nodes(n.else_, np + "/else")
                elif isinstance(n, RandomiserNode):
                    nodes(n.children, np + "/children")

        nodes(self.s.flow, "/flow")

    def _names(self) -> None:
        named: list[tuple[str, str]] = []  # (name, pointer to name or id)
        for info in self.questions.values():
            if not isinstance(info.q, NoteQuestion):
                explicit = info.q.name is not None
                named.append(
                    (info.q.name or info.q.id, info.ptr + ("/name" if explicit else "/id"))
                )
        for vi in self.variables.values():
            explicit = vi.v.name is not None
            named.append((vi.v.name or vi.v.id, vi.ptr + ("/name" if explicit else "/id")))
        exact: dict[str, str] = {}
        folded: dict[str, str] = {}
        for name, ptr in named:
            reason = reserved_reason(name)
            if reason:
                self.emit("name.reserved", ptr, f"variable name '{name}' is reserved: {reason}")
            if name in exact:
                self.emit("name.duplicate", ptr, f"variable name '{name}' is already used")
            elif name.lower() in folded:
                other = folded[name.lower()]
                self.emit(
                    "name.case_collision",
                    ptr,
                    f"variable name '{name}' differs from '{other}' only in case; "
                    "SPSS, Stata and LimeSurvey would treat them as one variable",
                )
            exact.setdefault(name, ptr)
            folded.setdefault(name.lower(), name)

    def _languages(self) -> None:
        md = self.s.metadata
        seen: set[str] = set()
        for i, lang in enumerate(md.languages):
            if lang in seen:
                self.emit("lang.duplicate", pointer("metadata", "languages", i), f"'{lang}' twice")
            seen.add(lang)
        if md.defaultLanguage is not None and md.defaultLanguage not in seen:
            self.emit(
                "lang.unknown_default",
                "/metadata/defaultLanguage",
                f"defaultLanguage '{md.defaultLanguage}' is not in metadata.languages",
            )
        self._text(md.title, "/metadata/title", None)
        if md.description is not None:
            self._text(md.description, "/metadata/description", None)

    # -- text and piping ------------------------------------------------------------

    def _text(self, text: Text, ptr: str, site: _Site | None) -> None:
        langs = self.s.metadata.languages
        strings: list[tuple[str, str]]
        if isinstance(text, str):
            strings = [(text, ptr)]
        else:
            strings = [(v, ptr + pointer(k)) for k, v in text.items()]
            for k in text:
                if k not in langs:
                    self.emit(
                        "text.unknown_language",
                        ptr + pointer(k),
                        f"language '{k}' is not in metadata.languages",
                    )
            missing = [lang for lang in langs if lang not in text]
            if missing:
                self.emit("text.missing_translation", ptr, f"no text for: {', '.join(missing)}")
        for s, sp in strings:
            refs: list[str] = []
            for m in _PIPE.finditer(s):
                inner = m.group(1).strip()
                if _IDENT.match(inner):
                    refs.append(inner)
                elif inner in BUILTIN_PIPES:
                    continue  # filled by the engine; always available
                else:
                    self.emit("pipe.invalid", sp, f"'${{{m.group(1)}}}' is not a valid reference")
            if refs:
                base = site or _Site(sp, [], None)
                self.sites.append(
                    _Site(sp, refs, base.pos, base.path, base.self_id, False, base.page)
                )

    # -- choices --------------------------------------------------------------------

    def _choices(self) -> None:
        for i, cl in enumerate(self.s.choiceLists):
            self._choice_items(cl.choices, pointer("choiceLists", i, "choices"), None)
        for info in self.questions.values():
            q = info.q
            if not isinstance(q, (SingleQuestion, MultiQuestion)):
                continue
            if (q.choiceList is None) == (q.choices is None):
                self.emit(
                    "choice.source",
                    info.ptr,
                    f"question '{q.id}' needs exactly one of 'choiceList' or 'choices'",
                )
            if q.choiceList is not None:
                self.used_lists.add(q.choiceList)
                if q.choiceList not in self.choice_lists:
                    self.emit(
                        "ref.unknown_choice_list",
                        info.ptr + "/choiceList",
                        f"no choice list with id '{q.choiceList}'",
                    )
        for cid, i in self.choice_lists.items():
            if cid not in self.used_lists:
                self.emit("choicelist.unused", pointer("choiceLists", i), f"'{cid}' is unused")

    def _choice_items(self, choices: list[Choice], ptr: str, site: _Site | None) -> None:
        seen: set[str] = set()
        for k, c in enumerate(choices):
            cp = ptr + pointer(k)
            key = str(c.value)
            if isinstance(c.value, str) and (not c.value or any(ch.isspace() for ch in c.value)):
                self.emit(
                    "choice.invalid_value",
                    cp + "/value",
                    "choice codes must be non-empty and contain no whitespace "
                    "(XForms stores multi answers space-separated)",
                )
            if key in seen:
                self.emit("choice.duplicate_value", cp + "/value", f"code {key!r} is repeated")
            seen.add(key)
            self._text(c.label, cp + "/label", site)
        if len({type(c.value) for c in choices}) > 1:
            self.emit("choice.mixed_types", ptr, "list mixes integer and text codes")

    # -- variables and quotas -------------------------------------------------------

    def _variables(self) -> None:
        for vi in self.variables.values():
            v = vi.v
            if isinstance(v, AssignedVariable):
                seen: set[str] = set()
                for k, level in enumerate(v.levels):
                    if str(level) in seen:
                        self.emit(
                            "variable.duplicate_level",
                            vi.ptr + pointer("levels", k),
                            f"level {level!r} is repeated",
                        )
                    seen.add(str(level))
            elif isinstance(v, EmbeddedVariable) and v.default is not None:
                if not _default_fits(v.valueType, v.default):
                    self.emit(
                        "variable.default_type",
                        vi.ptr + "/default",
                        f"default {v.default!r} is not a valid {v.valueType}",
                    )

    def _quotas_static(self) -> None:
        for i, quota in enumerate(self.s.quotas):
            blk = quota.onFull.block
            if blk is not None and blk not in self.blocks:
                self.emit(
                    "ref.unknown_block",
                    pointer("quotas", i, "onFull", "block"),
                    f"no block with id '{blk}'",
                )

    # -- flow -----------------------------------------------------------------------

    def _flow(self) -> None:
        if not self.s.flow:
            self.emit("flow.empty", "/flow", "flow is empty; no block will be shown")
        self._walk(self.s.flow, "/flow", ())
        for bid, i in self.blocks.items():
            if bid not in self.placed_blocks:
                self.emit("block.unused", pointer("blocks", i), f"block '{bid}' is not in flow")
        for qid, i in self.quotas.items():
            if qid not in self.used_quotas:
                self.emit("quota.unused", pointer("quotas", i), f"quota '{qid}' is never checked")
                when = self.s.quotas[i].when
                self.sites.append(_Site(pointer("quotas", i, "when"), ex.references(when), None))
        for vi in self.variables.values():
            if isinstance(vi.v, AssignedVariable) and vi.pos is None:
                self.emit(
                    "variable.never_assigned",
                    vi.ptr,
                    f"no assign node sets '{vi.v.id}'; it will always be null",
                )

    def _walk(self, nodes: list[FlowNode], ptr: str, path: tuple[PathElem, ...]) -> bool:
        """Walk a node list; return True if it always ends the session."""
        terminated = False
        flagged = False
        for i, node in enumerate(nodes):
            np = ptr + pointer(i)
            if terminated and not flagged:
                self.emit("flow.unreachable", np, "an earlier node always ends the survey")
                flagged = True
            terminated = self._node(node, np, path) or terminated
        return terminated

    def _node(self, node: FlowNode, ptr: str, path: tuple[PathElem, ...]) -> bool:
        if isinstance(node, BlockNode):
            self._place_block(node.block, ptr + "/block", path)
            return False
        if isinstance(node, BranchNode):
            self._expr_site(node.if_, ptr + "/if", self.counter, path, boolean=True)
            if not node.then:
                self.emit("flow.empty_branch", ptr + "/then", "branch has no 'then' nodes")
            t = self._walk(node.then, ptr + "/then", (*path, ("branch", node.id, 0)))
            e = self._walk(node.else_, ptr + "/else", (*path, ("branch", node.id, 1)))
            return t and e and bool(node.else_)
        if isinstance(node, RandomiserNode):
            if node.pick is not None and node.pick > len(node.children):
                self.emit(
                    "flow.pick_too_large",
                    ptr + "/pick",
                    f"pick {node.pick} but only {len(node.children)} children",
                )
            ends = [
                self._node(c, ptr + pointer("children", k), (*path, ("randomiser", node.id, k)))
                for k, c in enumerate(node.children)
            ]
            return any(ends) if node.pick is None else all(ends)
        if isinstance(node, AssignNode):
            for k, vid in enumerate(node.variables):
                vp = ptr + pointer("variables", k)
                vi = self.variables.get(vid)
                if vi is None:
                    self.emit("ref.unknown_variable", vp, f"no variable with id '{vid}'")
                elif not isinstance(vi.v, AssignedVariable):
                    self.emit(
                        "flow.assign_wrong_kind",
                        vp,
                        f"'{vid}' is {vi.v.kind}; only 'assigned' variables can be assigned",
                    )
                elif vi.pos is not None:
                    self.emit("flow.variable_reassigned", vp, f"'{vid}' is already assigned")
                else:
                    vi.pos, vi.path = self.counter, path
                    self.counter += 1
            return False
        if isinstance(node, QuotaCheckNode):
            i = self.quotas.get(node.quota)
            if i is None:
                self.emit("ref.unknown_quota", ptr + "/quota", f"no quota '{node.quota}'")
                return False
            quota = self.s.quotas[i]
            first = node.quota not in self.used_quotas
            self.used_quotas.add(node.quota)
            self._expr_site(
                quota.when, pointer("quotas", i, "when"), self.counter, path, boolean=True
            )
            blk = quota.onFull.block
            if first and blk is not None and blk in self.blocks:
                self._place_block(
                    blk, pointer("quotas", i, "onFull", "block"), (*path, ("quota", node.id, 1))
                )
            return False
        assert isinstance(node, EndNode)
        if node.message is not None:
            self._text(node.message, ptr + "/message", _Site(ptr, [], self.counter, path))
        return True

    def _place_block(self, bid: str, ptr: str, path: tuple[PathElem, ...]) -> None:
        if bid not in self.blocks:
            self.emit("ref.unknown_block", ptr, f"no block with id '{bid}'")
            return
        if bid in self.placed_blocks:
            self.emit(
                "flow.block_reused",
                ptr,
                f"block '{bid}' is already in the flow; a block may appear once",
            )
            return
        self.placed_blocks.add(bid)
        bp = pointer("blocks", self.blocks[bid])
        for j, page in enumerate(self.s.blocks[self.blocks[bid]].pages):
            pp = bp + pointer("pages", j)
            if page.title is not None:
                # A page title sits before the page's first item: it may pipe earlier pages.
                self._text(page.title, pp + "/title", _Site(pp, [], self.counter, path))
            if page.showIf is not None:
                # So does a page-level showIf: it may refer only to earlier pages.
                self._expr_site(page.showIf, pp + "/showIf", self.counter, path, boolean=True)
            for q in page.items:
                info = self.questions.get(q.id)
                if info is None or info.q is not q:
                    continue  # duplicate id, already reported
                info.pos, info.path = self.counter, path
                self.counter += 1
                self._question_sites(info)

    def _unplaced(self) -> None:
        for bid, i in self.blocks.items():
            if bid in self.placed_blocks:
                continue
            for j, page in enumerate(self.s.blocks[i].pages):
                if page.title is not None:
                    self._text(page.title, pointer("blocks", i, "pages", j, "title"), None)
                if page.showIf is not None:
                    pp = pointer("blocks", i, "pages", j, "showIf")
                    self._expr_site(page.showIf, pp, None, (), boolean=True)
        for info in self.questions.values():
            if info.pos is None:
                self._question_sites(info)

    def _question_sites(self, info: _QInfo) -> None:
        q = info.q
        site = _Site(info.ptr, [], info.pos, info.path, q.id, page=info.page)
        if q.showIf is not None:
            self._expr_site(
                q.showIf, info.ptr + "/showIf", info.pos, info.path, True, q.id, page=info.page
            )
        if not isinstance(q, NoteQuestion) and q.constraint is not None:
            self._expr_site(
                q.constraint,
                info.ptr + "/constraint",
                info.pos,
                info.path,
                True,
                q.id,
                True,
                info.page,
            )
        if isinstance(q, (IntegerQuestion, DecimalQuestion)):
            self._bounds(q, info.ptr)
        self._text(q.label, info.ptr + "/label", site)
        if q.help is not None:
            self._text(q.help, info.ptr + "/help", site)
        if not isinstance(q, NoteQuestion) and q.constraintMessage is not None:
            self._text(q.constraintMessage, info.ptr + "/constraintMessage", site)
        if isinstance(q, (SingleQuestion, MultiQuestion)) and q.choices is not None:
            self._choice_items(q.choices, info.ptr + "/choices", site)

    def _expr_site(
        self,
        e: ex.Expression,
        ptr: str,
        pos: int | None,
        path: tuple[PathElem, ...],
        boolean: bool,
        self_id: str | None = None,
        allow_self: bool = False,
        page: str | None = None,
    ) -> None:
        self.sites.append(_Site(ptr, ex.references(e), pos, path, self_id, allow_self, page))
        self._typecheck(e, ptr, boolean)
        self.code_sites.append((e, ptr))

    def _typecheck(self, e: ex.Expression, ptr: str, boolean: bool) -> None:
        for suffix, message in ex.typecheck(e, self._type_env(), boolean=boolean):
            self.emit("expr.type", ptr + suffix, message)

    def _type_env(self) -> dict[str, str]:
        """Value types by id. Notes (no value) and computed variables (type not declared)
        are left out, so the type checker treats them as unknown."""
        if self._env is None:
            env = {
                qid: i.q.type
                for qid, i in self.questions.items()
                if not isinstance(i.q, NoteQuestion)
            }
            for vid, vi in self.variables.items():
                if isinstance(vi.v, EmbeddedVariable):
                    env[vid] = vi.v.valueType
                elif isinstance(vi.v, AssignedVariable):
                    env[vid] = "single"  # a level is a code, like a single-choice answer
            self._env = env
        return self._env

    # -- computed variables and references ------------------------------------------

    def _choice_codes(self) -> None:
        """`ref.unknown_choice_code`: a condition compares a single/multi question (or an
        `assigned` variable) with a literal code that is not one of its choices (levels).
        Such a test is always false. Codes match as text (semantics.md C2-8: 1 == "1")."""
        for e, ptr in self.code_sites:
            for suffix, ref, code in ex.code_tests(e):
                codes = self._codes_of(ref)
                if codes is not None and str(code) not in codes:
                    self.emit(
                        "ref.unknown_choice_code",
                        ptr + suffix,
                        f"{code!r} is not a choice code of '{ref}' "
                        f"(codes: {', '.join(sorted(codes))}); the test is always false",
                    )

    def _codes_of(self, ref: str) -> set[str] | None:
        """The codes `ref` can take as text, or None if it is not a choice-like id."""
        info = self.questions.get(ref)
        if info is not None:
            q = info.q
            if not isinstance(q, (SingleQuestion, MultiQuestion)):
                return None
            choices = q.choices
            if choices is None and q.choiceList is not None:
                i = self.choice_lists.get(q.choiceList)
                choices = self.s.choiceLists[i].choices if i is not None else None
            return None if choices is None else {str(c.value) for c in choices}
        vi = self.variables.get(ref)
        if vi is not None and isinstance(vi.v, AssignedVariable):
            return {str(level) for level in vi.v.levels}
        return None

    def _computed_cycles(self) -> None:
        state: dict[str, int] = {}  # 1 visiting, 2 done

        def visit(vid: str) -> None:
            state[vid] = 1
            vi = self.variables[vid]
            assert isinstance(vi.v, ComputedVariable)
            for ref in ex.references(vi.v.expr):
                target = self.variables.get(ref)
                if target is None or not isinstance(target.v, ComputedVariable):
                    continue
                if state.get(ref) == 1:
                    self.emit(
                        "variable.cycle",
                        vi.ptr + "/expr",
                        f"computed variable '{vid}' depends on itself via '{ref}'",
                    )
                    self._cpos[vid] = None
                elif ref not in state:
                    visit(ref)
            state[vid] = 2

        for vid, vi in self.variables.items():
            if isinstance(vi.v, ComputedVariable) and vid not in state:
                visit(vid)
            if isinstance(vi.v, ComputedVariable):
                self.sites.append(_Site(vi.ptr + "/expr", ex.references(vi.v.expr), None))
                self._typecheck(vi.v.expr, vi.ptr + "/expr", boolean=False)
                self.code_sites.append((vi.v.expr, vi.ptr + "/expr"))

    def _computed_pos(self, vid: str, stack: frozenset[str] = frozenset()) -> int | None:
        """How late a computed variable is available: its latest input (-1: from start)."""
        if vid in self._cpos:
            return self._cpos[vid]
        vi = self.variables[vid]
        assert isinstance(vi.v, ComputedVariable)
        latest = -1
        for ref in ex.references(vi.v.expr):
            t = self._target_pos(ref, stack | {vid})
            if t is None:
                continue
            latest = max(latest, t)
        self._cpos[vid] = latest
        return latest

    def _target_pos(self, ref: str, stack: frozenset[str]) -> int | None:
        if ref in self.questions:
            return self.questions[ref].pos
        vi = self.variables.get(ref)
        if vi is None:
            return None
        if isinstance(vi.v, EmbeddedVariable):
            return -1
        if isinstance(vi.v, AssignedVariable):
            return vi.pos
        if ref in stack:
            return None  # cycle, reported separately
        return self._computed_pos(ref, stack)

    def _references(self) -> None:
        for site in self.sites:
            for ref in site.refs:
                self._check_ref(site, ref)

    def _check_ref(self, site: _Site, ref: str) -> None:
        tpath: tuple[PathElem, ...] | None = None
        if ref in self.questions:
            info = self.questions[ref]
            if isinstance(info.q, NoteQuestion):
                self.emit("ref.no_value", site.ptr, f"'{ref}' is a note and has no value")
                return
            if info.pos is None:
                self.emit(
                    "ref.not_in_flow", site.ptr, f"'{ref}' is in a block that is not in the flow"
                )
                return
            t: int | None = info.pos
            tpath = info.path
        elif ref in self.variables:
            vi = self.variables[ref]
            if isinstance(vi.v, EmbeddedVariable):
                return
            if isinstance(vi.v, AssignedVariable):
                t, tpath = vi.pos, vi.path
            else:
                t = self._computed_pos(ref)
        else:
            self.emit("ref.unknown", site.ptr, f"'{ref}' is not a question or variable id")
            return
        if ref == site.self_id:
            if not site.allow_self:
                self.emit("ref.self", site.ptr, f"'{ref}' refers to itself")
            return
        if site.pos is None or t is None:
            return
        if t >= site.pos:
            if site.page is not None and self._same_page_only(ref, site):
                return  # C2-1: same-page references go either way (cycles: _same_page_cycles)
            self.emit("ref.forward", site.ptr, f"'{ref}' comes later in the flow")
            return
        if tpath is None:
            return
        for a, b in zip(site.path, tpath, strict=False):
            if a == b:
                continue
            if a[:2] == b[:2]:
                if a[0] == "randomiser":
                    self.emit(
                        "ref.randomised_sibling",
                        site.ptr,
                        f"'{ref}' is in another child of randomiser '{a[1]}'; "
                        "it may not have been shown yet",
                    )
                else:
                    self.emit(
                        "ref.other_branch",
                        site.ptr,
                        f"'{ref}' is in the other arm of branch '{a[1]}'; it is never reached "
                        "on this path",
                    )
            return


def _question_inputs(checker: _Checker, ref: str, seen: frozenset[str] = frozenset()) -> set[str]:
    """Question ids `ref` reads: itself, or a computed variable's inputs (transitively)."""
    if ref in checker.questions:
        return {ref}
    vi = checker.variables.get(ref)
    if vi is None or not isinstance(vi.v, ComputedVariable) or ref in seen:
        return set()
    out: set[str] = set()
    for r in ex.references(vi.v.expr):
        out |= _question_inputs(checker, r, seen | {ref})
    return out


def _same_page_only(self: _Checker, ref: str, site: _Site) -> bool:
    """Every question `ref` reads at or after the site is on the site's page."""
    for qid in _question_inputs(self, ref):
        info = self.questions[qid]
        if info.pos is not None and site.pos is not None and info.pos >= site.pos:
            if info.page != site.page:
                return False
    vi = self.variables.get(ref)
    if vi is not None and isinstance(vi.v, AssignedVariable):
        return False  # an assigned variable is never on a page
    return True


def _same_page_cycles(self: _Checker) -> None:
    """`ref.cycle`: questions on one page whose `showIf`s depend on each other in a loop
    (each one's relevance needs the other's value). Constraints and piping cannot loop."""
    edges: dict[str, set[str]] = {}
    for qid, info in self.questions.items():
        if info.q.showIf is None:
            continue
        deps: set[str] = set()
        for r in ex.references(info.q.showIf):
            deps |= {x for x in _question_inputs(self, r) if self.questions[x].page == info.page}
        deps.discard(qid)  # self-reference is ref.self
        edges[qid] = deps
    state: dict[str, int] = {}
    reported: set[str] = set()

    def visit(q: str, stack: list[str]) -> None:
        state[q] = 1
        stack.append(q)
        for nxt in sorted(edges.get(q, ())):
            if state.get(nxt) == 1:
                loop = stack[stack.index(nxt) :]
                if not reported & set(loop):
                    reported.update(loop)
                    info = self.questions[loop[0]]
                    self.emit(
                        "ref.cycle",
                        info.ptr + "/showIf",
                        "show-if conditions on one page depend on each other in a loop: "
                        + " -> ".join([*loop, loop[0]]),
                    )
            elif nxt not in state:
                visit(nxt, stack)
        stack.pop()
        state[q] = 2

    for q in sorted(edges):
        if q not in state:
            visit(q, [])


def _bounds(self: _Checker, q: IntegerQuestion | DecimalQuestion, ptr: str) -> None:
    """Numeric `min` / `max` (§4): readable, at most 28 significant figures, min <= max."""
    values: dict[str, Decimal] = {}
    for key in ("min", "max"):
        raw = getattr(q, key)
        if raw is None:
            continue
        text = _canonical_decimal(raw) if _canonical_decimal else str(raw)
        if text is None:
            self.emit("question.bounds", f"{ptr}/{key}", f"{key} {raw!r} is not a usable number")
            continue
        values[key] = Decimal(text)
    if "min" in values and "max" in values and values["min"] > values["max"]:
        self.emit("question.bounds", ptr + "/min", "min is greater than max")


def _settings(self: _Checker) -> None:
    r = self.s.settings.retention
    if r is None:
        return
    ptr = "/settings/retention"
    if r.kind == "days-after-close" and (r.days is None or r.until is not None):
        self.emit("settings.retention", ptr, "'days-after-close' needs 'days' (and no 'until')")
    elif r.kind == "after-date" and (r.until is None or r.days is not None):
        self.emit("settings.retention", ptr, "'after-date' needs 'until' (and no 'days')")
    elif r.kind == "indefinite" and (r.days is not None or r.until is not None):
        self.emit("settings.retention", ptr, "'indefinite' takes no 'days' or 'until'")
    if r.until is not None:
        try:
            _date.fromisoformat(r.until)
        except ValueError:
            self.emit("settings.retention", ptr + "/until", f"{r.until!r} is not a date")


def _consent(self: _Checker) -> None:
    """semantics.md §11: the consent page comes before the flow, so nothing can be piped
    into it, and declining must not look like a completed response."""
    c = self.s.consent
    if c is None:
        return
    for key in ("text", "agreeLabel", "declineLabel"):
        text = getattr(c, key)
        ptr = "/consent/" + key
        self._text(text, ptr, None)
        values = [text] if isinstance(text, str) else list(text.values())
        if any(_PIPE.search(v) for v in values):
            self.emit("consent.pipe", ptr, "the consent page is shown first: nothing can be piped")
    if c.declineOutcome == "complete":
        self.emit("consent.outcome", "/consent/declineOutcome", "a decline cannot end 'complete'")


_Checker._same_page_only = _same_page_only  # type: ignore[attr-defined]
_Checker._same_page_cycles = _same_page_cycles  # type: ignore[attr-defined]
_Checker._bounds = _bounds  # type: ignore[attr-defined]
_Checker._settings = _settings  # type: ignore[attr-defined]
_Checker._consent = _consent  # type: ignore[attr-defined]


def publish_diagnostics(data: Any) -> list[Diagnostic]:
    """Diagnostics that block **publishing** but not editing or previewing: everything
    `validate` reports, plus `publish.retention_required` when no retention policy is set
    (decided 16 Oct 2026: required before publishing, no silent default). Never raises."""
    survey, diagnostics = parse(data)
    if survey is not None and survey.settings.retention is None:
        diagnostics = [
            *diagnostics,
            make(
                "publish.retention_required",
                "/settings/retention",
                "choose how long participant data is kept before publishing",
            ),
        ]
    return diagnostics


def _default_fits(value_type: str, default: str | int) -> bool:
    if value_type == "text":
        return isinstance(default, str)
    if value_type == "integer":
        return isinstance(default, int)
    if isinstance(default, int):
        return True
    try:
        return Decimal(default).is_finite()
    except InvalidOperation:
        return False
