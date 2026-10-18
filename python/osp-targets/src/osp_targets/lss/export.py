"""``osp-survey`` → LimeSurvey ``.lss`` (LimeSurvey 6.x survey structure XML).

Pipeline (planning/review.md §2.4): validate → walk the model for capability diagnostics
→ allocate LimeSurvey question codes (renaming invalid and reserved names) → lower the flow
tree into group relevance equations → emit the tables → write the XML. Each page becomes
one question group; blocks are consecutive groups. Every feature the capability table
marks as non-native produces a diagnostic with a JSON pointer; :func:`export_lss` never
raises.

Clean-room: written from our own hand-written spike file
(``spikes/spike-1/survey/spike1.lss``), the spike's observed behaviour
(``spikes/spike-1/FINDINGS.md``) and the public LimeSurvey manual. No LimeSurvey code.
"""

from __future__ import annotations

import html
import re
import zlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
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
from osp_expr.static import references
from osp_spec import Survey, is_rich, parse, redirect_templates
from osp_spec.hooks import DEFAULT_PARAM_PATTERN, placeholders
from osp_spec.model import (
    AssignedVariable,
    AssignNode,
    Block,
    BlockNode,
    BranchNode,
    Choice,
    ComputedVariable,
    DateQuestion,
    DecimalQuestion,
    EmbeddedVariable,
    EndNode,
    IntegerQuestion,
    MatrixQuestion,
    MultiQuestion,
    NoteQuestion,
    QuotaCheckNode,
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
from ..richtext import as_json
from .capabilities import LSS
from .em import EMPTY, FALSE, TRUE, EMContext, EMWriter, and_, not_, or_, string_literal
from .html import is_block_html, to_html
from .xml import Table, write_document

TARGET = "lss"

# The .lss DBVersion our spike file used and LimeSurvey 6.17.18 imported (spike-1 Q1).
DB_VERSION = "651"

# LimeSurvey built-in response columns (spike-1 Q2) and Expression Manager variables a
# question code must not shadow. Compared ignoring case.
RESERVED_CODES: frozenset[str] = frozenset(
    {
        "id",
        "token",
        "submitdate",
        "lastpage",
        "startlanguage",
        "seed",
        "startdate",
        "datestamp",
        "ipaddr",
        "refurl",
        # Expression Manager / survey-level variables
        "sid",
        "gid",
        "qid",
        "sgq",
        "lang",
        "savedid",
        "this",
        "self",
        "that",
    }
)

CODE_MAX = 20  # question / subquestion code length
ANSWER_CODE_MAX = 5
_CODE_OK = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
_PIPE = re.compile(r"\$\{([^}]*)\}")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_MARKUP = re.compile(r"[&<>\n]")
# Our own tags in a rendered text (every `<` of the researcher's text is `&lt;` by then).
_TAGS = re.compile(r"<[^>]+>")
_LATCH_MAX = 1_000_000
# LimeSurvey needs a quota message; used when the quota's screen-out block has no text.
_QUOTA_FULL = "<p>Thank you. This survey is now closed for your group.</p>"
# Characters `encodeURIComponent` leaves as they are; everything else is %XX per UTF-8 byte.
_URL_SAFE = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.!~*'()")


def _percent_encode(value: str) -> str:
    """`encodeURIComponent(value)`, as the participant app fills a redirect template."""
    return "".join(
        c if c in _URL_SAFE else "".join(f"%{b:02X}" for b in c.encode("utf-8")) for c in value
    )


@dataclass(frozen=True)
class _Redirect:
    """An end redirect as LimeSurvey holds it (EN2): the filled URL, auto-load, link text."""

    url: str
    auto: bool
    label: dict[str, str]


class _NoPattern:
    pattern: str | None = None


_NO_PATTERN = _NoPattern()

QUESTION_FIELDS = (
    "qid",
    "parent_qid",
    "sid",
    "gid",
    "type",
    "title",
    "preg",
    "other",
    "mandatory",
    "encrypted",
    "question_order",
    "scale_id",
    "same_default",
    "relevance",
    "question_theme_name",
    "modulename",
    "same_script",
)

SURVEY_FIELDS = (
    "sid",
    "gsid",
    "admin",
    "adminemail",
    "anonymized",
    "format",
    "savetimings",
    "template",
    "language",
    "additional_languages",
    "datestamp",
    "usecookie",
    "allowregister",
    "allowsave",
    "autonumber_start",
    "autoredirect",
    "allowprev",
    "printanswers",
    "ipaddr",
    "ipanonymize",
    "refurl",
    "showsurveypolicynotice",
    "publicstatistics",
    "publicgraphs",
    "listpublic",
    "htmlemail",
    "sendconfirmation",
    "tokenanswerspersistence",
    "assessments",
    "usecaptcha",
    "tokenlength",
    "showxquestions",
    "showgroupinfo",
    "shownoanswer",
    "showqnumcode",
    "showwelcome",
    "showprogress",
    "questionindex",
    "navigationdelay",
    "nokeyboard",
    "alloweditaftercompletion",
    "access_mode",
)

_THEMES = {
    "N": "numerical",
    "S": "shortfreetext",
    "T": "longfreetext",
    "L": "listradio",
    "M": "multiplechoice",
    "F": "arrays/array",
    "D": "date",
    "X": "boilerplate",
    "*": "equation",
}

type Texts = dict[str, str]  # language -> LimeSurvey text (HTML + EM)


# --- Result -------------------------------------------------------------------------------


@dataclass(frozen=True)
class LssExport:
    """An export: the ``.lss`` bytes plus the metadata a researcher needs to read the data.

    - ``name_map``: our variable name (``name`` or ``id``) → LimeSurvey question code, for
      every question and variable. ``renamed`` is the subset whose code differs.
    - ``choice_codes``: our variable name → {our choice value as text: answer code}, only
      for questions where a code had to change.
    - ``helpers``: generated question codes (seeds, outcome, ...) → what they hold.
    """

    xml: bytes
    sid: int
    name_map: dict[str, str]
    renamed: dict[str, str]
    choice_codes: dict[str, dict[str, str]]
    helpers: dict[str, str]


# --- Public API ---------------------------------------------------------------------------


def export_lss(survey: Survey | Mapping[str, Any]) -> tuple[bytes, list[ExportDiagnostic]]:
    """Export a survey to LimeSurvey ``.lss`` XML bytes, with diagnostics.

    Returns ``(b"", diagnostics)`` with an ``error`` diagnostic if the survey is invalid or
    the exporter fails. Never raises on bad input.
    """
    result, diags = build_lss(survey)
    return (result.xml if result is not None else b""), diags


def build_lss(
    survey: Survey | Mapping[str, Any],
) -> tuple[LssExport | None, list[ExportDiagnostic]]:
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

    The key is refined to ``"<Def>.<field>=<value>"`` when the LSS table has such a row.
    Discriminators (``type``, ``kind``) always count as present and point at their object.
    Nothing inside an unsupported field is reported again: it is dropped as a whole.
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
            p = ptr + pointer(alias)
            key = f"{cls}.{alias}"
            if isinstance(value, (bool, int, str)):
                refined = f"{key}={str(value).lower() if isinstance(value, bool) else value}"
                if refined in LSS:
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
    cap = LSS.get(key)
    return cap.level if cap else None


# --- Intermediate structure ---------------------------------------------------------------


@dataclass
class _Item:
    """One parent question to write."""

    code: str
    type: str  # LimeSurvey type letter
    text: Texts
    help: Texts = field(default_factory=dict)
    relevance: str = TRUE
    mandatory: bool = False
    attributes: list[tuple[str, str, str | None]] = field(default_factory=list)
    answers: list[tuple[str, Texts]] = field(default_factory=list)  # (code, label)
    subquestions: list[tuple[str, Texts]] = field(default_factory=list)
    default: str | None = None
    qid: int = 0


@dataclass
class _Group:
    name: Texts
    description: Texts = field(default_factory=dict)
    relevance: str = TRUE
    items: list[_Item] = field(default_factory=list)
    randomization_group: str | None = None


# --- Exporter ------------------------------------------------------------------------------


class _Exporter:
    def __init__(self, survey: Survey) -> None:
        self.s = survey
        self.diags: list[ExportDiagnostic] = []
        self._seen: set[tuple[str, str]] = set()
        self.langs = list(survey.metadata.languages)
        self.base_lang = survey.metadata.defaultLanguage or self.langs[0]
        # Base language first: LimeSurvey's survey language, then the additional ones.
        self.langs = [self.base_lang, *[x for x in self.langs if x != self.base_lang]]
        self.groups: list[_Group] = []
        self.setup: list[_Item] = []
        self.taken: set[str] = set()
        self.codes: dict[str, str] = {}  # id -> question code
        self.types: dict[str, str] = {}  # id -> value type
        self.our_names: dict[str, str] = {}  # id -> our name
        self.choice_maps: dict[str, dict[str, str]] = {}  # id -> {our value: LS code}
        self.items: dict[str, _Item] = {}  # question id -> its item
        self.item_group: dict[str, int] = {}  # question/computed id -> group index
        self.blocks = {b.id: (i, b) for i, b in enumerate(survey.blocks)}
        self.ends: list[tuple[str, str]] = []  # (condition, outcome)
        self.helpers: dict[str, str] = {}
        self.quota_checks: list[tuple[str, str]] = []  # (pointer, quota id)
        self.dropped_quotas: list[int] = []
        self.em = EMWriter(EMContext(self.codes, self.types, self.choice_maps))

    # -- diagnostics ---------------------------------------------------------------------

    def note(self, feature: str, ptr: str, detail: str = "") -> None:
        cap: Capability | None = LSS.get(feature)
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
                    message=f"{feature} has no row in the LimeSurvey capability table; "
                    "it may not be exported",
                )
            )
            return
        if cap.level == "native" or (feature, ptr) in self._seen:
            return
        self._seen.add((feature, ptr))
        message = f"{feature} is {cap.level} in LimeSurvey: {cap.note}"
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
        """A free question code from ``base``: letters and digits, starting with a letter,
        at most 20 characters, not reserved, unique ignoring case."""
        stem = sanitise_code(base)
        name, n = stem, 1
        while name.lower() in self.taken or name.lower() in RESERVED_CODES:
            n += 1
            suffix = str(n)
            name = stem[: CODE_MAX - len(suffix)] + suffix
        self.taken.add(name.lower())
        return name

    def _helper(self, base: str, what: str) -> str:
        code = self._alloc(base)
        self.helpers[code] = what
        return code

    def _index(self) -> None:
        """Allocate a question code for every question and variable.

        Names that are already valid codes are taken first, so a rewritten name never
        takes one. Each rewrite is reported.
        """
        entries: list[tuple[str, str, str, str]] = []  # (id, our name, type, pointer)
        for bi, b in enumerate(self.s.blocks):
            for pi, page in enumerate(b.pages):
                for qi, q in enumerate(page.items):
                    ptr = pointer("blocks", bi, "pages", pi, "items", qi)
                    name = getattr(q, "name", None)
                    qtype = q.valueType if isinstance(q, SliderQuestion) else q.type
                    entries.append((q.id, name or q.id, qtype, ptr + ("/name" if name else "/id")))
        for vi, v in enumerate(self.s.variables):
            ptr = pointer("variables", vi) + ("/name" if v.name else "/id")
            if isinstance(v, EmbeddedVariable):
                vtype = v.valueType
            elif isinstance(v, AssignedVariable):
                vtype = "assigned"
            else:
                vtype = "boolean" if _is_condition(v.expr) else "decimal"
            entries.append((v.id, v.name or v.id, vtype, ptr))

        def valid(name: str) -> bool:
            return (
                bool(_CODE_OK.match(name))
                and len(name) <= CODE_MAX
                and name.lower() not in RESERVED_CODES
            )

        for _id, name, _t, _p in entries:
            if valid(name) and name.lower() not in self.taken:
                self.taken.add(name.lower())
                self.codes[_id] = name
        for _id, name, vtype, ptr in entries:
            self.types[_id] = vtype
            self.our_names[_id] = name
            if _id in self.codes:
                continue
            code = self._alloc(name)
            self.codes[_id] = code
            if sanitise_code(name).lower() in RESERVED_CODES:
                self.note("$names.reserved", ptr, f"{name} → {code}")
            else:
                self.note("$names.rename", ptr, f"{name} → {code}")
        self._matrix_rows()

    def _matrix_rows(self) -> None:
        """Each matrix row is a subquestion; Expression Manager names it `<q>_<sq>`, the
        variable of its own that our row `<matrix id>_<row id>` is (semantics §2, C2c-1)."""
        self.row_codes: dict[str, list[tuple[str, str]]] = {}  # matrix id -> [(row id, sq)]
        for q in _questions(self.s):
            if not isinstance(q, MatrixQuestion):
                continue
            used: set[str] = set()
            pairs: list[tuple[str, str]] = []
            for row in q.rows:
                stem = sanitise_code(row.id)
                sq, n = stem, 1
                while sq.lower() in used:
                    n += 1
                    sq = stem[: CODE_MAX - len(str(n))] + str(n)
                used.add(sq.lower())
                pairs.append((row.id, sq))
                rid = matrix_row_id(q.id, row.id)
                self.codes[rid] = f"{self.codes[q.id]}_{sq}"
                self.types[rid] = "single"
                self.our_names[rid] = matrix_row_name(q, row.id)
            self.row_codes[q.id] = pairs

    def _choice_codes(
        self, q: SingleQuestion | MultiQuestion | MatrixQuestion, ptr: str
    ) -> list[tuple[str, Choice]]:
        """(LimeSurvey code, choice) for each choice of ``q``; invalid codes are replaced."""
        if q.choiceList is not None:
            li = next(i for i, cl in enumerate(self.s.choiceLists) if cl.id == q.choiceList)
            choices = self.s.choiceLists[li].choices
            base = pointer("choiceLists", li, "choices")
        else:
            choices = q.choices or []
            base = ptr + "/choices"
        limit = ANSWER_CODE_MAX if isinstance(q, SingleQuestion | MatrixQuestion) else CODE_MAX
        ok = re.compile(rf"^[A-Za-z0-9]{{1,{limit}}}$")
        used = {str(c.value).lower() for c in choices if ok.match(str(c.value))}
        out: list[tuple[str, Choice]] = []
        mapping: dict[str, str] = {}
        n = 0
        for ci, c in enumerate(choices):
            value = str(c.value)
            code = value
            if not ok.match(value) or value.lower() in {o.lower() for o, _ in out}:
                while True:
                    n += 1
                    code = f"A{n}"
                    if code.lower() not in used:
                        break
                used.add(code.lower())
                self.note("$choice.code", base + pointer(ci, "value"), f"{value!r} → {code}")
            out.append((code, c))
            mapping[value] = code
        self.choice_maps[q.id] = mapping
        if isinstance(q, MatrixQuestion):
            for row in q.rows:
                self.choice_maps[matrix_row_id(q.id, row.id)] = mapping
        return out

    # -- text ----------------------------------------------------------------------------

    def _texts(self, text: object, ptr: str) -> Texts:
        """``{language: LimeSurvey HTML}``: plain strings escaped with `\\n` as `<br />`,
        rich text (RT2) as the HTML subset (RT4, `html.py`), pipes rewritten to Expression
        Manager."""
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

    @staticmethod
    def _paragraph(text: str) -> str:
        """A text as one paragraph of a longer LimeSurvey text: wrapped in `<p>` unless it
        is already block HTML (a rich value with more than one block)."""
        return text if is_block_html(text) else f"<p>{text}</p>"

    def _escape(self, s: str, ptr: str) -> str:
        if _CONTROL.search(s):
            self.note("$text.controlCharacters", ptr)
            s = _CONTROL.sub("", s)
        if _MARKUP.search(s):
            self.note("$text.markup", ptr)
        if "{" in s:
            self.note("$text.braces", ptr)
        s = html.escape(s, quote=False).replace("\n", "<br />")
        return s.replace("{", "\\{")

    def _render(self, s: str, ptr: str) -> str:
        out: list[str] = []
        pos = 0
        for m in _PIPE.finditer(s):
            out.append(self._escape(s[pos : m.start()], ptr))
            pos = m.end()
            out.append(self._pipe(m.group(1).strip(), ptr, m.group(0)))
        out.append(self._escape(s[pos:], ptr))
        return "".join(out)

    def _pipe(self, qid: str, ptr: str, raw: str | None = None) -> str:
        """The Expression Manager text for one `${qid}` (`raw` is how it was written, kept
        as escaped text when the id is unknown), with the piping diagnostics at `ptr`."""
        if qid.startswith("$"):
            # Built-ins ($trial, $position.*; semantics §8) are our runtime's.
            self.note("$pipe.builtin", ptr, f"${{{qid}}}")
            return ""
        if qid not in self.codes:
            return self._escape(raw if raw is not None else "${" + qid + "}", ptr)
        code = self.codes[qid]
        kind = self.types.get(qid)
        if kind == "single":
            self.note("$pipe.choiceLabel", ptr, f"${{{qid}}}")
            return f"{{{code}.shown}}"
        if kind == "multi":
            self.note("$pipe.multi", ptr, f"${{{qid}}}")
            return "{" + self.em.value(Ref(id=qid)) + "}"
        return f"{{{code}}}"

    def _all_langs(self, s: str) -> Texts:
        return {lang: s for lang in self.langs}

    # -- run -----------------------------------------------------------------------------

    def run(self) -> tuple[LssExport, list[ExportDiagnostic]]:
        for key, ptr, _value in feature_uses(self.s):
            self.note(key, ptr)
        self._index()
        self._variables()
        self._walk(self.s.flow, TRUE, "/flow")
        self._computed()
        self._outcome()
        self._place_setup()
        if any(not isinstance(q, NoteQuestion) for q in _questions(self.s)):
            self.note("$missingStates", "")
        sid = 100000 + zlib.crc32(self.s.id.encode("utf-8")) % 900000
        tables = self._tables(sid)
        self._drop_quota_notes()
        result = self._result(sid, tables)
        return result, self.diags

    def _result(self, sid: int, tables: list[Table]) -> LssExport:
        name_map = {self.our_names[i]: self.codes[i] for i in self.our_names}
        renamed = {k: v for k, v in name_map.items() if k != v}
        choice_codes = {
            self.our_names[qid]: {k: v for k, v in m.items() if k != v}
            for qid, m in self.choice_maps.items()
            if any(k != v for k, v in m.items())
        }
        comment = "Exported by Open Survey Platform (osp-targets lss)."
        if renamed:
            comment += " Renamed question codes: " + ", ".join(
                f"{k}={v}" for k, v in renamed.items()
            )
        xml = write_document(
            [("LimeSurveyDocType", "Survey"), ("DBVersion", DB_VERSION)],
            self.langs,
            tables,
            comment,
        )
        return LssExport(xml, sid, name_map, renamed, choice_codes, dict(self.helpers))

    # -- variables -----------------------------------------------------------------------

    def _variables(self) -> None:
        for v in self.s.variables:
            if isinstance(v, EmbeddedVariable):
                code = self.codes[v.id]
                item = _Item(
                    code=code,
                    type="S",
                    text=self._all_langs(code),
                    attributes=[("hidden", "1", None)],
                    default=None if v.default is None else str(v.default),
                )
                self.items[v.id] = item
                self.setup.append(item)
            # Assigned variables are emitted at their assign node, computed ones after
            # the walk (in the group of their last input).

    def _equation(self, code: str, expr: str) -> _Item:
        return _Item(
            code=code,
            type="*",
            text=self._all_langs("{" + expr + "}"),
            attributes=[("hidden", "1", None)],
        )

    def _latched_draw(self, code: str, upper: int) -> _Item:
        """A random integer in 1..upper drawn once and then kept (spike-1 Q7)."""
        ref = f"{code}.NAOK"
        return self._equation(code, f"if(!is_empty({ref}), {ref}, rand(1, {upper}))")

    def _computed(self) -> None:
        by_id = {v.id: v for v in self.s.variables}
        placed: dict[str, int] = {}

        def position(vid: str) -> int:
            if vid in placed:
                return placed[vid]
            v = by_id.get(vid)
            if isinstance(v, ComputedVariable):
                placed[vid] = -1  # cycle guard (the validator rejects cycles)
                placed[vid] = max((position(r) for r in references(v.expr)), default=-1)
                return placed[vid]
            return self.item_group.get(vid, -1)

        for v in self.s.variables:
            if not isinstance(v, ComputedVariable):
                continue
            item = self._equation(self.codes[v.id], self.em.value(v.expr))
            self.items[v.id] = item
            at = position(v.id)
            if at < 0:
                self.setup.append(item)
            else:
                self.groups[at].items.append(item)
                self.item_group[v.id] = at

    # -- flow ----------------------------------------------------------------------------

    def _walk(self, nodes: list[Any], alive: str, ptr: str) -> str:
        """Emit ``nodes`` reachable under ``alive``; return the condition to continue."""
        for i, node in enumerate(nodes):
            p = ptr + pointer(i)
            match node:
                case BlockNode():
                    self._block(node.block, alive)
                case BranchNode():
                    c = self.em.condition(node.if_)
                    then_in, else_in = and_(alive, c), and_(alive, not_(c))
                    a = self._walk(node.then, then_in, p + "/then")
                    b = self._walk(node.else_, else_in, p + "/else")
                    if (a, b) != (then_in, else_in):
                        alive = or_(a, b)
                case RandomiserNode():
                    alive = self._randomiser(node, alive, p)
                case AssignNode():
                    self._assign(node)
                case QuotaCheckNode():
                    # LimeSurvey checks quotas itself; reported by the capability walk.
                    self.quota_checks.append((p, node.quota))
                case EndNode():
                    self._end(node, alive, p)
                    alive = FALSE
        return alive

    def _one_page_block(self, node: object) -> bool:
        if not isinstance(node, BlockNode) or node.block not in self.blocks:
            return False
        return len(self.blocks[node.block][1].pages) == 1

    def _randomiser(self, node: RandomiserNode, alive: str, ptr: str) -> str:
        children = node.children
        shuffle = len(children) > 1 and all(self._one_page_block(c) for c in children)
        group_name = f"osprand{sanitise_code(node.id)}" if shuffle else None
        if not shuffle and len(children) > 1:
            self.note(
                "RandomiserNode.children",
                ptr + "/children",
                "children are not all one-page blocks: shown in document order",
            )
        pick = node.pick
        if pick is None or pick >= len(children):
            for k, child in enumerate(children):
                start = len(self.groups)
                alive = self._walk([child], alive, ptr + pointer("children", k))
                self._mark_random(start, group_name)
            return alive
        draws = [
            self._helper(f"osp{node.id}{k + 1}", f"randomiser {node.id}: draw for child {k + 1}")
            for k in range(len(children))
        ]
        for code in draws:
            self.setup.append(self._latched_draw(code, _LATCH_MAX))
        for k, child in enumerate(children):
            # Rank by draw, ties broken by position: exactly `pick` children are chosen.
            beats = [
                f"if({draws[j]}.NAOK {'>=' if j < k else '>'} {draws[k]}.NAOK, 1, 0)"
                for j in range(len(children))
                if j != k
            ]
            chosen = f"{' + '.join(beats)} < {pick}"
            child_in = and_(alive, chosen)
            start = len(self.groups)
            out = self._walk([child], child_in, ptr + pointer("children", k))
            self._mark_random(start, group_name)
            if out != child_in:
                alive = or_(out, and_(alive, not_(chosen)))
        return alive

    def _mark_random(self, start: int, group_name: str | None) -> None:
        if group_name is None:
            return
        for g in self.groups[start:]:
            g.randomization_group = group_name

    def _assign(self, node: AssignNode) -> None:
        by_id = {v.id: v for v in self.s.variables}
        for vid in node.variables:
            v = by_id.get(vid)
            if not isinstance(v, AssignedVariable) or vid in self.items:
                continue
            code = self.codes[vid]
            seed = self._helper(f"ospseed{code}", f"assignment draw for {self.our_names[vid]}")
            self.setup.append(self._latched_draw(seed, len(v.levels)))
            expr = EMPTY
            for k in reversed(range(len(v.levels))):
                expr = f"if({seed}.NAOK == {k + 1}, {string_literal(str(v.levels[k]))}, {expr})"
            item = self._equation(code, expr)
            self.items[vid] = item
            self.setup.append(item)

    def _end(self, node: EndNode, alive: str, ptr: str) -> None:
        self.ends.append((alive, node.outcome))
        if alive == FALSE:
            return
        items: list[_Item] = []
        if node.message is not None:
            code = self._helper(f"ospend{node.id}", f"end message ({node.id})")
            items.append(
                _Item(code=code, type="X", text=self._texts(node.message, ptr + "/message"))
            )
        # EN1: another outcome's ending goes with each End node that has it (LimeSurvey has
        # one end text, which the `complete` ending fills).
        ending = {} if node.outcome == "complete" else self._ending_texts(node.outcome)
        if ending:
            code = self._helper(f"ospending{node.id}", f"ending ({node.outcome})")
            items.append(_Item(code=code, type="X", text=ending))
        if items:
            self.groups.append(_Group(name=self._all_langs(node.id), relevance=alive, items=items))

    def _redirect(self, outcome: str) -> _Redirect | None:
        """An outcome's end redirect (EN2) as LimeSurvey can hold it: the template URL with
        its literal params percent-encoded, whether to load it automatically, and the link
        text per language. None when the outcome has no redirect, or when a param is piped
        (LimeSurvey cannot re-check a value against its pattern, so the redirect is a loss)."""
        ending = self.s.settings.endings.get(outcome)
        if ending is None or ending.redirect is None:
            return None
        r = ending.redirect
        ptr = pointer("settings", "endings", outcome, "redirect")
        template = redirect_templates(self.s).get(r.template)
        if template is None:
            return None  # the validator's redirect.unknown_template already blocks publishing
        self.note("Ending.redirect", ptr)
        self.note("EndRedirect.template", ptr + "/template")
        if any(_PIPE.search(v) for v in r.params.values()):
            self.note("$redirect.piped", ptr + "/params")
            return None
        url = template.url
        for name in placeholders(template.url):
            value = r.params.get(name, "")
            pattern = (template.params.get(name) or _NO_PATTERN).pattern or DEFAULT_PARAM_PATTERN
            if not re.fullmatch(f"(?:{pattern})", value) or value in (".", ".."):
                return None  # the validator's redirect.param_literal already blocks publishing
            url = url.replace("{" + name + "}", _percent_encode(value))
        if r.mode == "auto":
            self.note("EndRedirect.delay", ptr + "/delay")
        label = self._texts(r.label, ptr + "/label") if r.label is not None else {}
        return _Redirect(url=url, auto=r.mode == "auto", label=label)

    def _ending_texts(self, outcome: str) -> Texts:
        """An outcome's ending (EN1) as one LimeSurvey text per language: the title, then the
        body, each a paragraph. Empty when the outcome has no ending text."""
        ending = self.s.settings.endings.get(outcome)
        if ending is None:
            return {}
        parts: dict[str, list[str]] = {lang: [] for lang in self.langs}
        for key in ("title", "body"):
            ptr = pointer("settings", "endings", outcome, key)
            for lang, t in self._texts(getattr(ending, key), ptr).items():
                parts[lang].append(self._paragraph(t))
        return {lang: "".join(ps) for lang, ps in parts.items() if ps}

    def _outcome(self) -> None:
        if not any(o != "complete" for _c, o in self.ends):
            return
        calc = string_literal("complete")
        for cond, outcome in reversed(self.ends):
            if cond == FALSE or outcome == "complete":
                continue
            calc = (
                string_literal(outcome)
                if cond == TRUE
                else f"if({cond}, {string_literal(outcome)}, {calc})"
            )
        code = self._helper("ospoutcome", "end outcome (EndNode.outcome)")
        self.groups.append(
            _Group(name=self._all_langs("ospoutcome"), items=[self._equation(code, calc)])
        )

    def _place_setup(self) -> None:
        """Embedded variables and random draws go first: into the first group when it is
        always shown and not shuffled, otherwise into a group of their own."""
        if not self.setup:
            return
        first = self.groups[0] if self.groups else None
        if first is not None and first.relevance == TRUE and first.randomization_group is None:
            first.items[:0] = self.setup
        else:
            self.groups.insert(0, _Group(name=self._all_langs("ospsetup"), items=self.setup))

    # -- blocks, pages, questions --------------------------------------------------------

    def _block(self, block_id: str, alive: str) -> None:
        if block_id not in self.blocks:
            return
        bi, block = self.blocks[block_id]
        assert isinstance(block, Block)
        for pi, page in enumerate(block.pages):
            pptr = pointer("blocks", bi, "pages", pi)
            # A formatted title (RT2) is HTML in the description; the group name, which
            # LimeSurvey shows as plain text, gets the text without the tags.
            title = self._texts(page.title, pptr + "/title")
            if _any_rich(page.title):
                name = {lang: _TAGS.sub("", t.replace("<br />", " ")) for lang, t in title.items()}
            else:
                name = title if page.title is not None else self._all_langs(page.id)
            group = _Group(
                name=name,
                description=title,
                relevance=alive
                if page.showIf is None
                else and_(alive, self.em.condition(page.showIf)),
            )
            index = len(self.groups)
            self.groups.append(group)
            for qi, q in enumerate(page.items):
                item = self._question(q, pptr + pointer("items", qi))
                if page.itemOrder == "shuffle":
                    item.attributes.append(
                        ("random_group", f"osppage{sanitise_code(page.id)}", None)
                    )
                group.items.append(item)
                self.items[q.id] = item
                self.item_group[q.id] = index

    def _question(self, q: Any, ptr: str) -> _Item:
        code = self.codes[q.id]
        item = _Item(code=code, type="", text=self._texts(q.label, ptr + "/label"))
        item.help = self._texts(q.help, ptr + "/help")
        match q:
            case IntegerQuestion():
                item.type = "N"
                item.attributes.append(("num_value_int_only", "1", None))
            case DecimalQuestion():
                item.type = "N"
            case TextQuestion():
                item.type = "T" if q.multiline else "S"
            case DateQuestion():
                item.type = "D"
            case NoteQuestion():
                item.type = "X"
            case SliderQuestion():
                # A number box: LimeSurvey's slider layout is only on type K (several
                # numbers), and its range is checked by validation below.
                item.type = "N"
                if q.valueType == "integer":
                    item.attributes.append(("num_value_int_only", "1", None))
            case MatrixQuestion():
                item.type = "F"
                item.answers = [
                    (c_code, self._texts(c.label, self._choice_ptr(q, ptr, i)))
                    for i, (c_code, c) in enumerate(self._choice_codes(q, ptr))
                ]
                labels = {r.id: r.label for r in q.rows}
                item.subquestions = [
                    (sq, self._texts(labels[rid], ptr + pointer("rows", k, "label")))
                    for k, (rid, sq) in enumerate(self.row_codes[q.id])
                ]
            case SingleQuestion() | MultiQuestion():
                item.type = "L" if isinstance(q, SingleQuestion) else "M"
                rows = [
                    (c_code, self._texts(c.label, self._choice_ptr(q, ptr, i)))
                    for i, (c_code, c) in enumerate(self._choice_codes(q, ptr))
                ]
                if isinstance(q, SingleQuestion):
                    item.answers = rows
                else:
                    item.subquestions = rows
                if q.choiceOrder == "shuffle":
                    item.attributes.append(("random_order", "1", None))
        if q.showIf is not None:
            item.relevance = self.em.condition(q.showIf)
        if isinstance(q, MatrixQuestion):
            self._matrix_required(q, item, ptr)
            return item
        if not isinstance(q, NoteQuestion):
            item.mandatory = q.required
            parts = [
                f"{code}.NAOK {op} {bound}"
                for op, bound in ((">=", getattr(q, "min", None)), ("<=", getattr(q, "max", None)))
                if bound is not None
            ]
            if isinstance(q, SliderQuestion):
                parts.append(f"fmod({code}.NAOK - ({q.min}), {q.step}) == 0")
            if q.constraint is not None:
                parts.append(self.em.condition(q.constraint))
            if parts:
                check = or_(f"is_empty({code}.NAOK)", and_(*parts))
                item.attributes.append(("em_validation_q", check, None))
            for lang, tip in self._texts(q.constraintMessage, ptr + "/constraintMessage").items():
                item.attributes.append(("em_validation_q_tip", tip, lang))
        return item

    def _matrix_required(self, q: MatrixQuestion, item: _Item, ptr: str) -> None:
        """`mandatory` is per question in LimeSurvey: all rows required → Y; only some →
        a validation that the required rows are answered (only while relevant)."""
        flags = [matrix_row_required(q, r) for r in q.rows]
        if all(flags):
            item.mandatory = True
        elif any(flags):
            self.note("$matrix.someRowsRequired", ptr + "/rows")
            needed = [
                f"!is_empty({item.code}_{sq}.NAOK)"
                for (_rid, sq), flag in zip(self.row_codes[q.id], flags, strict=True)
                if flag
            ]
            item.attributes.append(("em_validation_q", and_(*needed), None))

    def _choice_ptr(
        self, q: SingleQuestion | MultiQuestion | MatrixQuestion, ptr: str, i: int
    ) -> str:
        if q.choiceList is None:
            return ptr + pointer("choices", i, "label")
        li = next(k for k, cl in enumerate(self.s.choiceLists) if cl.id == q.choiceList)
        return pointer("choiceLists", li, "choices", i, "label")

    # -- quotas --------------------------------------------------------------------------

    def _quota_members(self, e: Expr) -> dict[str, list[str]] | None:
        """{question id: [answer codes]} for a condition LimeSurvey quotas can express."""
        match e:
            case (
                Compare(op="==", left=Ref(id=rid), right=lit)
                | Compare(op="==", left=lit, right=Ref(id=rid))
            ) if isinstance(lit, (IntLit, TextLit, DecLit)):
                if self.types.get(rid) != "single":
                    return None
                code = self.choice_maps.get(rid, {}).get(_literal_text(lit))
                return {rid: [code]} if code is not None else None
            case Contains(ref=Ref(id=rid), value=lit) if isinstance(lit, (IntLit, TextLit)):
                if self.types.get(rid) != "multi":
                    return None
                code = self.choice_maps.get(rid, {}).get(_literal_text(lit))
                return {rid: [code]} if code is not None else None
            case Or(args=args):
                parts = [self._quota_members(a) for a in args]
                if any(p is None for p in parts):
                    return None
                qids = {q for p in parts if p for q in p}
                if len(qids) != 1:
                    return None
                (qid,) = qids
                return {qid: [c for p in parts if p for c in p[qid]]}
            case And(args=args):
                merged: dict[str, list[str]] = {}
                for a in args:
                    part = self._quota_members(a)
                    if part is None or set(part) & set(merged):
                        return None
                    merged.update(part)
                return merged
        return None

    def _quota_message(self, block_id: str | None) -> Texts:
        if block_id is None or block_id not in self.blocks:
            return {}
        bi, block = self.blocks[block_id]
        parts: dict[str, list[str]] = {lang: [] for lang in self.langs}
        for pi, page in enumerate(block.pages):
            for qi, q in enumerate(page.items):
                ptr = pointer("blocks", bi, "pages", pi, "items", qi, "label")
                for lang, t in self._texts(q.label, ptr).items():
                    parts[lang].append(self._paragraph(t))
        return {lang: "".join(p) for lang, p in parts.items() if p}

    # -- tables --------------------------------------------------------------------------

    def _tables(self, sid: int) -> list[Table]:
        groups = Table("groups", ("gid", "sid", "group_order", "randomization_group", "grelevance"))
        group_l10ns = Table("group_l10ns", ("id", "gid", "group_name", "description", "language"))
        questions = Table("questions", QUESTION_FIELDS)
        subquestions = Table("subquestions", QUESTION_FIELDS)
        question_l10ns = Table(
            "question_l10ns", ("id", "qid", "question", "help", "script", "language")
        )
        attributes = Table("question_attributes", ("qid", "attribute", "value", "language"))
        answers = Table(
            "answers", ("aid", "qid", "code", "sortorder", "assessment_value", "scale_id")
        )
        answer_l10ns = Table("answer_l10ns", ("id", "aid", "answer", "language"))
        defaults = Table("defaultvalues", ("dvid", "qid", "scale_id", "sqid", "specialtype"))
        default_l10ns = Table("defaultvalue_l10ns", ("id", "dvid", "language", "defaultvalue"))
        quota = Table("quota", ("id", "sid", "name", "qlimit", "action", "active", "autoload_url"))
        quota_members = Table("quota_members", ("id", "sid", "qid", "quota_id", "code"))
        quota_l10ns = Table(
            "quota_languagesettings",
            (
                "quotals_id",
                "quotals_quota_id",
                "quotals_language",
                "quotals_name",
                "quotals_message",
                "quotals_url",
                "quotals_urldescrip",
            ),
        )

        next_qid = iter(range(1, 1_000_000))
        next_ql = iter(range(1, 1_000_000))
        next_gl = iter(range(1, 1_000_000))
        next_aid = iter(range(1, 1_000_000))
        next_al = iter(range(1, 1_000_000))
        next_dv = iter(range(1, 1_000_000))
        next_dl = iter(range(1, 1_000_000))

        def question_row(table: Table, **values: Any) -> None:
            base = {
                "parent_qid": 0,
                "sid": sid,
                "preg": None,
                "other": "N",
                "mandatory": "N",
                "encrypted": "N",
                "scale_id": 0,
                "same_default": 0,
                "relevance": TRUE,
                "question_theme_name": None,
                "modulename": None,
                "same_script": 0,
            }
            table.add(**(base | values))

        for gi, g in enumerate(self.groups):
            gid = gi + 1
            groups.add(
                gid=gid,
                sid=sid,
                group_order=gi,
                randomization_group=g.randomization_group,
                grelevance=g.relevance,
            )
            for lang in self.langs:
                group_l10ns.add(
                    id=next(next_gl),
                    gid=gid,
                    group_name=g.name.get(lang, ""),
                    description=g.description.get(lang),
                    language=lang,
                )
            for order, item in enumerate(g.items):
                qid = next(next_qid)
                item.qid = qid
                question_row(
                    questions,
                    qid=qid,
                    gid=gid,
                    type=item.type,
                    title=item.code,
                    mandatory="Y" if item.mandatory else "N",
                    question_order=order + 1,
                    relevance=item.relevance,
                    question_theme_name=_THEMES[item.type],
                )
                for lang in self.langs:
                    question_l10ns.add(
                        id=next(next_ql),
                        qid=qid,
                        question=item.text.get(lang, ""),
                        help=item.help.get(lang),
                        script=None,
                        language=lang,
                    )
                for attr, value, lang in item.attributes:
                    attributes.add(qid=qid, attribute=attr, value=value, language=lang)
                for so, (code, label) in enumerate(item.answers):
                    aid = next(next_aid)
                    answers.add(
                        aid=aid, qid=qid, code=code, sortorder=so, assessment_value=0, scale_id=0
                    )
                    for lang in self.langs:
                        answer_l10ns.add(
                            id=next(next_al), aid=aid, answer=label.get(lang, ""), language=lang
                        )
                for so, (code, label) in enumerate(item.subquestions):
                    sqid = next(next_qid)
                    question_row(
                        subquestions,
                        qid=sqid,
                        parent_qid=qid,
                        gid=gid,
                        type="T",
                        title=code,
                        question_order=so + 1,
                    )
                    for lang in self.langs:
                        question_l10ns.add(
                            id=next(next_ql),
                            qid=sqid,
                            question=label.get(lang, ""),
                            help=None,
                            script=None,
                            language=lang,
                        )
                if item.default is not None:
                    dvid = next(next_dv)
                    defaults.add(dvid=dvid, qid=qid, scale_id=0, sqid=0, specialtype=None)
                    for lang in self.langs:
                        default_l10ns.add(
                            id=next(next_dl),
                            dvid=dvid,
                            language=lang,
                            defaultvalue=item.default,
                        )

        self._quota_tables(sid, quota, quota_members, quota_l10ns)

        end_redirect = self._redirect("complete")  # EN2: the `complete` ending's redirect
        survey = Table("surveys", SURVEY_FIELDS)
        survey.add(**self._survey_row(sid, end_redirect))
        l10n_fields = (
            "surveyls_survey_id",
            "surveyls_language",
            "surveyls_title",
            "surveyls_description",
            "surveyls_welcometext",
            "surveyls_endtext",
            "surveyls_dateformat",
            "surveyls_numberformat",
        )
        if end_redirect is not None:  # the URL columns only when there is one to write
            l10n_fields += ("surveyls_url", "surveyls_urldescription")
        survey_l10ns = Table("surveys_languagesettings", l10n_fields)
        titles = self._texts(self.s.metadata.title, "/metadata/title")
        descriptions = self._texts(self.s.metadata.description, "/metadata/description")
        end_texts = self._ending_texts("complete")  # EN1: the `complete` ending
        for lang in self.langs:
            row: dict[str, Any] = {
                "surveyls_survey_id": sid,
                "surveyls_language": lang,
                "surveyls_title": titles.get(lang, ""),
                "surveyls_description": descriptions.get(lang),
                "surveyls_welcometext": None,
                "surveyls_endtext": end_texts.get(lang),
                "surveyls_dateformat": 1,
                "surveyls_numberformat": 0,
            }
            if end_redirect is not None:
                row["surveyls_url"] = end_redirect.url
                row["surveyls_urldescription"] = end_redirect.label.get(lang)
            survey_l10ns.add(**row)
        return [
            groups,
            group_l10ns,
            questions,
            subquestions,
            question_l10ns,
            attributes,
            answers,
            answer_l10ns,
            defaults,
            default_l10ns,
            quota,
            quota_members,
            quota_l10ns,
            survey,
            survey_l10ns,
        ]

    def _drop_quota_notes(self) -> None:
        """A dropped quota is reported once (``Quota.when=unmappable``), not field by field;
        a check of it is reported as ``$quota.dropped``."""
        if not self.dropped_quotas:
            return
        prefixes = tuple(pointer("quotas", i) for i in self.dropped_quotas)
        dropped_ids = {self.s.quotas[i].id for i in self.dropped_quotas}
        checks = {p for p, qid in self.quota_checks if qid in dropped_ids}
        kept: list[ExportDiagnostic] = []
        for d in self.diags:
            under_quota = d.pointer in prefixes or d.pointer.startswith(
                tuple(x + "/" for x in prefixes)
            )
            if under_quota and d.feature != "Quota.when=unmappable":
                continue
            if d.feature.startswith("QuotaCheckNode.") and (
                d.pointer in checks or d.pointer.rsplit("/", 1)[0] in checks
            ):
                continue
            kept.append(d)
        self.diags = kept
        for p in sorted(checks):
            self.note("$quota.dropped", p)

    def _quota_tables(self, sid: int, quota: Table, members: Table, l10ns: Table) -> None:
        member_id = 0
        for i, qu in enumerate(self.s.quotas):
            found = self._quota_members(qu.when)
            if not found or any(qid not in self.items for qid in found):
                self.note("Quota.when=unmappable", pointer("quotas", i, "when"))
                self.dropped_quotas.append(i)
                continue
            quota_id = len(quota.rows) + 1
            redirect = self._redirect(qu.onFull.outcome)  # EN2: the quota outcome's redirect
            quota.add(
                id=quota_id,
                sid=sid,
                name=qu.id,
                qlimit=qu.limit,
                action=1,
                active=1,
                autoload_url=1 if redirect is not None and redirect.auto else 0,
            )
            for qid, codes in found.items():
                for code in codes:
                    member_id += 1
                    members.add(
                        id=member_id, sid=sid, qid=self.items[qid].qid, quota_id=quota_id, code=code
                    )
            # EN1: the quota outcome's ending is the quota message; else the onFull block.
            message = self._ending_texts(qu.onFull.outcome) or self._quota_message(qu.onFull.block)
            for lang in self.langs:
                l10ns.add(
                    quotals_id=len(l10ns.rows) + 1,
                    quotals_quota_id=quota_id,
                    quotals_language=lang,
                    quotals_name=qu.id,
                    quotals_message=message.get(lang) or _QUOTA_FULL,
                    quotals_url=redirect.url if redirect is not None else None,
                    quotals_urldescrip=redirect.label.get(lang) if redirect is not None else None,
                )

    def _survey_row(self, sid: int, end_redirect: _Redirect | None = None) -> dict[str, Any]:
        return {
            "sid": sid,
            "gsid": 1,
            "admin": None,
            "adminemail": None,
            "anonymized": "N",
            "format": "G",
            "savetimings": "N",
            "template": "fruity_twentythree",
            "language": self.base_lang,
            "additional_languages": " ".join(self.langs[1:]) or None,
            "datestamp": "N",
            "usecookie": "N",
            "allowregister": "N",
            "allowsave": "N",
            "autonumber_start": 0,
            "autoredirect": "Y" if end_redirect is not None and end_redirect.auto else "N",
            "allowprev": "Y" if self.s.settings.backNavigation else "N",
            "printanswers": "N",
            "ipaddr": "N",
            "ipanonymize": "Y",
            "refurl": "N",
            "showsurveypolicynotice": 0,
            "publicstatistics": "N",
            "publicgraphs": "N",
            "listpublic": "N",
            "htmlemail": "N",
            "sendconfirmation": "N",
            "tokenanswerspersistence": "N",
            "assessments": "N",
            "usecaptcha": "N",
            "tokenlength": 15,
            "showxquestions": "N",
            "showgroupinfo": "D",
            "shownoanswer": "N",
            "showqnumcode": "X",
            "showwelcome": "N",
            "showprogress": "Y",
            "questionindex": 0,
            "navigationdelay": 0,
            "nokeyboard": "N",
            "alloweditaftercompletion": "N",
            "access_mode": "O",
        }


def sanitise_code(name: str) -> str:
    """``name`` as a LimeSurvey question code: letters and digits only, starting with a
    letter, at most 20 characters. Not checked for reserved words or uniqueness."""
    s = re.sub(r"[^A-Za-z0-9]", "", name)
    if not s or not s[0].isalpha():
        s = "q" + s
    return s[:CODE_MAX]


def _any_rich(text: object) -> bool:
    """Whether a `Text` holds a rich value (as a whole or in any language)."""
    text = as_json(text)
    if is_rich(text):
        return True
    return isinstance(text, dict) and any(is_rich(v) for v in text.values())


def _literal_text(lit: Expr) -> str:
    if isinstance(lit, DecLit):
        return format(lit.value, "f")
    assert isinstance(lit, (IntLit, TextLit))
    return str(lit.value)


def _is_condition(e: Expr) -> bool:
    return isinstance(e, (Compare, And, Or, Not, Answered, Contains, BoolLit))


def _questions(s: Survey) -> Iterator[Any]:
    for b in s.blocks:
        for page in b.pages:
            yield from page.items


__all__ = [
    "RESERVED_CODES",
    "LssExport",
    "build_lss",
    "export_lss",
    "feature_uses",
    "sanitise_code",
]
