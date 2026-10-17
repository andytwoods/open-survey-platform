"""``osp-survey`` → XLSForm (survey / choices / settings sheets).

Pipeline (planning/review.md §2.4): validate → walk the model for capability diagnostics
→ lower the flow tree into ``relevant`` expressions on block groups → emit rows → write
the workbook. Pages become ``field-list`` groups inside one group per block, with
settings ``style: pages``. Every feature the capability table marks as non-native
produces a diagnostic with a JSON pointer; :func:`export_xlsform` never raises.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import Any

from osp_spec import Survey, parse
from osp_spec.model import (
    AssignedVariable,
    AssignNode,
    Block,
    BlockNode,
    BranchNode,
    Choice,
    ComputedVariable,
    EmbeddedVariable,
    EndNode,
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

from ..capabilities import XLSFORM, Capability
from ..diagnostics import SEVERITY_FOR_LEVEL, ExportDiagnostic, pointer
from .workbook import columns, write_workbook
from .xpath import FALSE, TRUE, XPathContext, XPathWriter, and_, not_, or_, string_literal

TARGET = "xlsform"

_PIPE = re.compile(r"\$\{([^}]*)\}")
_MARKUP = re.compile(r"[*_#<>]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Park–Miller constants (osp_engine.random): modulus 2**31 - 1, multiplier 16807.
_M = 2147483647
_SEED_CALC = "once(int(random() * 2147483646) + 1)"

# English names for language column headers (`label::English (en)`, the XLSForm
# convention); any other tag is written as `<tag> (<tag>)`.
_LANGUAGE_NAMES = {
    "ar": "Arabic",
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "hi": "Hindi",
    "it": "Italian",
    "ja": "Japanese",
    "nl": "Dutch",
    "pl": "Polish",
    "pt": "Portuguese",
    "ru": "Russian",
    "sw": "Swahili",
    "tr": "Turkish",
    "zh": "Chinese",
}

SURVEY_COLUMNS = [
    "type",
    "name",
    "label",
    "hint",
    "relevant",
    "required",
    "constraint",
    "constraint_message",
    "calculation",
    "default",
    "appearance",
    "parameters",
]


def language_column(tag: str) -> str:
    base = tag.split("-")[0].lower()
    return f"{_LANGUAGE_NAMES.get(base, tag)} ({tag})"


type Rows = list[dict[str, str]]


class XLSForm:
    """The three sheets as lists of rows, plus the column order for each."""

    def __init__(self, survey: Rows, choices: Rows, settings: Rows, languages: list[str]):
        self.survey = survey
        self.choices = choices
        self.settings = settings
        self.languages = languages

    def as_pyxform_dict(self) -> dict[str, Rows]:
        return {"survey": self.survey, "choices": self.choices, "settings": self.settings}

    def sheets(self) -> dict[str, tuple[list[str], Rows]]:
        survey_pref = [
            c
            for base in SURVEY_COLUMNS
            for c in ([base] if base in ("type", "name") else _lang_cols(base, self.languages))
        ]
        choice_pref = ["list_name", "name", *_lang_cols("label", self.languages)]
        return {
            "survey": (columns(self.survey, survey_pref), self.survey),
            "choices": (columns(self.choices, choice_pref), self.choices),
            "settings": (columns(self.settings, []), self.settings),
        }


def _lang_cols(base: str, languages: list[str]) -> list[str]:
    translatable = {"label", "hint", "constraint_message"}
    if base not in translatable:
        return [base]
    return [f"{base}::{lang}" for lang in languages]


# --- Public API ---------------------------------------------------------------------------


def export_xlsform(survey: Survey | Mapping[str, Any]) -> tuple[bytes, list[ExportDiagnostic]]:
    """Export a survey to XLSForm ``.xlsx`` bytes, with diagnostics.

    Returns ``(b"", diagnostics)`` with an ``error`` diagnostic if the survey is invalid
    or the exporter fails. Never raises on bad input.
    """
    form, diags = build_xlsform(survey)
    if form is None:
        return b"", diags
    try:
        return write_workbook(form.sheets()), diags
    except Exception as exc:  # pragma: no cover - defensive: never crash on input
        return b"", [
            *diags,
            _error("internal", "", f"workbook writer failed: {type(exc).__name__}"),
        ]


def build_xlsform(
    survey: Survey | Mapping[str, Any],
) -> tuple[XLSForm | None, list[ExportDiagnostic]]:
    """The sheets as row dicts (also valid ``pyxform`` dict input), with diagnostics."""
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
    Nothing inside an unsupported field, or an object whose type is unsupported, is
    reported again: it is dropped as a whole.
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
                if refined in XLSFORM:
                    key = refined
            yield key, p, value
            if _level(key) != "unsupported":
                yield from feature_uses(value, p)
    elif isinstance(obj, (list, tuple)):
        for i, item in enumerate(obj):
            yield from feature_uses(item, ptr + pointer(i))


def _level(key: str) -> str | None:
    cap = XLSFORM.get(key)
    return cap.level if cap else None


# --- Exporter ------------------------------------------------------------------------------


class _Exporter:
    def __init__(self, survey: Survey) -> None:
        self.s = survey
        self.diags: list[ExportDiagnostic] = []
        self._seen: set[tuple[str, str]] = set()
        self.langs = list(survey.metadata.languages)
        self.default_lang = survey.metadata.defaultLanguage or self.langs[0]
        self.rows: Rows = []
        self.choices: Rows = []
        self.taken: set[str] = set()
        self.list_names: set[str] = {cl.id for cl in survey.choiceLists}
        self.names: dict[str, str] = {}
        self.types: dict[str, str] = {}
        self.ends: list[tuple[str, str]] = []  # (condition, outcome)
        self.label_calcs: dict[str, str] = {}  # piped single question id -> calc name
        self._index()

    # -- diagnostics ---------------------------------------------------------------------

    def note(self, feature: str, ptr: str, detail: str = "") -> None:
        cap: Capability | None = XLSFORM.get(feature)
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
                    message=f"{feature} has no row in the XLSForm capability table; "
                    "it may not be exported",
                )
            )
            return
        if cap.level == "native" or (feature, ptr) in self._seen:
            return
        self._seen.add((feature, ptr))
        message = f"{feature} is {cap.level} in XLSForm: {cap.note}"
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
        name, n = base, 2
        while name.lower() in self.taken:
            name, n = f"{base}_{n}", n + 1
        self.taken.add(name.lower())
        return name

    def _alloc_list(self, base: str) -> str:
        name, n = base, 2
        while name in self.list_names:
            name, n = f"{base}_{n}", n + 1
        self.list_names.add(name)
        return name

    def _index(self) -> None:
        # User-visible names first, so generated names never take one.
        for b in self.s.blocks:
            for page in b.pages:
                for q in page.items:
                    name = getattr(q, "name", None) or q.id
                    self.names[q.id] = name
                    self.taken.add(name.lower())
                    self.types[q.id] = q.valueType if isinstance(q, SliderQuestion) else q.type
                    if isinstance(q, MatrixQuestion):
                        # Each row is its own variable (semantics.md §2, C2c-1).
                        for row in q.rows:
                            rid = matrix_row_id(q.id, row.id)
                            self.names[rid] = matrix_row_name(q, row.id)
                            self.taken.add(self.names[rid].lower())
                            self.types[rid] = "single"
        for v in self.s.variables:
            name = v.name or v.id
            self.names[v.id] = name
            self.taken.add(name.lower())
            if isinstance(v, EmbeddedVariable):
                self.types[v.id] = v.valueType
            elif isinstance(v, AssignedVariable):
                self.types[v.id] = "assigned"
            else:
                self.types[v.id] = "decimal"
        self.taken.update({"meta", "instanceid", "instancename"})
        for text in self._all_texts():
            for m in _PIPE.finditer(text):
                qid = m.group(1).strip()
                if self.types.get(qid) == "single" and qid not in self.label_calcs:
                    self.label_calcs[qid] = ""  # allocated when the question is emitted

    def _all_texts(self) -> Iterator[str]:
        def strings(t: object) -> Iterator[str]:
            if isinstance(t, str):
                yield t
            elif isinstance(t, dict):
                yield from (v for v in t.values() if isinstance(v, str))

        for cl in self.s.choiceLists:
            for c in cl.choices:
                yield from strings(c.label)
        for b in self.s.blocks:
            for page in b.pages:
                for q in page.items:
                    for attr in ("label", "help", "constraintMessage", "minLabel", "maxLabel"):
                        yield from strings(getattr(q, attr, None))
                    for row in getattr(q, "rows", None) or []:
                        yield from strings(row.label)
                    for c in getattr(q, "choices", None) or []:
                        yield from strings(c.label)
        for node in _flow_nodes(self.s.flow):
            if isinstance(node, EndNode):
                yield from strings(node.message)

    def _xpath(self, self_id: str | None = None) -> XPathWriter:
        return XPathWriter(XPathContext(self.names, self.types, self_id))

    # -- text ----------------------------------------------------------------------------

    def _texts(self, text: object, ptr: str) -> dict[str, str]:
        """``{language column: text}`` with pipes rewritten to XLSForm names."""
        if text is None:
            return {}
        if isinstance(text, str):
            per_lang = {lang: (text, ptr) for lang in self.langs}
        else:
            assert isinstance(text, dict)
            fallback = text.get(self.default_lang) or next(iter(text.values()), "")
            per_lang = {
                lang: (text.get(lang, fallback), ptr + pointer(lang) if lang in text else ptr)
                for lang in self.langs
            }
        out: dict[str, str] = {}
        for lang, (s, sp) in per_lang.items():
            out[language_column(lang)] = self._pipe(s, sp)
        return out

    def _pipe(self, s: str, ptr: str) -> str:
        if _CONTROL.search(s):
            self.note("$text.controlCharacters", ptr)
        if _MARKUP.search(_PIPE.sub("", s)):
            self.note("$text.markup", ptr)

        def repl(m: re.Match[str]) -> str:
            qid = m.group(1).strip()
            if qid.startswith("$"):
                # Built-ins ($trial, $position.*; semantics §8) are our runtime's.
                self.note("$pipe.builtin", ptr, f"${{{qid}}}")
                return ""
            if qid not in self.names:
                return m.group(0)
            self.note("$pipe.escaping", ptr)
            kind = self.types.get(qid)
            if kind == "single":
                self.note("$pipe.choiceLabel", ptr, f"${{{qid}}}")
                calc = self.label_calcs.get(qid) or self._label_calc_name(qid)
                return "${" + calc + "}"
            if kind == "multi":
                self.note("$pipe.multi", ptr, f"${{{qid}}}")
            return "${" + self.names[qid] + "}"

        return _PIPE.sub(repl, s)

    def _label_calc_name(self, qid: str) -> str:
        name = self.label_calcs.get(qid) or self._alloc(f"osp_label_{self.names[qid]}")
        self.label_calcs[qid] = name
        return name

    def _labelled(self, row: dict[str, str], col: str, text: object, ptr: str) -> None:
        for lang_col, value in self._texts(text, ptr).items():
            row[f"{col}::{lang_col}"] = value

    # -- run -----------------------------------------------------------------------------

    def run(self) -> tuple[XLSForm, list[ExportDiagnostic]]:
        for key, ptr, _value in feature_uses(self.s):
            self.note(key, ptr)
        title = self.s.metadata.title
        if isinstance(title, dict) and len(title) > 1:
            self.note("Metadata.title=translated", "/metadata/title")

        self._choice_lists()
        self._variables()
        self._walk(self.s.flow, TRUE, "/flow")
        self._outcome()
        if any(not isinstance(q, NoteQuestion) for q in _questions(self.s)):
            self.note("$missingStates", "")

        lang_cols = [language_column(lang) for lang in self.langs]
        settings: dict[str, str] = {
            "form_title": _plain(title, self.default_lang),
            "form_id": self.s.id,
            "default_language": language_column(self.default_lang),
            "style": "pages",
        }
        if self.s.version is not None:
            settings["version"] = str(self.s.version)
        form = XLSForm(self.rows, self.choices, [settings], lang_cols)
        return form, self.diags

    # -- choices and variables -----------------------------------------------------------

    def _choice_rows(self, list_name: str, choices: list[Choice], ptr: str) -> None:
        for i, c in enumerate(choices):
            row = {"list_name": list_name, "name": str(c.value)}
            self._labelled(row, "label", c.label, ptr + pointer(i, "label"))
            self.choices.append(row)

    def _choice_lists(self) -> None:
        for i, cl in enumerate(self.s.choiceLists):
            self._choice_rows(cl.id, cl.choices, pointer("choiceLists", i, "choices"))

    def _variables(self) -> None:
        for v in self.s.variables:
            name = self.names[v.id]
            if isinstance(v, EmbeddedVariable):
                row = {"type": "hidden", "name": name}
                if v.default is not None:
                    row["default"] = str(v.default)
                self.rows.append(row)
            elif isinstance(v, ComputedVariable):
                calc = self._xpath().value(v.expr)
                self.rows.append({"type": "calculate", "name": name, "calculation": calc})
            # Assigned variables are emitted at their assign node.

    # -- flow ----------------------------------------------------------------------------

    def _walk(self, nodes: list[Any], alive: str, ptr: str) -> str:
        """Emit ``nodes`` reachable under ``alive``; return the condition to continue."""
        for i, node in enumerate(nodes):
            p = ptr + pointer(i)
            match node:
                case BlockNode():
                    self._block(node.block, alive)
                case BranchNode():
                    c = self._xpath().condition(node.if_)
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
                    pass  # unsupported; reported by the capability walk
                case EndNode():
                    self._end(node, alive, p)
                    alive = FALSE
        return alive

    def _randomiser(self, node: RandomiserNode, alive: str, ptr: str) -> str:
        if node.pick is None or node.pick >= len(node.children):
            return self._walk(node.children, alive, ptr + "/children")
        list_name = self._alloc_list(f"osp_rand_{node.id}")
        for child in node.children:
            self.choices.append(
                {"list_name": list_name, "name": child.id}
                | {f"label::{language_column(lang)}": child.id for lang in self.langs}
            )
        seed = self._alloc(f"osp_seed_{node.id}")
        order = self._alloc(f"osp_order_{node.id}")
        self.rows.append({"type": "calculate", "name": seed, "calculation": _SEED_CALC})
        self.rows.append(
            {
                "type": "calculate",
                "name": order,
                "calculation": f"join(' ', randomize(instance('{list_name}')/root/item/name, "
                f"${{{seed}}}))",
            }
        )
        for k, child in enumerate(node.children):
            chosen = or_(
                *(
                    f"selected-at(${{{order}}}, {j}) = {string_literal(child.id)}"
                    for j in range(node.pick)
                )
            )
            child_in = and_(alive, chosen)
            out = self._walk([child], child_in, ptr + pointer("children", k))
            if out != child_in:
                alive = or_(out, and_(alive, not_(chosen)))
        return alive

    def _assign(self, node: AssignNode) -> None:
        by_id = {v.id: v for v in self.s.variables}
        for vid in node.variables:
            v = by_id.get(vid)
            if not isinstance(v, AssignedVariable):
                continue
            seed = self._alloc(f"osp_seed_{self.names[vid]}")
            self.rows.append({"type": "calculate", "name": seed, "calculation": _SEED_CALC})
            self.rows.append(
                {"type": "calculate", "name": self.names[vid], "calculation": _assign_calc(seed, v)}
            )

    def _end(self, node: EndNode, alive: str, ptr: str) -> None:
        self.ends.append((alive, node.outcome))
        if node.message is None:
            return
        group = self._alloc(f"osp_end_{node.id}")
        row = {"type": "begin group", "name": group, "appearance": "field-list"}
        if alive != TRUE:
            row["relevant"] = alive
        self.rows.append(row)
        note = {"type": "note", "name": self._alloc(f"osp_end_{node.id}_message")}
        self._labelled(note, "label", node.message, ptr + "/message")
        self.rows.append(note)
        self.rows.append({"type": "end group"})

    def _outcome(self) -> None:
        if not self.ends:
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
        self.rows.append(
            {"type": "calculate", "name": self._alloc("osp_outcome"), "calculation": calc}
        )

    # -- blocks, pages, questions --------------------------------------------------------

    def _block(self, block_id: str, alive: str) -> None:
        bi, block = next(
            ((i, b) for i, b in enumerate(self.s.blocks) if b.id == block_id), (-1, None)
        )
        if block is None:
            return
        assert isinstance(block, Block)
        row = {"type": "begin group", "name": self._alloc(block.id)}
        if alive != TRUE:
            row["relevant"] = alive
        self.rows.append(row)
        for pi, page in enumerate(block.pages):
            group = {
                "type": "begin group",
                "name": self._alloc(page.id),
                "appearance": "field-list",
            }
            if page.showIf is not None:
                group["relevant"] = self._xpath().condition(page.showIf)
            self.rows.append(group)
            for qi, q in enumerate(page.items):
                self._question(q, pointer("blocks", bi, "pages", pi, "items", qi))
            self.rows.append({"type": "end group"})
        self.rows.append({"type": "end group"})

    def _matrix(self, q: MatrixQuestion, ptr: str) -> None:
        """A `table-list` group: a label-only header row, then one `select_one` per row,
        each its own variable `<matrix name>_<row id>` (semantics.md §2, C2c-1)."""
        name = self.names[q.id]
        list_name = q.choiceList
        if list_name is None:
            list_name = self._alloc_list(f"{name}_choices")
            self._choice_rows(list_name, q.choices or [], ptr + "/choices")
        # The matrix's own name (reserved in _index) names the group; it holds no value.
        group = {"type": "begin group", "name": name, "appearance": "table-list"}
        if q.showIf is not None:
            group["relevant"] = self._xpath().condition(q.showIf)
        self.rows.append(group)
        header = {
            "type": f"select_one {list_name}",
            "name": self._alloc(f"osp_{name}_header"),
            "appearance": "label",
        }
        # The header row carries the matrix text above the column labels.
        self._labelled(header, "label", q.label, ptr + "/label")
        self._labelled(header, "hint", q.help, ptr + "/help")
        self.rows.append(header)
        for k, mrow in enumerate(q.rows):
            rid = matrix_row_id(q.id, mrow.id)
            row = {
                "type": f"select_one {list_name}",
                "name": self.names[rid],
                "appearance": "list-nolabel",
            }
            self._labelled(row, "label", mrow.label, ptr + pointer("rows", k, "label"))
            if matrix_row_required(q, mrow):
                row["required"] = "yes"
            self.rows.append(row)
            self._label_calc(rid)
        self.rows.append({"type": "end group"})

    def _label_calc(self, qid: str) -> None:
        if qid not in self.label_calcs:
            return
        name = self.names[qid]
        calc = self._label_calc_name(qid)
        self.rows.append(
            {
                "type": "calculate",
                "name": calc,
                "calculation": f"jr:choice-name(${{{name}}}, '${{{name}}}')",
            }
        )

    def _question(self, q: Any, ptr: str) -> None:
        if isinstance(q, MatrixQuestion):
            self._matrix(q, ptr)
            return
        name = self.names[q.id]
        row: dict[str, str] = {"type": "", "name": name}
        if isinstance(q, (SingleQuestion, MultiQuestion)):
            list_name = q.choiceList
            if list_name is None:
                list_name = self._alloc_list(f"{name}_choices")
                self._choice_rows(list_name, q.choices or [], ptr + "/choices")
            kind = "select_one" if isinstance(q, SingleQuestion) else "select_multiple"
            row["type"] = f"{kind} {list_name}"
            if q.choiceOrder == "shuffle":
                seed = self._alloc(f"osp_seed_{name}")
                self.rows.append({"type": "calculate", "name": seed, "calculation": _SEED_CALC})
                row["parameters"] = f"randomize=true seed=${{{seed}}}"
        elif isinstance(q, SliderQuestion):
            # `range` enforces the track and step; Enketo shows no value until touched.
            row["type"] = "range"
            row["parameters"] = f"start={q.min} end={q.max} step={q.step}"
        else:
            row["type"] = q.type
            if isinstance(q, TextQuestion) and q.multiline:
                row["appearance"] = "multiline"
        self._labelled(row, "label", q.label, ptr + "/label")
        self._labelled(row, "hint", q.help, ptr + "/help")
        if q.showIf is not None:
            row["relevant"] = self._xpath().condition(q.showIf)
        if not isinstance(q, NoteQuestion):
            if q.required:
                row["required"] = "yes"
            parts = []
            for key, op in (("min", ">="), ("max", "<=")):
                bound = None if isinstance(q, SliderQuestion) else getattr(q, key, None)
                if bound is not None:
                    parts.append(f". {op} {bound}")
            if q.constraint is not None:
                parts.append(self._xpath(self_id=q.id).condition(q.constraint))
            if parts:
                row["constraint"] = " and ".join(p if len(parts) == 1 else f"({p})" for p in parts)
            self._labelled(
                row, "constraint_message", q.constraintMessage, ptr + "/constraintMessage"
            )
        self.rows.append(row)
        self._label_calc(q.id)


def _assign_calc(seed: str, v: AssignedVariable) -> str:
    """The level osp_engine.random.assign(levels, None, seed) picks, in XPath.

    One Park–Miller draw: ``r = (seed * 16807 mod M) - 1``, level ``floor(r * n / (M - 1))``.
    Every intermediate is an integer below 2**53, so IEEE doubles compute it exactly.
    """
    n = len(v.levels)
    index = f"floor((((${{{seed}}} * 16807) mod {_M}) - 1) * {n} div {_M - 1})"
    levels = [str(level) for level in v.levels]
    if all(level and not any(ch.isspace() for ch in level) for level in levels):
        return f"selected-at({string_literal(' '.join(levels))}, {index})"
    calc = "''"
    for k in reversed(range(n)):
        calc = f"if({index} = {k}, {string_literal(levels[k])}, {calc})"
    return calc


def _plain(text: object, lang: str) -> str:
    if isinstance(text, str):
        return text
    if isinstance(text, dict):
        return text.get(lang) or next(iter(text.values()), "")
    return ""


def _flow_nodes(nodes: list[Any]) -> Iterator[Any]:
    for node in nodes:
        yield node
        if isinstance(node, BranchNode):
            yield from _flow_nodes(node.then)
            yield from _flow_nodes(node.else_)
        elif isinstance(node, RandomiserNode):
            yield from _flow_nodes(node.children)


def _questions(s: Survey) -> Iterator[Any]:
    for b in s.blocks:
        for page in b.pages:
            yield from page.items


__all__ = ["XLSForm", "build_xlsform", "export_xlsform", "feature_uses", "language_column"]
