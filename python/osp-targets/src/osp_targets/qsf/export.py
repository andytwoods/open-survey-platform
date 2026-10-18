"""``osp-survey`` → Qualtrics ``.qsf`` (the JSON survey export Qualtrics imports).

Pipeline (planning/review.md §2.4): validate → walk the model for capability diagnostics
→ allocate export tags (renaming invalid and reserved names) and question ids (``QIDn``) →
write the blocks (pages are page breaks), the questions and the survey flow → serialise.
Every feature the capability table marks as non-native produces a diagnostic with a JSON
pointer; :func:`export_qsf` never raises.

Conditions become Qualtrics logic (display logic, branch logic): sets of conditions joined
by Or, each an And of conditions on one question, statement or embedded field. Our
condition is rewritten into that shape (``_Logic``); a condition that has none (arithmetic,
``if``, a comparison of two questions …) is reported as ``$logic.unmappable``.

Clean-room: written from the public Qualtrics documentation (survey flow, question types,
display logic, embedded data, piped text) and the shape of ``.qsf`` files as our own
importer (``imports/qsf.py``) reads them. No Qualtrics code.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from osp_expr.ast import (
    And,
    Answered,
    BoolLit,
    Compare,
    Contains,
    DecLit,
    Expr,
    IntLit,
    Not,
    Or,
    Ref,
    TextLit,
)
from osp_spec import Survey, is_rich, parse, redirect_templates
from osp_spec.hooks import DEFAULT_PARAM_PATTERN, placeholders
from osp_spec.model import (
    AssignedVariable,
    AssignNode,
    Block,
    BlockNode,
    BranchNode,
    Choice,
    DateQuestion,
    DecimalQuestion,
    EmbeddedVariable,
    EndNode,
    IntegerQuestion,
    MatrixQuestion,
    MultiQuestion,
    NoteQuestion,
    RandomiserNode,
    SingleQuestion,
    SliderQuestion,
    TextQuestion,
    matrix_row_id,
    matrix_row_name,
    matrix_row_required,
)
from pydantic import BaseModel

from ..capabilities.base import Capability
from ..diagnostics import SEVERITY_FOR_LEVEL, ExportDiagnostic, pointer
from ..lss.html import is_block_html, to_html
from ..richtext import as_json
from .capabilities import QSF

TARGET = "qsf"

# Response columns every Qualtrics export has (lower case): an export tag or embedded field
# with one of these names would clash with it in the data.
RESERVED_NAMES: frozenset[str] = frozenset(
    {
        "responseid",
        "startdate",
        "enddate",
        "status",
        "ipaddress",
        "progress",
        "duration",
        "finished",
        "recordeddate",
        "recipientlastname",
        "recipientfirstname",
        "recipientemail",
        "externalreference",
        "externaldatareference",
        "locationlatitude",
        "locationlongitude",
        "distributionchannel",
        "userlanguage",
        "q_url",
        "q_language",
    }
)

NAME_MAX = 64
_NAME_OK = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_PIPE = re.compile(r"\$\{([^}]*)\}")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_MARKUP = re.compile(r"[&<>\n]")
_TAGS = re.compile(r"<[^>]+>")
_URL_SAFE = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.!~*'()")
_SIMPLE_LANGUAGE = re.compile(r"^[a-z]{2}$")
_B62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_OUTCOME_FIELD = "ospoutcome"

# Qualtrics logic operators for our comparisons with a literal, and their complements.
_OPS = {
    "==": "EqualTo",
    "!=": "NotEqualTo",
    "<": "LessThan",
    "<=": "LessThanOrEqual",
    ">": "GreaterThan",
    ">=": "GreaterThanOrEqual",
}
_COMPLEMENT = {"==": "!=", "!=": "==", "<": ">=", ">=": "<", "<=": ">", ">": "<="}
_FLIP = {"==": "==", "!=": "!=", "<": ">", ">": "<", "<=": ">=", ">=": "<="}
_LOGIC_MAX = 64  # condition sets (and conditions per set) one condition may expand to

type Texts = dict[str, str]  # language -> Qualtrics text (HTML + piped text)


def _percent_encode(value: str) -> str:
    return "".join(
        ch if ch in _URL_SAFE else "".join(f"%{b:02X}" for b in ch.encode("utf-8")) for ch in value
    )


def _hash_id(*parts: str, length: int = 15) -> str:
    """A stable base-62 id from ``parts`` (Qualtrics ids are a prefix and 15 characters)."""
    n = int.from_bytes(hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest(), "big")
    out = []
    for _ in range(length):
        n, r = divmod(n, 62)
        out.append(_B62[r])
    return "".join(out)


# --- Result -------------------------------------------------------------------------------


@dataclass(frozen=True)
class QsfExport:
    """An export: the ``.qsf`` bytes plus the metadata a researcher needs to read the data.

    - ``name_map``: our variable name (``name`` or ``id``) → Qualtrics export tag (or
      embedded data field), for every question and variable written. ``renamed`` is the
      subset whose tag differs.
    - ``choice_codes``: our variable name → {our choice value as text: recode value}, only
      for questions where a code had to change.
    - ``qids``: our question id → its Qualtrics question id (``QIDn``).
    - ``helpers``: generated export tags and fields → what they hold.
    """

    qsf: bytes
    survey_id: str
    name_map: dict[str, str]
    renamed: dict[str, str]
    choice_codes: dict[str, dict[str, str]]
    qids: dict[str, str]
    helpers: dict[str, str]


# --- Public API ---------------------------------------------------------------------------


def export_qsf(survey: Survey | Mapping[str, Any]) -> tuple[bytes, list[ExportDiagnostic]]:
    """Export a survey to Qualtrics ``.qsf`` JSON bytes (UTF-8), with diagnostics.

    Returns ``(b"", diagnostics)`` with an ``error`` diagnostic if the survey is invalid or
    the exporter fails. Never raises on bad input.
    """
    result, diags = build_qsf(survey)
    return (result.qsf if result is not None else b""), diags


def build_qsf(
    survey: Survey | Mapping[str, Any],
) -> tuple[QsfExport | None, list[ExportDiagnostic]]:
    """The export with its name/code mapping tables, and diagnostics."""
    try:
        data = (
            survey.model_dump(mode="json", by_alias=True, exclude_unset=True)
            if isinstance(survey, Survey)
            else survey
        )
        model, spec_diags = parse(data)
        errors = [d for d in spec_diags if d.severity == "error"]
        if model is None or errors:
            return None, [
                _error("invalid_survey", d.pointer, f"{d.code}: {d.message}") for d in errors
            ] or [_error("invalid_survey", "", "survey did not parse")]
        return _Exporter(model).run()
    except Exception as exc:  # defensive: never crash on input
        return None, [_error("internal", "", f"exporter failed: {type(exc).__name__}: {exc}")]


def _error(what: str, ptr: str, message: str) -> ExportDiagnostic:
    return ExportDiagnostic(
        target=TARGET,
        severity="error",
        code=f"{TARGET}.error.{what}",
        feature="",
        level=None,
        pointer=ptr,
        message=message,
    )


# --- Generic capability walk --------------------------------------------------------------


def feature_uses(obj: object, ptr: str = "") -> Iterator[tuple[str, str, object]]:
    """Every model field present in ``obj``, as ``(capability key, pointer, value)``.

    As ``lss.feature_uses``, against the Qualtrics table: the key is refined to
    ``"<Def>.<field>=<value>"`` when the table has such a row; discriminators (``type``,
    ``kind``) always count as present; nothing inside an unsupported field is reported
    again. An empty list or map uses no feature and is skipped.
    """
    if isinstance(obj, BaseModel):
        cls = type(obj).__name__
        fields = type(obj).model_fields
        for disc in ("type", "kind"):
            if disc in fields and getattr(obj, disc, None) is not None:
                key = f"{cls}.{disc}"
                yield key, ptr, getattr(obj, disc)
                if _level(key) == "unsupported":
                    return
        for name, info in fields.items():
            alias = info.alias or name
            if alias in ("type", "kind") or name not in obj.model_fields_set:
                continue
            value = getattr(obj, name)
            if isinstance(value, (list, tuple, dict)) and not value:
                continue
            p = ptr + pointer(alias)
            key = f"{cls}.{alias}"
            if isinstance(value, (bool, int, str)):
                refined = f"{key}={str(value).lower() if isinstance(value, bool) else value}"
                if refined in QSF:
                    key = refined
            yield key, p, value
            if _level(key) != "unsupported":
                yield from feature_uses(value, p)
    elif isinstance(obj, (list, tuple)):
        for i, item in enumerate(obj):
            yield from feature_uses(item, ptr + pointer(i))
    elif isinstance(obj, dict):  # a map of models (`settings.endings`)
        for k, item in obj.items():
            if isinstance(item, BaseModel):
                yield from feature_uses(item, ptr + pointer(str(k)))


def _level(key: str) -> str | None:
    cap = QSF.get(key)
    return cap.level if cap else None


# --- Logic (display logic, branch logic) ----------------------------------------------------


class _Unmappable(Exception):
    """A condition Qualtrics logic cannot say; carries the reason."""


# One Qualtrics condition, and a condition in disjunctive normal form: a list of sets (Or)
# of conditions (And). `[]` is never true, `[[]]` always.
type _Cond = dict[str, Any]
type _Dnf = list[list[_Cond]]
_ALWAYS: _Dnf = [[]]


def _and(a: _Dnf, b: _Dnf) -> _Dnf:
    out = [x + y for x in a for y in b]
    if len(out) > _LOGIC_MAX or any(len(s) > _LOGIC_MAX for s in out):
        raise _Unmappable("the condition is too large once written as Or of Ands")
    return out


def _or(a: _Dnf, b: _Dnf) -> _Dnf:
    if [] in a or [] in b:
        return _ALWAYS
    out = a + b
    if len(out) > _LOGIC_MAX:
        raise _Unmappable("the condition is too large once written as Or of Ands")
    return out


@dataclass
class _Target:
    """What a reference in a condition or a pipe names in the export."""

    kind: str  # single | multi | entry | slider | date | text | cell | field | none
    qid: str = ""
    embedded: str = ""  # embedded data field
    choices: dict[str, str] = field(default_factory=dict)  # our value (text) -> choice id
    row: str = ""  # a grid statement's choice id


class _Logic:
    """Our condition → Qualtrics logic. Every comparison is guarded so that a missing
    value behaves as in §3: a positive comparison is false when the question is
    unanswered, its negation true."""

    def __init__(self, targets: Mapping[str, _Target]) -> None:
        self.targets = targets

    def dnf(self, e: Expr, neg: bool = False) -> _Dnf:
        match e:
            case And():
                parts = [self.dnf(a, neg) for a in e.args]
                acc = parts[0]
                for p in parts[1:]:
                    acc = _or(acc, p) if neg else _and(acc, p)
                return acc
            case Or():
                parts = [self.dnf(a, neg) for a in e.args]
                acc = parts[0]
                for p in parts[1:]:
                    acc = _and(acc, p) if neg else _or(acc, p)
                return acc
            case Not():
                return self.dnf(e.arg, not neg)
            case BoolLit():
                return _ALWAYS if e.value != neg else []
            case Compare():
                return self._compare(e, neg)
            case Contains():
                t = self._target(e.ref)
                if t.kind != "multi":
                    raise _Unmappable("contains() on a question that is not multiple answer")
                cid = self._choice(t, e.value)
                return [[self._selected(t, cid, not neg)]]
            case Answered():
                return self._answered(self._target(e.ref), neg)
            case _:
                raise _Unmappable(f"a {getattr(e, 'kind', '?')} node has no Qualtrics logic")

    def _target(self, ref: Ref) -> _Target:
        t = self.targets.get(ref.id)
        if t is None or t.kind == "none":
            raise _Unmappable(f"{ref.id} is not a question or field Qualtrics logic can test")
        return t

    @staticmethod
    def _choice(t: _Target, lit: Expr) -> str:
        if not isinstance(lit, (IntLit, TextLit, DecLit)):
            raise _Unmappable("a choice is tested against something that is not a literal")
        cid = t.choices.get(str(lit.value))
        if cid is None:
            raise _Unmappable(f"{lit.value!r} is not one of the question's choices")
        return cid

    def _compare(self, e: Compare, neg: bool) -> _Dnf:
        op, left, right = e.op, e.left, e.right
        if isinstance(right, Ref) and not isinstance(left, Ref):
            op, left, right = _FLIP[op], right, left
        if not isinstance(left, Ref) or not isinstance(right, (IntLit, DecLit, TextLit)):
            raise _Unmappable("only a comparison of a question with a literal can be written")
        t = self._target(left)
        if neg:
            op = _COMPLEMENT[op]
        if t.kind in ("single", "cell"):
            if op not in ("==", "!="):
                raise _Unmappable(f"a choice question is compared with {e.op}")
            cid = self._choice(t, right)
            if op == "==" and not neg:
                return [[self._selected(t, cid, True)]]
            if op == "!=" and not neg:  # answered, and not this choice
                return [[self._selected(t, c, True)] for c in t.choices.values() if c != cid]
            if op == "!=":  # not (q == v): unanswered counts
                return [[self._selected(t, cid, False)]]
            return _or([[self._selected(t, cid, True)]], self._answered(t, True))  # not !=
        if t.kind in ("entry", "slider", "field") or (t.kind == "text" and op in ("==", "!=")):
            test = self._entry(t, _OPS[op], right)
            if not neg:
                return [[test, self._entry(t, "NotEmpty")]]
            return [[test, self._entry(t, "NotEmpty")], [self._entry(t, "Empty")]]
        raise _Unmappable(f"{left.id} cannot be compared with {e.op} in Qualtrics logic")

    def _answered(self, t: _Target, neg: bool) -> _Dnf:
        if t.kind in ("entry", "slider", "field", "text", "date"):
            return [[self._entry(t, "Empty" if neg else "NotEmpty")]]
        if t.kind in ("single", "multi", "cell"):
            ids = list(t.choices.values())
            if neg:
                return [[self._selected(t, c, False) for c in ids]]
            return [[self._selected(t, c, True)] for c in ids]
        raise _Unmappable("answered() on this question cannot be written")

    @staticmethod
    def _selected(t: _Target, cid: str, yes: bool) -> _Cond:
        locator = (
            f"q://{t.qid}/SelectableChoice/{t.row}/{cid}"
            if t.kind == "cell"
            else f"q://{t.qid}/SelectableChoice/{cid}"
        )
        op = "Selected" if yes else "NotSelected"
        return {
            "LogicType": "Question",
            "QuestionID": t.qid,
            "QuestionIsInLoop": "no",
            "ChoiceLocator": locator,
            "Operator": op,
            "QuestionIDFromLocator": t.qid,
            "LeftOperand": locator,
            "Type": "Expression",
            "Description": f"{t.qid} choice {cid} is {op}",
        }

    @staticmethod
    def _entry(t: _Target, op: str, lit: Expr | None = None) -> _Cond:
        right = "" if lit is None else _literal(lit)
        if t.kind == "field":
            out: _Cond = {"LogicType": "EmbeddedField", "LeftOperand": t.embedded, "Operator": op}
            if lit is not None:
                out["RightOperand"] = right
            out |= {"Type": "Expression", "Description": f"{t.embedded} {op} {right}".rstrip()}
            return out
        locator = (
            f"q://{t.qid}/ChoiceNumericEntryValue/1"
            if t.kind == "slider"
            else f"q://{t.qid}/ChoiceTextEntryValue"
        )
        out = {
            "LogicType": "Question",
            "QuestionID": t.qid,
            "QuestionIsInLoop": "no",
            "ChoiceLocator": locator,
            "Operator": op,
            "QuestionIDFromLocator": t.qid,
            "LeftOperand": locator,
        }
        if lit is not None:
            out["RightOperand"] = right
        out |= {"Type": "Expression", "Description": f"{t.qid} {op} {right}".rstrip()}
        return out


def _literal(lit: Expr) -> str:
    if isinstance(lit, DecLit):
        d = lit.value
        return format(d, "f") if isinstance(d, Decimal) else str(d)
    if isinstance(lit, (IntLit, TextLit)):
        return str(lit.value)
    return ""


def logic_document(dnf: _Dnf) -> dict[str, Any]:
    """A DNF as a Qualtrics logic object: numbered condition sets joined by Or, each a
    numbered list of conditions joined by And."""
    doc: dict[str, Any] = {}
    for i, conds in enumerate(dnf):
        s: dict[str, Any] = {}
        for j, c in enumerate(conds):
            s[str(j)] = c if j == 0 else {**c, "Conjuction": "And"}
        s["Type"] = "If"
        if i:
            s["Conjuction"] = "Or"
        doc[str(i)] = s
    doc["Type"] = "BooleanExpression"
    doc["inPage"] = False
    return doc


# --- Intermediate structure ---------------------------------------------------------------


@dataclass
class _Question:
    """One survey question (`SQ` element) to write."""

    qid: str
    tag: str
    payload: dict[str, Any]


@dataclass
class _Block:
    id: str  # BL_...
    description: str
    elements: list[dict[str, Any]] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)


# --- Exporter ------------------------------------------------------------------------------


class _Exporter:
    def __init__(self, survey: Survey) -> None:
        self.s = survey
        self.diags: list[ExportDiagnostic] = []
        self._seen: set[tuple[str, str]] = set()
        self.langs = list(survey.metadata.languages)
        self.base_lang = survey.metadata.defaultLanguage or self.langs[0]
        self.langs = [self.base_lang, *[x for x in self.langs if x != self.base_lang]]
        self.taken: set[str] = set()
        self.tags: dict[str, str] = {}  # id -> export tag / field
        self.our_names: dict[str, str] = {}  # id -> our name
        self.qids: dict[str, str] = {}  # question id -> QIDn
        self.targets: dict[str, _Target] = {}
        self.choice_maps: dict[str, dict[str, str]] = {}  # question id -> {value: recode}
        self.choice_rows: dict[str, list[tuple[str, int, Choice, str]]] = {}
        self.questions: list[_Question] = []
        self.blocks: list[_Block] = []
        self.block_ids: dict[str, str] = {}  # our block id -> BL id
        self.helpers: dict[str, str] = {}
        self.flow_count = 1  # FL_1 is the root
        self.next_qid = 1
        self.survey_id = "SV_" + _hash_id("survey", survey.id)
        self.logic = _Logic(self.targets)
        self.outcome_field: str | None = None
        self.vars = {v.id: v for v in survey.variables}

    # -- diagnostics ---------------------------------------------------------------------

    def note(self, feature: str, ptr: str, detail: str = "") -> None:
        cap: Capability | None = QSF.get(feature)
        if cap is None:
            if (feature, ptr) in self._seen:
                return
            self._seen.add((feature, ptr))
            self.diags.append(
                ExportDiagnostic(
                    target=TARGET,
                    severity="warning",
                    code=f"{TARGET}.unknown_feature",
                    feature=feature,
                    level=None,
                    pointer=ptr,
                    message=f"{feature} has no row in the Qualtrics capability table; "
                    "it may not be exported",
                )
            )
            return
        if cap.level == "native" or (feature, ptr) in self._seen:
            return
        self._seen.add((feature, ptr))
        message = f"{feature} is {cap.level} in Qualtrics: {cap.note}"
        if detail:
            message += f" ({detail})"
        self.diags.append(
            ExportDiagnostic(
                target=TARGET,
                severity=SEVERITY_FOR_LEVEL[cap.level],
                code=f"{TARGET}.{cap.level}",
                feature=feature,
                level=cap.level,
                pointer=ptr,
                message=message,
            )
        )

    # -- naming --------------------------------------------------------------------------

    def _alloc(self, base: str) -> str:
        """A free export tag from ``base``: starts with a letter, letters, digits and `_`,
        at most 64 characters, not a Qualtrics response column, unique ignoring case."""
        stem = sanitise_name(base)
        name, n = stem, 1
        while name.lower() in self.taken or name.lower() in RESERVED_NAMES:
            n += 1
            suffix = f"_{n}"
            name = stem[: NAME_MAX - len(suffix)] + suffix
        self.taken.add(name.lower())
        return name

    def _helper(self, base: str, what: str) -> str:
        tag = self._alloc(base)
        self.helpers[tag] = what
        return tag

    def _qid(self) -> str:
        qid = f"QID{self.next_qid}"
        self.next_qid += 1
        return qid

    def _index(self) -> None:
        """Export tags for every question and variable, and a QID for every question.

        Embedded fields are named after their URL parameter (Qualtrics fills a field from
        the parameter of the same name), so they are taken first and never renamed. Names
        that are already valid come next, so a rewritten name never takes one."""
        entries: list[tuple[str, str, str]] = []  # (id, our name, pointer)
        for bi, b in enumerate(self.s.blocks):
            for pi, page in enumerate(b.pages):
                for qi, q in enumerate(page.items):
                    ptr = pointer("blocks", bi, "pages", pi, "items", qi)
                    name = getattr(q, "name", None)
                    entries.append((q.id, name or q.id, ptr + ("/name" if name else "/id")))
                    self.qids[q.id] = self._qid()
        for vi, v in enumerate(self.s.variables):
            self.our_names[v.id] = v.name or v.id
            if isinstance(v, EmbeddedVariable):
                self.tags[v.id] = v.param
                self.taken.add(v.param.lower())
                if v.param != (v.name or v.id):
                    self.note("$embedded.param", pointer("variables", vi, "param"))
            elif isinstance(v, AssignedVariable):
                ptr = pointer("variables", vi) + ("/name" if v.name else "/id")
                entries.append((v.id, v.name or v.id, ptr))

        def valid(name: str) -> bool:
            return (
                bool(_NAME_OK.match(name))
                and len(name) <= NAME_MAX
                and name.lower() not in RESERVED_NAMES
            )

        for _id, name, _p in entries:
            if valid(name) and name.lower() not in self.taken:
                self.taken.add(name.lower())
                self.tags[_id] = name
        for _id, name, ptr in entries:
            self.our_names[_id] = name
            if _id in self.tags:
                continue
            tag = self._alloc(name)
            self.tags[_id] = tag
            if sanitise_name(name).lower() in RESERVED_NAMES:
                self.note("$names.reserved", ptr, f"{name} → {tag}")
            else:
                self.note("$names.rename", ptr, f"{name} → {tag}")

    def _choices(
        self, q: SingleQuestion | MultiQuestion | MatrixQuestion, ptr: str
    ) -> list[tuple[str, int, Choice, str]]:
        """(choice id, recode value, choice, pointer of its label) for each choice of
        ``q``. A whole-number value is its own recode; a text value is coded by the next
        free positive number ($choice.code). A positive recode is also the choice id."""
        if q.choiceList is not None:
            li = next(i for i, cl in enumerate(self.s.choiceLists) if cl.id == q.choiceList)
            choices = self.s.choiceLists[li].choices
            base = pointer("choiceLists", li, "choices")
        else:
            choices = q.choices or []
            base = ptr + "/choices"
        used = {c.value for c in choices if isinstance(c.value, int)}
        recodes: list[int] = []
        n = 0
        for ci, c in enumerate(choices):
            if isinstance(c.value, int):
                recodes.append(c.value)
                continue
            n += 1
            while n in used:
                n += 1
            used.add(n)
            recodes.append(n)
            self.note("$choice.code", base + pointer(ci, "value"), f"{c.value!r} → {n}")
        ids = {r for r in recodes if r > 0}
        out: list[tuple[str, int, Choice, str]] = []
        k = 0
        for ci, (c, recode) in enumerate(zip(choices, recodes, strict=True)):
            if recode > 0:
                cid = recode
            else:
                k += 1
                while k in ids:
                    k += 1
                ids.add(k)
                cid = k
            out.append((str(cid), recode, c, base + pointer(ci, "label")))
        self.choice_maps[q.id] = {str(c.value): str(r) for _i, r, c, _p in out}
        return out

    def _targets(self) -> None:
        """What each question and variable id is to logic and piping; the choice codes of
        every choice question (with their diagnostics)."""
        for bi, b in enumerate(self.s.blocks):
            for pi, page in enumerate(b.pages):
                for qi, q in enumerate(page.items):
                    ptr = pointer("blocks", bi, "pages", pi, "items", qi)
                    self.targets.update(self._targets_of(q, ptr))
        for v in self.s.variables:
            if isinstance(v, (EmbeddedVariable, AssignedVariable)):
                self.targets[v.id] = _Target("field", embedded=self.tags[v.id])
            else:
                self.targets[v.id] = _Target("none")

    def _targets_of(self, q: Any, ptr: str) -> dict[str, _Target]:
        qid = self.qids[q.id]
        match q:
            case SingleQuestion() | MultiQuestion():
                rows = self._choices(q, ptr)
                self.choice_rows[q.id] = rows
                kind = "single" if isinstance(q, SingleQuestion) else "multi"
                choices = {str(c.value): i for i, _r, c, _p in rows}
                return {q.id: _Target(kind, qid, choices=choices)}
            case MatrixQuestion():
                rows = self._choices(q, ptr)
                self.choice_rows[q.id] = rows
                cols = {str(c.value): i for i, _r, c, _p in rows}
                out = {q.id: _Target("none", qid)}
                for k, row in enumerate(q.rows):
                    out[matrix_row_id(q.id, row.id)] = _Target(
                        "cell", qid, choices=cols, row=str(k + 1)
                    )
                return out
            case IntegerQuestion() | DecimalQuestion():
                return {q.id: _Target("entry", qid)}
            case TextQuestion():
                return {q.id: _Target("text", qid)}
            case DateQuestion():
                return {q.id: _Target("date", qid)}
            case SliderQuestion():
                return {q.id: _Target("slider", qid)}
        return {q.id: _Target("none", qid)}

    def _condition(self, e: Expr, ptr: str, neg: bool = False) -> _Dnf | None:
        """The condition as logic, or None (reported) when it cannot be written."""
        try:
            dnf = self.logic.dnf(e, neg)
        except _Unmappable as exc:
            self.note("$logic.unmappable", ptr, str(exc))
            return None
        if not dnf:
            self.note("$logic.unmappable", ptr, "the condition is never true")
            return None
        return dnf

    # -- text ----------------------------------------------------------------------------

    def _texts(self, text: object, ptr: str) -> Texts:
        """``{language: Qualtrics HTML}``: plain strings escaped with `\\n` as `<br />`,
        rich text (RT2) as the HTML subset (RT4), pipes rewritten to piped text."""
        text = as_json(text)
        if text is None:
            return {}
        if isinstance(text, str) or is_rich(text):
            per_lang = {lang: (text, ptr) for lang in self.langs}
        else:
            assert isinstance(text, dict)
            fallback = text.get(self.base_lang) or next(iter(text.values()), "")
            per_lang = {
                lang: (text.get(lang, fallback), ptr + pointer(lang) if lang in text else ptr)
                for lang in self.langs
            }
        return {lang: self._html(value, vp) for lang, (value, vp) in per_lang.items()}

    def _html(self, value: object, ptr: str) -> str:
        if is_rich(value):
            assert isinstance(value, dict)
            return to_html(
                value,
                escape=lambda s, path: self._escape(s, ptr + pointer(*path)),
                pipe=lambda qid, path: self._pipe(qid, ptr + pointer(*path)),
                report=lambda key, path: self.note(key, ptr + pointer(*path)),
            )
        return self._render(value if isinstance(value, str) else "", ptr)

    def _escape(self, s: str, ptr: str) -> str:
        if _CONTROL.search(s):
            self.note("$text.controlCharacters", ptr)
            s = _CONTROL.sub("", s)
        if _MARKUP.search(s):
            self.note("$text.markup", ptr)
        # `${` would start piped text in Qualtrics.
        return html.escape(s, quote=False).replace("\n", "<br />").replace("${", "&#36;{")

    def _render(self, s: str, ptr: str) -> str:
        out: list[str] = []
        pos = 0
        for m in _PIPE.finditer(s):
            out.append(self._escape(s[pos : m.start()], ptr))
            pos = m.end()
            out.append(self._pipe(m.group(1).strip(), ptr, m.group(0)))
        out.append(self._escape(s[pos:], ptr))
        return "".join(out)

    def _pipe(self, ref: str, ptr: str, raw: str | None = None) -> str:
        """Qualtrics piped text for one `${id}` (`raw` is how it was written, kept as
        escaped text when the id is unknown), with the piping diagnostics at `ptr`."""
        if ref.startswith("$"):
            self.note("$pipe.builtin", ptr, f"${{{ref}}}")
            return ""
        t = self.targets.get(ref)
        if t is None:
            return self._escape(raw if raw is not None else "${" + ref + "}", ptr)
        match t.kind:
            case "single":
                return f"${{q://{t.qid}/ChoiceGroup/SelectedChoices}}"
            case "multi":
                self.note("$pipe.multi", ptr, f"${{{ref}}}")
                return f"${{q://{t.qid}/ChoiceGroup/SelectedChoices}}"
            case "entry" | "text" | "date":
                return f"${{q://{t.qid}/ChoiceTextEntryValue}}"
            case "slider":
                return f"${{q://{t.qid}/ChoiceNumericEntryValue/1}}"
            case "field":
                return f"${{e://Field/{t.embedded}}}"
        self.note("$pipe.unsupported", ptr, f"${{{ref}}}")
        return ""

    def _plain_texts(self, text: object, ptr: str) -> Texts:
        return {lang: _plain(t) for lang, t in self._texts(text, ptr).items()}

    @staticmethod
    def _paragraph(text: str) -> str:
        if not text:
            return ""
        return text if is_block_html(text) else f"<p>{text}</p>"

    # -- run -----------------------------------------------------------------------------

    def run(self) -> tuple[QsfExport, list[ExportDiagnostic]]:
        for key, ptr, _value in feature_uses(self.s):
            self.note(key, ptr)
        self._index()
        self._targets()
        for code in self.langs:
            if not _SIMPLE_LANGUAGE.match(code):
                self.note("$language.code", "/metadata/languages", code)
        consent = self._consent_block()
        for bi, b in enumerate(self.s.blocks):
            self._block(bi, b)
        if consent is not None:
            self.blocks.insert(0, consent)
        flow = self._setup_flow()
        if consent is not None:
            flow += self._consent_flow(consent)
        flow += self._walk(self.s.flow, "/flow")
        if not flow or flow[-1].get("Type") != "EndSurvey":
            flow += self._end_elements("complete", None, "")
        if any(not isinstance(q, NoteQuestion) for q in _questions(self.s)):
            self.note("$missingStates", "")
        return self._result(flow), self.diags

    def _result(self, flow: list[dict[str, Any]]) -> QsfExport:
        name_map = {self.our_names[i]: self.tags[i] for i in self.our_names if i in self.tags}
        for q in _questions(self.s):
            if isinstance(q, MatrixQuestion):
                for row in q.rows:
                    name_map[matrix_row_name(q, row.id)] = f"{self.tags[q.id]}_{row.id}"
        renamed = {k: v for k, v in name_map.items() if k != v}
        choice_codes = {
            self.our_names[qid]: {k: v for k, v in m.items() if k != v}
            for qid, m in self.choice_maps.items()
            if any(k != v for k, v in m.items())
        }
        doc = self._document(flow)
        data = (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        return QsfExport(
            data,
            self.survey_id,
            name_map,
            renamed,
            choice_codes,
            dict(self.qids),
            dict(self.helpers),
        )

    def _document(self, flow: list[dict[str, Any]]) -> dict[str, Any]:
        sid = self.survey_id
        title = self.s.metadata.title
        description = (
            self._plain_texts(self.s.metadata.description, "/metadata/description").get(
                self.base_lang
            )
            if self.s.metadata.description is not None
            else None
        )
        trash = _Block("BL_" + _hash_id(self.s.id, "trash"), "Trash / Unused Questions")
        blocks = [
            {
                "Type": "Default" if i == 0 else "Standard",
                "Description": b.description,
                "ID": b.id,
                "BlockElements": b.elements,
                "Options": b.options
                or {
                    "BlockLocking": "false",
                    "RandomizeQuestions": "false",
                    "BlockVisibility": "Expanded",
                },
            }  # fmt: skip
            for i, b in enumerate(self.blocks)
        ]
        blocks.append(
            {"Type": "Trash", "Description": trash.description, "ID": trash.id, "BlockElements": []}
        )
        options = {
            "BackButton": "true" if self.s.settings.backNavigation else "false",
            "SaveAndContinue": "true",
            "SurveyProtection": "PublicSurvey",
            "BallotBoxStuffingPrevention": "false",
            "NoIndex": "Yes",
            "SecureResponseFiles": "true",
            "SurveyExpiration": "None",
            "Header": "",
            "Footer": "",
            "ProgressBarDisplay": "None",
            "PreviousButton": "",
            "NextButton": "",
            "SurveyTitle": title,
            "SurveyLanguage": self._code(self.base_lang),
        }
        elements: list[dict[str, Any]] = [
            _element(sid, "BL", "Survey Blocks", None, blocks),
            _element(
                sid,
                "FL",
                "Survey Flow",
                None,
                {
                    "Type": "Root",
                    "FlowID": "FL_1",
                    "Flow": flow,
                    "Properties": {"Count": self.flow_count},
                },
            ),
            _element(sid, "SO", "Survey Options", None, options),
            _element(sid, "QC", "Survey Question Count", str(len(self.questions)), None),
            _element(sid, "RS", "RS_" + _hash_id(self.s.id, "rs"), "Default Response Set", None),
        ]
        for q in sorted(self.questions, key=lambda q: int(q.qid[3:])):
            desc = str(q.payload.get("QuestionDescription", ""))[:100]
            elements.append(_element(sid, "SQ", q.qid, desc, q.payload))
        return {
            "SurveyEntry": {
                "SurveyID": sid,
                "SurveyName": title,
                "SurveyDescription": description,
                "SurveyOwnerID": "",
                "SurveyBrandID": "",
                "DivisionID": None,
                "SurveyLanguage": self._code(self.base_lang),
                "SurveyActiveResponseSet": "RS_" + _hash_id(self.s.id, "rs"),
                "SurveyStatus": "Inactive",
                "SurveyStartDate": "0000-00-00 00:00:00",
                "SurveyExpirationDate": "0000-00-00 00:00:00",
                "SurveyCreationDate": "0000-00-00 00:00:00",
                "CreatorID": "",
                "LastModified": "0000-00-00 00:00:00",
                "LastAccessed": "0000-00-00 00:00:00",
                "LastActivated": "0000-00-00 00:00:00",
                "Deleted": None,
            },
            "SurveyElements": elements,
        }

    @staticmethod
    def _code(tag: str) -> str:
        return tag.upper()

    # -- flow ----------------------------------------------------------------------------

    def _flow_id(self) -> str:
        self.flow_count += 1
        return f"FL_{self.flow_count}"

    def _embedded(self, fields: list[tuple[str, str, str | None]]) -> dict[str, Any]:
        """An EmbeddedData flow element: (field, variable type, value or None)."""
        return {
            "Type": "EmbeddedData",
            "FlowID": self._flow_id(),
            "EmbeddedData": [
                {
                    "Description": name,
                    "Type": "Custom" if value is not None else "Recipient",
                    "Field": name,
                    "VariableType": vtype,
                    "DataVisibility": [],
                    "AnalyzeText": False,
                    **({"Value": value} if value is not None else {}),
                }
                for name, vtype, value in fields
            ],
        }

    def _setup_flow(self) -> list[dict[str, Any]]:
        """Embedded fields first (filled from the URL), then their defaults."""
        embedded = [v for v in self.s.variables if isinstance(v, EmbeddedVariable)]
        if not embedded:
            return []
        out = [
            self._embedded(
                [(v.param, "String" if v.valueType == "text" else "Number", None) for v in embedded]
            )
        ]
        for v in embedded:
            if v.default is None:
                continue
            t = self.targets[v.id]
            cond = [[self.logic._entry(t, "Empty")]]
            out.append(
                {
                    "Type": "Branch",
                    "FlowID": self._flow_id(),
                    "Description": f"Default for {v.param}",
                    "BranchLogic": logic_document(cond),
                    "Flow": [
                        self._embedded(
                            [
                                (
                                    v.param,
                                    "String" if v.valueType == "text" else "Number",
                                    str(v.default),
                                )
                            ]
                        )
                    ],
                }
            )
        return out

    def _walk(self, nodes: list[Any], ptr: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i, node in enumerate(nodes):
            p = ptr + pointer(i)
            match node:
                case BlockNode():
                    if node.block in self.block_ids:
                        bid = self.block_ids[node.block]
                        first = self.blocks[0].id if self.blocks else None
                        out.append(
                            {
                                "Type": "Block" if bid == first else "Standard",
                                "ID": bid,
                                "FlowID": self._flow_id(),
                                "Autofill": [],
                            }
                        )
                case BranchNode():
                    out += self._branch(node, p)
                case RandomiserNode():
                    out += self._randomiser(node, p)
                case AssignNode():
                    out += self._assign(node)
                case EndNode():
                    out += self._end_elements(node.outcome, node, p)
                    return out  # nothing after an end runs
                # QuotaCheckNode, ExternalTaskNode: reported by the capability walk.
        return out

    def _branch(self, node: BranchNode, ptr: str) -> list[dict[str, Any]]:
        yes = self._condition(node.if_, ptr + "/if")
        no = self._condition(node.if_, ptr + "/if", neg=True) if yes is not None else None
        then = self._walk(node.then, ptr + "/then")
        else_ = self._walk(node.else_, ptr + "/else")
        if yes is None or (node.else_ and no is None):
            # Unmappable: both arms run for everyone (reported as $logic.unmappable).
            return [self._group(then + else_, f"Branch {node.id} (condition not exported)")]
        out: list[dict[str, Any]] = []
        for dnf, arm, label in ((yes, then, "then"), (no or [], else_, "else")):
            if not arm or dnf == []:
                continue
            if dnf == _ALWAYS:
                out += arm
                continue
            out.append(
                {
                    "Type": "Branch",
                    "FlowID": self._flow_id(),
                    "Description": f"{node.id} ({label})",
                    "BranchLogic": logic_document(dnf),
                    "Flow": arm,
                }
            )
        return out

    def _group(self, flow: list[dict[str, Any]], description: str) -> dict[str, Any]:
        return {
            "Type": "Group",
            "FlowID": self._flow_id(),
            "Description": description,
            "Flow": flow,
        }

    def _randomiser(self, node: RandomiserNode, ptr: str) -> list[dict[str, Any]]:
        children: list[dict[str, Any]] = []
        for k, child in enumerate(node.children):
            elems = self._walk([child], ptr + pointer("children", k))
            if len(elems) == 1:
                children.append(elems[0])
            elif elems:
                children.append(self._group(elems, f"{node.id} child {k + 1}"))
        if not children:
            return []
        pick = node.pick if node.pick is not None and node.pick < len(children) else len(children)
        return [
            {
                "Type": "BlockRandomizer",
                "FlowID": self._flow_id(),
                "SubSet": pick,
                "EvenPresentation": False,
                "Flow": children,
            }
        ]

    def _assign(self, node: AssignNode) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for vid in node.variables:
            v = self.vars.get(vid)
            if not isinstance(v, AssignedVariable):
                continue
            tag = self.tags[vid]
            out.append(
                {
                    "Type": "BlockRandomizer",
                    "FlowID": self._flow_id(),
                    "SubSet": 1,
                    "EvenPresentation": False,
                    "Flow": [self._embedded([(tag, "String", str(lv))]) for lv in v.levels],
                }
            )
        return out

    def _end_elements(self, outcome: str, node: EndNode | None, ptr: str) -> list[dict[str, Any]]:
        """What ends the survey with ``outcome``: the message and ending block (if any),
        the outcome field (for an outcome Qualtrics has no flag for), the End of Survey."""
        out: list[dict[str, Any]] = []
        texts: list[Texts] = []
        if node is not None and node.message is not None:
            texts.append(self._texts(node.message, ptr + "/message"))
        ending = self._ending_texts(outcome)
        if ending:
            texts.append(ending)
        if texts:
            name = node.id if node is not None else "end"
            block = self._message_block(f"End: {name}", f"ospend_{name}", texts, f"end ({name})")
            out.append(
                {"Type": "Standard", "ID": block.id, "FlowID": self._flow_id(), "Autofill": []}
            )
        if outcome not in ("complete", "screened_out"):
            if self.outcome_field is None:
                self.outcome_field = self._helper(_OUTCOME_FIELD, "end outcome (EndNode.outcome)")
            out.append(self._embedded([(self.outcome_field, "String", outcome)]))
        end: dict[str, Any] = {"Type": "EndSurvey", "FlowID": self._flow_id()}
        options: dict[str, Any] = {}
        if outcome == "screened_out":
            options |= {"Advanced": "true", "EndingType": "Advanced", "ResponseFlag": "Screened"}
        url = self._redirect(outcome)
        if url is not None:
            options |= {
                "Advanced": "true",
                "EndingType": "Advanced",
                "SurveyTermination": "Redirect",
                "EOSRedirectURL": url,
            }
        if options:
            end["Options"] = options
        out.append(end)
        return out

    def _ending_texts(self, outcome: str) -> Texts:
        """An outcome's ending (EN1) as one text per language: title, then body."""
        ending = self.s.settings.endings.get(outcome)
        if ending is None:
            return {}
        parts: dict[str, list[str]] = {lang: [] for lang in self.langs}
        for key in ("title", "body"):
            ptr = pointer("settings", "endings", outcome, key)
            for lang, t in self._texts(getattr(ending, key), ptr).items():
                parts[lang].append(self._paragraph(t))
        return {lang: "".join(ps) for lang, ps in parts.items() if any(ps)}

    def _redirect(self, outcome: str) -> str | None:
        """An outcome's end redirect (EN2): the template URL with its literal params
        percent-encoded. None when the outcome has none, or a param is piped."""
        ending = self.s.settings.endings.get(outcome)
        if ending is None or ending.redirect is None:
            return None
        r = ending.redirect
        ptr = pointer("settings", "endings", outcome, "redirect")
        template = redirect_templates(self.s).get(r.template)
        if template is None:
            return None  # the validator's redirect.unknown_template already blocks publishing
        if any(_PIPE.search(v) for v in r.params.values()):
            self.note("$redirect.piped", ptr + "/params")
            return None
        url = template.url
        for name in placeholders(template.url):
            value = r.params.get(name, "")
            pattern = getattr(template.params.get(name), "pattern", None) or DEFAULT_PARAM_PATTERN
            if not re.fullmatch(f"(?:{pattern})", value) or value in (".", ".."):
                return None  # the validator's redirect.param_literal already blocks publishing
            url = url.replace("{" + name + "}", _percent_encode(value))
        if r.mode == "auto":
            self.note("EndRedirect.delay", ptr + "/delay")
        return url

    # -- consent ---------------------------------------------------------------------------

    def _consent_block(self) -> _Block | None:
        c = self.s.consent
        if c is None:
            return None
        block = _Block("BL_" + _hash_id(self.s.id, "consent"), "Consent")
        text = self._texts(c.text, "/consent/text")
        tag = self._helper("ospconsent_text", "consent text")
        block.elements.append(self._db(tag, text))
        tag = self._helper("ospconsent", "consent answer: 1 agree, 2 decline")
        qid = self._qid()
        labels = [
            ("1", self._texts(c.agreeLabel, "/consent/agreeLabel")),
            ("2", self._texts(c.declineLabel, "/consent/declineLabel")),
        ]
        payload = self._payload(qid, tag, {lang: "" for lang in self.langs}, "MC", "SAVR")
        payload["SubSelector"] = "TX"
        payload["Choices"] = {cid: {"Display": t[self.base_lang]} for cid, t in labels}
        payload["ChoiceOrder"] = ["1", "2"]
        payload["RecodeValues"] = {"1": "1", "2": "2"}
        payload["Validation"] = _validation(True)
        payload["NextChoiceId"] = 3
        payload["NextAnswerId"] = 1
        for lang in self.langs[1:]:
            payload["Language"].setdefault(self._code(lang), {})["Choices"] = {
                cid: {"Display": t[lang]} for cid, t in labels
            }
        self.questions.append(_Question(qid, tag, payload))
        block.elements.append({"Type": "Question", "QuestionID": qid})
        self.targets["$consent"] = _Target("single", qid, choices={"agree": "1", "decline": "2"})
        return block

    def _consent_flow(self, block: _Block) -> list[dict[str, Any]]:
        c = self.s.consent
        assert c is not None
        t = self.targets["$consent"]
        return [
            {"Type": "Block", "ID": block.id, "FlowID": self._flow_id(), "Autofill": []},
            {
                "Type": "Branch",
                "FlowID": self._flow_id(),
                "Description": "Consent declined",
                "BranchLogic": logic_document([[self.logic._selected(t, "2", True)]]),
                "Flow": self._end_elements(c.declineOutcome, None, ""),
            },
        ]

    # -- blocks, pages, questions --------------------------------------------------------

    def _message_block(self, description: str, base: str, texts: list[Texts], what: str) -> _Block:
        block = _Block("BL_" + _hash_id(self.s.id, "message", base), description)
        merged = {
            lang: "".join(self._paragraph(t.get(lang, "")) for t in texts) for lang in self.langs
        }
        block.elements.append(self._db(self._helper(base, what), merged))
        self.blocks.append(block)
        return block

    def _db(self, tag: str, text: Texts) -> dict[str, Any]:
        """A generated descriptive-text question; returns its block element."""
        qid = self._qid()
        payload = self._payload(qid, tag, text, "DB", "TB")
        self.questions.append(_Question(qid, tag, payload))
        return {"Type": "Question", "QuestionID": qid}

    def _payload(
        self, qid: str, tag: str, text: Texts, qtype: str, selector: str
    ) -> dict[str, Any]:
        base = text.get(self.base_lang, "")
        payload: dict[str, Any] = {
            "QuestionText": base,
            "DefaultChoices": False,
            "DataExportTag": tag,
            "QuestionType": qtype,
            "Selector": selector,
            "Configuration": {"QuestionDescriptionOption": "UseText"},
            "QuestionDescription": _plain(base)[:200],
            "Language": {},
            "QuestionID": qid,
            "DataVisibility": {"Private": False, "Hidden": False},
        }
        for lang in self.langs[1:]:
            payload["Language"][self._code(lang)] = {"QuestionText": text.get(lang, base)}
        return payload

    def _block(self, bi: int, block: Block) -> None:
        bid = "BL_" + _hash_id(self.s.id, "block", block.id)
        out = _Block(bid, block.title or block.id)
        self.block_ids[block.id] = bid
        for pi, page in enumerate(block.pages):
            pptr = pointer("blocks", bi, "pages", pi)
            if pi:
                out.elements.append({"Type": "Page Break"})
            page_cond: _Dnf = _ALWAYS
            if page.showIf is not None:
                page_cond = self._condition(page.showIf, pptr + "/showIf") or _ALWAYS
            if page.title is not None:
                tag = self._helper(f"{page.id}_title", f"page title ({page.id})")
                el = self._db(tag, self._texts(page.title, pptr + "/title"))
                self._display_logic(self.questions[-1].payload, page_cond)
                out.elements.append(el)
            for qi, q in enumerate(page.items):
                qptr = pptr + pointer("items", qi)
                payload = self._question(q, qptr)
                cond = page_cond
                if q.showIf is not None:
                    own = self._condition(q.showIf, qptr + "/showIf")
                    if own is not None:
                        try:
                            cond = _and(page_cond, own)
                        except _Unmappable as exc:
                            self.note("$logic.unmappable", qptr + "/showIf", str(exc))
                self._display_logic(payload, cond)
                self.questions.append(_Question(self.qids[q.id], self.tags[q.id], payload))
                out.elements.append({"Type": "Question", "QuestionID": self.qids[q.id]})
        if len(block.pages) == 1 and block.pages[0].itemOrder == "shuffle":
            n = sum(1 for e in out.elements if e.get("Type") == "Question")
            out.options = {
                "BlockLocking": "false",
                "RandomizeQuestions": "RandomWithOnlyX",
                "Randomization": {
                    "Advanced": None,
                    "EvenPresentation": False,
                    "TotalRandSubset": n,
                },
                "BlockVisibility": "Expanded",
            }
        self.blocks.append(out)

    @staticmethod
    def _display_logic(payload: dict[str, Any], cond: _Dnf) -> None:
        if cond != _ALWAYS:
            payload["DisplayLogic"] = logic_document(cond)

    def _question(self, q: Any, ptr: str) -> dict[str, Any]:
        qid, tag = self.qids[q.id], self.tags[q.id]
        label = self._texts(q.label, ptr + "/label")
        if q.help is not None:
            helps = self._texts(q.help, ptr + "/help")
            label = {
                lang: self._paragraph(t) + _small(helps.get(lang, "")) for lang, t in label.items()
            }
        match q:
            case NoteQuestion():
                return self._payload(qid, tag, label, "DB", "TB")
            case SingleQuestion() | MultiQuestion():
                single = isinstance(q, SingleQuestion)
                p = self._payload(qid, tag, label, "MC", "SAVR" if single else "MAVR")
                p["SubSelector"] = "TX"
                p["Configuration"] |= {"TextPosition": "inline"}
                rows = self.choice_rows[q.id]
                self._write_choices(p, "Choices", "ChoiceOrder", rows)
                p["RecodeValues"] = {cid: str(recode) for cid, recode, _c, _p in rows}
                p["NextAnswerId"] = 1
                if q.choiceOrder == "shuffle":
                    p["Randomization"] = {
                        "Advanced": None,
                        "TotalRandSubset": "",
                        "Type": "All",
                        "EvenPresentation": False,
                    }
                p["Validation"] = _validation(q.required)
                return p
            case MatrixQuestion():
                p = self._payload(qid, tag, label, "Matrix", "Likert")
                p["SubSelector"] = "SingleAnswer"
                p["Configuration"] |= {
                    "TextPosition": "inline",
                    "ChoiceColumnWidth": 25,
                    "RepeatHeaders": "none",
                    "WhiteSpace": "OFF",
                    "MobileFirst": True,
                }
                cols = self.choice_rows[q.id]
                statements = [
                    (str(k + 1), self._texts(r.label, ptr + pointer("rows", k, "label")))
                    for k, r in enumerate(q.rows)
                ]
                p["Choices"] = {cid: {"Display": t[self.base_lang]} for cid, t in statements}
                p["ChoiceOrder"] = [cid for cid, _t in statements]
                p["ChoiceDataExportTags"] = {str(k + 1): r.id for k, r in enumerate(q.rows)}
                self._write_choices(p, "Answers", "AnswerOrder", cols)
                p["RecodeValues"] = {cid: str(recode) for cid, recode, _c, _p in cols}
                p["NextChoiceId"] = len(statements) + 1
                for lang in self.langs[1:]:
                    p["Language"][self._code(lang)]["Choices"] = {
                        cid: {"Display": t[lang]} for cid, t in statements
                    }
                required = [matrix_row_required(q, r) for r in q.rows]
                if any(required) and not all(required):
                    self.note("$matrix.someRowsRequired", ptr + "/rows")
                p["Validation"] = _validation(all(required))
                return p
            case SliderQuestion():
                p = self._payload(qid, tag, label, "Slider", "HSLIDER")
                decimals = 0 if q.valueType == "integer" else _decimals(q.step, q.min, q.max)
                if not _step_fits(q.step, decimals):
                    self.note("$slider.step", ptr + "/step", f"step {q.step}")
                p["Configuration"] |= {
                    "CSSliderMin": _number(q.min),
                    "CSSliderMax": _number(q.max),
                    "GridLines": 10,
                    "SnapToGrid": False,
                    "NumDecimals": str(decimals),
                    "ShowValue": True,
                    "CustomStart": False,
                    "NotApplicable": False,
                    "MobileFirst": True,
                }
                p["Choices"] = {"1": {"Display": ""}}
                p["ChoiceOrder"] = ["1"]
                labels: dict[str, Texts] = {}
                if q.minLabel is not None or q.maxLabel is not None:
                    labels["1"] = self._texts(q.minLabel or "", ptr + "/minLabel")
                    labels["2"] = self._texts(q.maxLabel or "", ptr + "/maxLabel")
                    p["Labels"] = {k: {"Display": t[self.base_lang]} for k, t in labels.items()}
                    for lang in self.langs[1:]:
                        p["Language"][self._code(lang)]["Labels"] = {
                            k: {"Display": t[lang]} for k, t in labels.items()
                        }
                p["Validation"] = _validation(q.required)
                p["NextChoiceId"] = 2
                p["NextAnswerId"] = 1
                return p
            case IntegerQuestion() | DecimalQuestion() | TextQuestion() | DateQuestion():
                multiline = isinstance(q, TextQuestion) and q.multiline
                p = self._payload(qid, tag, label, "TE", "ML" if multiline else "SL")
                v = _validation(q.required)
                if isinstance(q, (IntegerQuestion, DecimalQuestion)):
                    v["Settings"] |= {
                        "Type": "ContentType",
                        "ContentType": "ValidNumber",
                        "ValidNumber": {
                            "Min": "" if q.min is None else str(q.min),
                            "Max": "" if q.max is None else str(q.max),
                            "NumDecimals": "0" if isinstance(q, IntegerQuestion) else "",
                        },
                    }
                elif isinstance(q, DateQuestion):
                    v["Settings"] |= {
                        "Type": "ContentType",
                        "ContentType": "ValidDate",
                        "ValidDate": {"DateFormat": "yyyy/mm/dd"},
                    }
                p["Validation"] = v
                return p
        raise ValueError(f"unknown question type {type(q).__name__}")  # pragma: no cover

    def _write_choices(
        self,
        p: dict[str, Any],
        key: str,
        order_key: str,
        rows: list[tuple[str, int, Choice, str]],
    ) -> None:
        texts = [(cid, self._texts(c.label, lp)) for cid, _r, c, lp in rows]
        p[key] = {cid: {"Display": t[self.base_lang]} for cid, t in texts}
        p[order_key] = [cid for cid, _t in texts]
        if key == "Choices":
            p["NextChoiceId"] = max((int(cid) for cid, _t in texts), default=0) + 1
        else:
            p["NextAnswerId"] = max((int(cid) for cid, _t in texts), default=0) + 1
        for lang in self.langs[1:]:
            p["Language"][self._code(lang)][key] = {cid: {"Display": t[lang]} for cid, t in texts}


# --- Helpers -------------------------------------------------------------------------------


def _element(
    sid: str, kind: str, primary: str, secondary: str | None, payload: Any
) -> dict[str, Any]:
    return {
        "SurveyID": sid,
        "Element": kind,
        "PrimaryAttribute": primary,
        "SecondaryAttribute": secondary,
        "TertiaryAttribute": None,
        "Payload": payload,
    }


def _validation(required: bool) -> dict[str, Any]:
    return {
        "Settings": {
            "ForceResponse": "ON" if required else "OFF",
            "ForceResponseType": "ON",
            "Type": "None",
        }
    }


def _small(text: str) -> str:
    if not text:
        return ""
    return (
        f"<div><small>{text}</small></div>"
        if is_block_html(text)
        else (f"<p><small>{text}</small></p>")
    )


def _plain(text: str) -> str:
    """A Qualtrics HTML text as one line of plain text."""
    return " ".join(html.unescape(_TAGS.sub(" ", text)).split())


def _number(value: int | str) -> int | float:
    if isinstance(value, int):
        return value
    d = Decimal(value)
    return int(d) if d == d.to_integral_value() else float(value)


def _decimals(*values: int | str) -> int:
    return max((len(str(v).split(".", 1)[1]) for v in values if "." in str(v)), default=0)


def _step_fits(step: int | str, decimals: int) -> bool:
    """Whether a slider with ``decimals`` decimals moves in exactly ``step``."""
    return Decimal(str(step)) == Decimal(1).scaleb(-decimals)


def sanitise_name(name: str) -> str:
    """An export tag from any name: letters, digits and `_`, starting with a letter."""
    out = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not out or not out[0].isalpha():
        out = "q" + out
    return out[:NAME_MAX]


def _questions(s: Survey) -> Iterator[Any]:
    for b in s.blocks:
        for page in b.pages:
            yield from page.items


__all__ = [
    "RESERVED_NAMES",
    "QsfExport",
    "build_qsf",
    "export_qsf",
    "feature_uses",
    "logic_document",
    "sanitise_name",
]
