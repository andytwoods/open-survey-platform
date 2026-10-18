"""``osp-survey`` → SurveyJS survey JSON (task XP1).

Pipeline (planning/review.md §2.4): validate → walk the model for capability diagnostics
→ name every question and variable → lower the flow tree into page ``visibleIf``
conditions and conditional completion texts → write the JSON. Each page becomes one
SurveyJS page; blocks are consecutive pages. Every feature the capability table marks as
non-native produces a diagnostic with a JSON pointer; :func:`export_surveyjs` never raises.

Clean-room: written from the public SurveyJS documentation of the survey JSON and our own
importer (``osp_targets/imports/surveyjs.py``), which reads the result back. No SurveyJS
code.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from osp_expr.ast import Expr
from osp_spec import Survey, is_rich, parse, redirect_templates
from osp_spec.hooks import DEFAULT_PARAM_PATTERN, placeholders
from osp_spec.model import (
    AssignedVariable,
    BlockNode,
    BranchNode,
    Choice,
    ComputedVariable,
    DateQuestion,
    DecimalQuestion,
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
    matrix_row_required,
)
from osp_spec.richtext import features, to_plain
from pydantic import BaseModel

from ..capabilities.base import Capability
from ..diagnostics import SEVERITY_FOR_LEVEL, ExportDiagnostic, pointer
from ..lss.html import is_block_html, to_html
from ..richtext import as_json
from .capabilities import SURVEYJS
from .expr import FALSE, TRUE, SjsContext, SjsWriter, Unmappable, and_, not_, or_, string_literal

TARGET = "surveyjs"

_PIPE = re.compile(r"\$\{([^}]*)\}")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_MARKUP = re.compile(r"[&<>]")
_WHOLE_NUMBER = "^-?[0-9]+$"
_URL_SAFE = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.!~*'()")
_OUTCOME = "osp_outcome"

# A SurveyJS localisable string: one text, or {"default": …, "<lang>": …}.
type Loc = str | dict[str, str]


def _percent_encode(value: str) -> str:
    """`encodeURIComponent(value)`, as the participant app fills a redirect template."""
    return "".join(
        c if c in _URL_SAFE else "".join(f"%{b:02X}" for b in c.encode("utf-8")) for c in value
    )


class _NoPattern:
    pattern: str | None = None


_NO_PATTERN = _NoPattern()


@dataclass(frozen=True)
class SurveyJsExport:
    """An export: the JSON bytes, the same document as a dict, and the metadata a
    researcher needs to read the data.

    - ``name_map``: our variable name → the SurveyJS data key (identical: SurveyJS takes
      our names as they are; a matrix row is ``<matrix>.<row>`` inside the matrix's
      answer object).
    - ``helpers``: generated names (``osp_outcome``) → what they hold.
    """

    json: bytes
    document: dict[str, Any]
    name_map: dict[str, str]
    helpers: dict[str, str]


# --- Public API ---------------------------------------------------------------------------


def export_surveyjs(survey: Survey | Mapping[str, Any]) -> tuple[bytes, list[ExportDiagnostic]]:
    """Export a survey to SurveyJS survey JSON bytes, with diagnostics.

    Returns ``(b"", diagnostics)`` with an ``error`` diagnostic if the survey is invalid or
    the exporter fails. Never raises on bad input.
    """
    result, diags = build_surveyjs(survey)
    return (result.json if result is not None else b""), diags


def build_surveyjs(
    survey: Survey | Mapping[str, Any],
) -> tuple[SurveyJsExport | None, list[ExportDiagnostic]]:
    """The export with its name table, and diagnostics."""
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

    The key is refined to ``"<Def>.<field>=<value>"`` when the table has such a row.
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
                if refined in SURVEYJS:
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
    cap = SURVEYJS.get(key)
    return cap.level if cap else None


# --- Exporter ------------------------------------------------------------------------------


@dataclass
class _End:
    condition: str
    html: Loc | None
    url: str | None
    fallback: bool = False  # the end of the flow: what SurveyJS shows when no entry matches


@dataclass
class _Flow:
    pages: list[dict[str, Any]] = field(default_factory=list)
    ends: list[_End] = field(default_factory=list)
    outcomes: list[tuple[str, str]] = field(default_factory=list)  # (condition, outcome)


class _Exporter:
    def __init__(self, survey: Survey) -> None:
        self.s = survey
        self.diags: list[ExportDiagnostic] = []
        self._seen: set[tuple[str, str]] = set()
        langs = list(survey.metadata.languages)
        self.base_lang = survey.metadata.defaultLanguage or langs[0]
        self.langs = [self.base_lang, *[x for x in langs if x != self.base_lang]]
        self.names: dict[str, str] = {}  # id -> SurveyJS name inside braces
        self.types: dict[str, str] = {}  # id -> question type or variable kind
        self.our_names: dict[str, str] = {}  # our variable name -> SurveyJS data key
        self.taken: set[str] = set()
        self.helpers: dict[str, str] = {}
        self.blocks = {b.id: (i, b) for i, b in enumerate(survey.blocks)}
        self.emitted: set[str] = set()
        self.flow = _Flow()
        self.sjs = SjsWriter(SjsContext(self.names, self.types))

    # -- diagnostics ---------------------------------------------------------------------

    def note(self, feature: str, ptr: str, detail: str = "") -> None:
        cap: Capability | None = SURVEYJS.get(feature)
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
                    message=f"{feature} has no row in the SurveyJS capability table; "
                    "it may not be exported",
                )
            )
            return
        if cap.level == "native" or (feature, ptr) in self._seen:
            return
        self._seen.add((feature, ptr))
        message = f"{feature} is {cap.level} in SurveyJS: {cap.note}"
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

    def _index(self) -> None:
        """Name every question, matrix row and variable. SurveyJS takes our names as they
        are (the validator already keeps them unique ignoring case)."""
        for b in self.s.blocks:
            for page in b.pages:
                for q in page.items:
                    name = getattr(q, "name", None) or q.id
                    self.taken.add(name.lower())
                    self.names[q.id] = name
                    self.types[q.id] = q.type
                    if isinstance(q, MatrixQuestion):
                        for row in q.rows:
                            rid = matrix_row_id(q.id, row.id)
                            self.names[rid] = f"{name}.{row.id}"
                            self.types[rid] = "single"
                            self.our_names[f"{name}_{row.id}"] = f"{name}.{row.id}"
                    elif not isinstance(q, NoteQuestion):
                        self.our_names[name] = name
        for v in self.s.variables:
            name = v.name or v.id
            self.taken.add(name.lower())
            self.types[v.id] = v.kind
            if isinstance(v, AssignedVariable):
                continue  # unsupported: references to it are unmappable
            self.names[v.id] = name
            self.our_names[name] = name

    def _helper(self, base: str, what: str) -> str:
        name, n = base, 1
        while name.lower() in self.taken:
            n += 1
            name = f"{base}{n}"
        self.taken.add(name.lower())
        self.helpers[name] = what
        return name

    # -- text ----------------------------------------------------------------------------

    def _loc(self, text: object, ptr: str, *, rich_html: bool = False) -> Loc | None:
        """A `Text` as a SurveyJS localisable string: one string when it is the same in
        every language, else ``{"default": …, "<lang>": …}`` with only the languages it
        has (SurveyJS falls back to the default). ``rich_html``: the field shows HTML
        (notes, completion texts); otherwise rich text is flattened to plain text."""
        text = as_json(text)
        if text is None:
            return None
        if isinstance(text, str) or is_rich(text):
            return self._render(text, ptr, rich_html)
        assert isinstance(text, dict)
        base = text.get(self.base_lang)
        base_ptr = ptr + pointer(self.base_lang)
        if base is None:
            first = next(iter(text), None)
            if first is None:
                return ""
            base, base_ptr = text[first], ptr + pointer(first)
        out: dict[str, str] = {"default": self._render(base, base_ptr, rich_html)}
        for lang in self.langs[1:]:
            if lang in text:
                out[lang] = self._render(text[lang], ptr + pointer(lang), rich_html)
        return out["default"] if len(out) == 1 else out

    def _render(self, value: object, ptr: str, rich_html: bool) -> str:
        if is_rich(value):
            assert isinstance(value, dict)
            if rich_html:
                return to_html(
                    value,
                    escape=lambda s, path: self._escape(s, ptr + pointer(*path), True),
                    pipe=lambda qid, path: self._pipe(qid, ptr + pointer(*path)),
                    report=lambda key, path: self.note(key, ptr + pointer(*path)),
                )
            for feature in sorted(features(value)):
                self.note(f"$rich.{feature}", ptr)
            value = to_plain(value)
        s = value if isinstance(value, str) else ""
        out: list[str] = []
        pos = 0
        for m in _PIPE.finditer(s):
            out.append(self._escape(s[pos : m.start()], ptr, rich_html))
            pos = m.end()
            out.append(self._pipe(m.group(1).strip(), ptr, m.group(0)))
        out.append(self._escape(s[pos:], ptr, rich_html))
        return "".join(out)

    def _escape(self, s: str, ptr: str, as_html: bool) -> str:
        if _CONTROL.search(s):
            self.note("$text.controlCharacters", ptr)
            s = _CONTROL.sub("", s)
        if "{" in s:
            self.note("$text.braces", ptr)
        if not as_html:
            return s
        if _MARKUP.search(s):
            self.note("$text.markup", ptr)
        return html.escape(s, quote=False).replace("\n", "<br />")

    def _pipe(self, qid: str, ptr: str, raw: str | None = None) -> str:
        """The SurveyJS text for one `${qid}` (`raw` is how it was written, kept as text
        when the id is unknown), with the piping diagnostics at `ptr`."""
        if qid.startswith("$"):
            # Built-ins ($trial, $position.*; semantics §8) are our runtime's.
            self.note("$pipe.builtin", ptr, f"${{{qid}}}")
            return ""
        if qid not in self.names:
            if self.types.get(qid) == "assigned":
                self.note("$expr.unmappable", ptr, f"${{{qid}}} pipes an assigned variable")
                return ""
            return raw if raw is not None else "${" + qid + "}"
        kind = self.types.get(qid)
        if kind == "single":
            self.note("$pipe.choiceLabel", ptr, f"${{{qid}}}")
        elif kind == "multi":
            self.note("$pipe.multi", ptr, f"${{{qid}}}")
        return "{" + self.names[qid] + "}"

    # -- expressions ---------------------------------------------------------------------

    def _condition(self, expr: Expr, ptr: str, fallback: str | None = None) -> str | None:
        """The SurveyJS condition, or ``fallback`` with a loss when it cannot be written."""
        try:
            return self.sjs.condition(expr)
        except Unmappable as exc:
            self.note("$expr.unmappable", ptr, str(exc))
            return fallback

    # -- run -----------------------------------------------------------------------------

    def run(self) -> tuple[SurveyJsExport, list[ExportDiagnostic]]:
        for key, ptr, _value in feature_uses(self.s):
            self.note(key, ptr)
        self._index()
        alive = self._walk(self.s.flow, TRUE, "/flow")
        if alive != FALSE:
            html_, url = self._ending_html("complete", None, ""), self._redirect("complete")
            self.flow.ends.append(_End(alive, html_, url, fallback=True))
        if any(not isinstance(q, NoteQuestion) for q in _questions(self.s)):
            self.note("$missingStates", "")
        doc = self._document()
        body = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
        return (
            SurveyJsExport(body.encode("utf-8"), doc, dict(self.our_names), dict(self.helpers)),
            self.diags,
        )

    def _document(self) -> dict[str, Any]:
        doc: dict[str, Any] = {"title": self._loc(self.s.metadata.title, "/metadata/title")}
        desc = self._loc(self.s.metadata.description, "/metadata/description")
        if desc:
            doc["description"] = desc
        if self.base_lang != "en":
            doc["locale"] = self.base_lang
        if not self.s.settings.backNavigation:
            doc["showPrevButton"] = False
        # Our rule: a question that becomes irrelevant loses its answer (semantics.md §3).
        doc["clearInvisibleValues"] = "onHidden"
        doc["pages"] = self.flow.pages
        calculated = self._calculated()
        if calculated:
            doc["calculatedValues"] = calculated
        self._completion(doc)
        return doc

    def _calculated(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for vi, v in enumerate(self.s.variables):
            if not isinstance(v, ComputedVariable):
                continue
            ptr = pointer("variables", vi, "expr")
            try:
                expr = self.sjs.value(v.expr)
            except Unmappable as exc:
                self.note("$expr.unmappable", ptr, str(exc))
                continue
            out.append({"name": self.names[v.id], "expression": expr, "includeIntoResult": True})
        if any(o != "complete" for _c, o in self.flow.outcomes):
            calc = string_literal("complete")
            for cond, outcome in reversed(self.flow.outcomes):
                if cond == FALSE or outcome == "complete":
                    continue
                lit = string_literal(outcome)
                calc = lit if cond == TRUE else f"iif({cond}, {lit}, {calc})"
            name = self._helper(_OUTCOME, "end outcome (EndNode.outcome)")
            out.append({"name": name, "expression": calc, "includeIntoResult": True})
        return out

    def _completion(self, doc: dict[str, Any]) -> None:
        """Completion texts and redirects: the end of the flow (or an end reached
        unconditionally) is the default, each other end an entry on its own path (the paths
        exclude one another, so the default is shown exactly when no entry matches)."""
        on_condition: list[dict[str, Any]] = []
        urls: list[dict[str, Any]] = []
        default_html: Loc | None = None
        default_url: str | None = None
        for end in self.flow.ends:
            if end.fallback or end.condition == TRUE:
                default_html, default_url = end.html, end.url
                continue
            if end.html:
                on_condition.append({"expression": end.condition, "html": end.html})
            if end.url:
                urls.append({"expression": end.condition, "url": end.url})
        if default_html:
            doc["completedHtml"] = default_html
        if on_condition:
            doc["completedHtmlOnCondition"] = on_condition
        if default_url:
            doc["navigateToUrl"] = default_url
        if urls:
            doc["navigateToUrlOnCondition"] = urls

    # -- flow ----------------------------------------------------------------------------

    def _walk(self, nodes: list[Any], alive: str, ptr: str) -> str:
        """Emit ``nodes`` reachable under ``alive``; return the condition to continue."""
        for i, node in enumerate(nodes):
            p = ptr + pointer(i)
            match node:
                case BlockNode():
                    self._block(node.block, alive)
                case BranchNode():
                    c = self._condition(node.if_, p + "/if", TRUE)
                    assert c is not None
                    then_in, else_in = and_(alive, c), and_(alive, not_(c))
                    a = self._walk(node.then, then_in, p + "/then")
                    b = self._walk(node.else_, else_in, p + "/else")
                    if (a, b) != (then_in, else_in):
                        alive = or_(a, b)
                case RandomiserNode():
                    # Every child in written order (reported by the capability walk).
                    alive = self._walk(node.children, alive, p + "/children")
                case EndNode():
                    self._end(node, alive, p)
                    alive = FALSE
                # assign, quotaCheck and externalTask nodes are reported by the walk.
        return alive

    def _end(self, node: EndNode, alive: str, ptr: str) -> None:
        self.flow.outcomes.append((alive, node.outcome))
        if alive == FALSE:
            return
        self.flow.ends.append(
            _End(
                alive,
                self._ending_html(node.outcome, node.message, ptr + "/message"),
                self._redirect(node.outcome),
            )
        )

    def _ending_html(self, outcome: str, message: object, message_ptr: str) -> Loc | None:
        """The completion text of one end: the end node's message, then the outcome's
        ending title (a heading) and body, per language."""
        parts: list[tuple[Loc, str]] = []  # (text, wrapper tag)
        if message is not None:
            parts.append((self._loc(message, message_ptr, rich_html=True) or "", "p"))
        ending = self.s.settings.endings.get(outcome)
        if ending is not None:
            for key, tag in (("title", "h3"), ("body", "p")):
                value = getattr(ending, key)
                if value is not None:
                    ptr = pointer("settings", "endings", outcome, key)
                    parts.append((self._loc(value, ptr, rich_html=True) or "", tag))
        parts = [(t, tag) for t, tag in parts if t]
        if not parts:
            return None
        per_lang: dict[str, list[str]] = {}
        keys = ["default", *self.langs[1:]]
        for text, tag in parts:
            for k in keys:
                t = text if isinstance(text, str) else text.get(k, text["default"])
                wrapped = t if tag == "p" and is_block_html(t) else f"<{tag}>{t}</{tag}>"
                per_lang.setdefault(k, []).append(wrapped)
        joined = {k: "".join(v) for k, v in per_lang.items()}
        if all(v == joined["default"] for v in joined.values()):
            return joined["default"]
        return {k: v for k, v in joined.items() if k == "default" or v != joined["default"]}

    def _redirect(self, outcome: str) -> str | None:
        """An outcome's end redirect (EN2) as a filled URL: literal params percent-encoded.
        None when the outcome has no redirect, or when a param is piped (nothing in SurveyJS
        would re-check the value against its pattern, so the redirect is a loss)."""
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
            pattern = (template.params.get(name) or _NO_PATTERN).pattern or DEFAULT_PARAM_PATTERN
            if not re.fullmatch(f"(?:{pattern})", value) or value in (".", ".."):
                return None  # the validator's redirect.param_literal already blocks publishing
            url = url.replace("{" + name + "}", _percent_encode(value))
        return url

    # -- blocks, pages, questions --------------------------------------------------------

    def _block(self, block_id: str, alive: str) -> None:
        if block_id not in self.blocks or block_id in self.emitted:
            return
        self.emitted.add(block_id)
        bi, block = self.blocks[block_id]
        for pi, page in enumerate(block.pages):
            pptr = pointer("blocks", bi, "pages", pi)
            out: dict[str, Any] = {"name": page.id}
            title = self._loc(page.title, pptr + "/title")
            if title:
                out["title"] = title
            visible = alive
            if page.showIf is not None:
                cond = self._condition(page.showIf, pptr + "/showIf")
                if cond is not None:
                    visible = and_(alive, cond)
            if visible != TRUE:
                out["visibleIf"] = visible
            if page.itemOrder == "shuffle":
                out["questionsOrder"] = "random"
            out["elements"] = [
                self._question(q, pptr + pointer("items", qi)) for qi, q in enumerate(page.items)
            ]
            self.flow.pages.append(out)

    def _question(self, q: Any, ptr: str) -> dict[str, Any]:
        name = self.names[q.id]
        el: dict[str, Any] = {"name": name}
        validators: list[dict[str, Any]] = []
        match q:
            case NoteQuestion():
                el["type"] = "html"
                body = self._loc(q.label, ptr + "/label", rich_html=True)
                help_text = self._loc(q.help, ptr + "/help", rich_html=True)
                el["html"] = _join_html(body, help_text)
            case IntegerQuestion() | DecimalQuestion():
                el["type"] = "text"
                el["inputType"] = "number"
                if isinstance(q, IntegerQuestion):
                    el["step"] = 1
                    validators.append({"type": "regex", "regex": _WHOLE_NUMBER})
                numeric: dict[str, Any] = {"type": "numeric"}
                for key, src in (("min", "minValue"), ("max", "maxValue")):
                    bound = getattr(q, key)
                    if bound is not None:
                        el[key] = _number(bound)
                        numeric[src] = _number(bound)
                if len(numeric) > 1:
                    validators.append(numeric)
            case TextQuestion():
                el["type"] = "comment" if q.multiline else "text"
            case DateQuestion():
                el["type"] = "text"
                el["inputType"] = "date"
            case SingleQuestion() | MultiQuestion():
                el["type"] = "radiogroup" if isinstance(q, SingleQuestion) else "checkbox"
                el["choices"] = self._choices(q, ptr)
                if q.choiceOrder == "shuffle":
                    el["choicesOrder"] = "random"
            case MatrixQuestion():
                el["type"] = "matrix"
                el["columns"] = self._choices(q, ptr)
                el["rows"] = [
                    {
                        "value": r.id,
                        "text": self._loc(r.label, ptr + pointer("rows", k, "label")) or r.id,
                    }
                    for k, r in enumerate(q.rows)
                ]
            case SliderQuestion():
                el["type"] = "slider"
                el["min"], el["max"], el["step"] = _number(q.min), _number(q.max), _number(q.step)
        if not isinstance(q, NoteQuestion):
            el["title"] = self._loc(q.label, ptr + "/label")
            help_text = self._loc(q.help, ptr + "/help")
            if help_text:
                el["description"] = help_text
        # Keep the key order readable: name, type, title first.
        el = {k: el[k] for k in ("name", "type", "title") if k in el} | el
        if q.showIf is not None:
            cond = self._condition(q.showIf, ptr + "/showIf")
            if cond is not None:
                el["visibleIf"] = cond
        if isinstance(q, MatrixQuestion):
            self._matrix_required(q, el, validators, ptr)
        elif not isinstance(q, NoteQuestion):
            if q.required:
                el["isRequired"] = True
            if q.constraint is not None:
                cond = self._condition(q.constraint, ptr + "/constraint")
                if cond is not None:
                    check: dict[str, Any] = {
                        "type": "expression",
                        "expression": or_(f"{{{name}}} empty", cond),
                    }
                    msg = self._loc(q.constraintMessage, ptr + "/constraintMessage")
                    if msg:
                        check["text"] = msg
                    validators.append(check)
        if validators:
            el["validators"] = validators
        return el

    def _matrix_required(
        self,
        q: MatrixQuestion,
        el: dict[str, Any],
        validators: list[dict[str, Any]],
        ptr: str,
    ) -> None:
        """Every row required → `isAllRowRequired`; only some → a validator that those rows
        are answered."""
        flags = [matrix_row_required(q, r) for r in q.rows]
        if all(flags):
            el["isAllRowRequired"] = True
        elif any(flags):
            self.note("$matrix.someRowsRequired", ptr + "/rows")
            rows = [r for r, f in zip(q.rows, flags, strict=True) if f]
            check = and_(*(f"{{{self.names[matrix_row_id(q.id, r.id)]}}} notempty" for r in rows))
            validators.append({"type": "expression", "expression": check})

    def _choices(
        self, q: SingleQuestion | MultiQuestion | MatrixQuestion, ptr: str
    ) -> list[dict[str, Any]]:
        if q.choiceList is not None:
            li = next(i for i, cl in enumerate(self.s.choiceLists) if cl.id == q.choiceList)
            choices: list[Choice] = self.s.choiceLists[li].choices
            base = pointer("choiceLists", li, "choices")
        else:
            choices = q.choices or []
            base = ptr + "/choices"
        return [
            {
                "value": c.value,
                "text": self._loc(c.label, base + pointer(ci, "label")) or str(c.value),
            }
            for ci, c in enumerate(choices)
        ]


def _number(value: int | str | Decimal) -> int | float:
    """A bound or step as a JSON number (decimal text becomes a float: SurveyJS numbers
    are JavaScript numbers)."""
    if isinstance(value, int):
        return value
    d = Decimal(str(value))
    return int(d) if d == d.to_integral_value() else float(d)


def _join_html(body: Loc | None, extra: Loc | None) -> Loc:
    """A note's HTML: its text, then its help as a paragraph."""
    if not extra:
        return body or ""
    if not body:
        return extra
    if isinstance(body, str) and isinstance(extra, str):
        return f"{body}<p>{extra}</p>"
    b = {"default": body} if isinstance(body, str) else body
    e = {"default": extra} if isinstance(extra, str) else extra
    keys = list(dict.fromkeys([*b, *e]))
    return {k: f"{b.get(k, b['default'])}<p>{e.get(k, e['default'])}</p>" for k in keys}


def _questions(s: Survey) -> Iterator[Any]:
    for b in s.blocks:
        for page in b.pages:
            yield from page.items


__all__ = ["SurveyJsExport", "build_surveyjs", "export_surveyjs", "feature_uses"]
