"""SurveyJS JSON → ``osp-survey`` (task IM1).

Written from the public SurveyJS documentation (survey JSON schema: ``pages`` of
``elements``, question ``type``s, ``visibleIf`` / ``requiredIf`` expressions, localisable
strings as ``{"default": ..., "de": ...}``). Clean-room: no SurveyJS code.

Mapping (every other property is reported):

| SurveyJS                                 | osp-survey                                  |
|------------------------------------------|---------------------------------------------|
| page                                     | page (all pages in one block)               |
| text (inputType number/range)            | decimal (``min``/``max`` kept)              |
| text (inputType date)                    | date                                        |
| text (other), comment                    | text (comment: multiline)                   |
| radiogroup, dropdown                     | single                                      |
| checkbox, tagbox                         | multi                                       |
| boolean                                  | single with ``true``/``false`` labels       |
| rating                                   | single (rate values or rateMin..rateMax)    |
| matrix                                   | matrix (rows × columns)                     |
| html, image                              | note                                        |
| expression                               | computed variable (when the expression maps)|
| multipletext                             | one text question per item (lowered)        |
| panel                                    | its elements, flattened (lowered)           |
| nouislider / slider                      | slider                                      |
| visibleIf, requiredIf (page or question) | showIf; requiredIf: required when constant  |
| choicesOrder random                      | choiceOrder shuffle                         |
| questionsOrder random                    | itemOrder shuffle                           |
| calculatedValues                         | computed variables                          |
| completedHtml                            | end node message                            |
| ranking, file, signaturepad, imagepicker, matrixdropdown, matrixdynamic, paneldynamic,
  triggers, validators other than numeric, choicesByUrl, showOtherItem … | reported losses |
"""

from __future__ import annotations

import json
from typing import Any

from .common import (
    Diagnostics,
    Ids,
    ImportResult,
    choice_value,
    ensure_not_empty,
    finish,
    guard_our_pipes,
    guarded,
    harmonise_values,
    html_to_text,
    language_tag,
    pointer,
    rewrite_pipes,
    row_id,
    skeleton,
    text_value,
    unique_values,
)
from .sjs_expr import SJS_PIPE, parse_expression

MAX_BYTES = 20_000_000

_SINGLE = {"radiogroup", "dropdown"}
_MULTI = {"checkbox", "tagbox"}
_NOTE = {"html", "image"}
_SLIDER = {"nouislider", "slider"}
_LOST = {
    "ranking": "ranking questions",
    "file": "file uploads",
    "signaturepad": "signature pads",
    "matrixdropdown": "multi-column grids",
    "matrixdynamic": "dynamic grids",
    "paneldynamic": "dynamic panels",
    "imagepicker": "image pickers",
    "buttongroup": "button groups",
    "microphone": "audio recording",
    "geolocation": "geolocation",
}
# Question properties with no counterpart; reported once each when present.
_IGNORED_PROPS = {
    "enableIf": (
        "enableIf",
        "read-only logic (enableIf) is not supported: the question is always editable",
    ),
    "setValueIf": ("setValueIf", "setValueIf / setValueExpression are not imported"),
    "setValueExpression": ("setValueIf", "setValueIf / setValueExpression are not imported"),
    "defaultValue": ("defaultValue", "default values are not imported: questions start unanswered"),
    "defaultValueExpression": (
        "defaultValue",
        "default values are not imported: questions start unanswered",
    ),
    "correctAnswer": ("correctAnswer", "correct answers (quizzes) are not imported"),
    "choicesByUrl": ("choicesByUrl", "choices loaded from a URL are not imported"),
    "choicesVisibleIf": ("choicesVisibleIf", "per-choice visibility is not supported"),
    "choicesEnableIf": ("choicesVisibleIf", "per-choice visibility is not supported"),
    "showOtherItem": ("showOtherItem", "an 'Other' text box is not supported: add a text question"),
    "hasOther": ("showOtherItem", "an 'Other' text box is not supported: add a text question"),
    "showNoneItem": ("showNoneItem", "a 'None' item is not supported: add a choice"),
    "hasNone": ("showNoneItem", "a 'None' item is not supported: add a choice"),
    "showSelectAllItem": ("showSelectAllItem", "a 'Select all' item is not supported"),
    "hasSelectAll": ("showSelectAllItem", "a 'Select all' item is not supported"),
    "showCommentArea": ("showCommentArea", "comment areas are not supported: add a text question"),
    "hasComment": ("showCommentArea", "comment areas are not supported: add a text question"),
    "maxSelectedChoices": (
        "maxSelectedChoices",
        "limits on the number of selected choices are not supported",
    ),
    "minSelectedChoices": (
        "maxSelectedChoices",
        "limits on the number of selected choices are not supported",
    ),
    "readOnly": ("readOnly", "read-only questions are not supported"),
    "maxLength": ("maxLength", "text length limits are not supported"),
    "placeholder": ("placeholder", "placeholders are not shown"),
    "rows": None,  # matrix rows (handled) / comment rows (ignored silently)
    "cellType": ("cellType", "grid cell types are not supported"),
}


def import_surveyjs(content: str | bytes) -> ImportResult:
    """Import a SurveyJS survey JSON document. Never raises."""
    return guarded("surveyjs", lambda diags: _Importer(diags).run(content))


def _text(raw: str | bytes) -> str:
    return raw.decode("utf-8-sig", errors="replace") if isinstance(raw, bytes) else raw


class _Importer:
    def __init__(self, diags: Diagnostics) -> None:
        self.d = diags
        self.ids = Ids()
        self.langs: list[str] = ["en"]
        self.default = "en"
        self.names: dict[str, str] = {}  # SurveyJS name -> our id
        self.types: dict[str, str] = {}  # our id -> our type
        self.values: dict[str, dict[str, int | str]] = {}  # our id -> {value text: our value}
        self.html_count = 0
        self.survey: dict[str, Any] = {}

    # -- entry ---------------------------------------------------------------------------

    def run(self, content: str | bytes) -> ImportResult:
        text = _text(content)
        if len(text) > MAX_BYTES:
            self.d.error("too_large", "", "the file is larger than 20 MB")
            return ImportResult("surveyjs", None, self.d.items, [], None)
        try:
            doc = json.loads(text)
        except ValueError as exc:
            self.d.error("not_json", "", f"not valid JSON: {str(exc)[:80]}")
            return ImportResult("surveyjs", None, self.d.items, [], None)
        if not isinstance(doc, dict):
            self.d.error("not_a_survey", "", "the JSON is not an object")
            return ImportResult("surveyjs", None, self.d.items, [], None)
        pages = doc.get("pages")
        elements = doc.get("elements") or doc.get("questions")
        if not isinstance(pages, list) and not isinstance(elements, list):
            self.d.error("not_a_survey", "", "no 'pages' or 'elements' list: not a SurveyJS survey")
            return ImportResult("surveyjs", None, self.d.items, [], None)
        if not isinstance(pages, list):
            pages = [{"name": "page1", "elements": elements}]
            doc = {**doc, "pages": pages}

        self._languages(doc)
        self.ids.reserve("survey")
        title = self._localised(doc.get("title"), "/title") or {self.default: "Imported survey"}
        self.survey = skeleton(
            text_value(title, self.langs, self.default), self.langs, self.default
        )
        desc = self._localised(doc.get("description"), "/description")
        if desc:
            self.survey["metadata"]["description"] = text_value(desc, self.langs, self.default)
        self._survey_level(doc)

        block_id = self.ids.claim("main")
        block: dict[str, Any] = {"id": block_id, "pages": []}
        self.survey["blocks"].append(block)
        # First pass: allocate ids for every question, so references resolve in document
        # order (a reference to a later question is a forward reference: dropped by finish).
        self._allocate(pages)
        for pi, page in enumerate(pages):
            if isinstance(page, dict):
                self._page(page, pointer("pages", pi), block)
        self.survey["flow"].append(
            {"type": "block", "id": self.ids.claim("n_main"), "block": block_id}
        )
        self._calculated(doc)
        self._end(doc)
        if self.html_count:
            self.d.info(
                "html_stripped",
                "html",
                "",
                f"HTML formatting was removed from {self.html_count} text(s)",
            )
        ensure_not_empty(self.survey, self.d, self.ids)
        return finish("surveyjs", self.survey, self.d)

    # -- survey level --------------------------------------------------------------------

    def _languages(self, doc: dict[str, Any]) -> None:
        found: list[str] = []

        def walk(v: Any) -> None:
            if isinstance(v, dict):
                if "default" in v and all(isinstance(x, str) for x in v.values()):
                    for k in v:
                        if k != "default" and k not in found:
                            found.append(k)
                    return
                for x in v.values():
                    walk(x)
            elif isinstance(v, list):
                for x in v:
                    walk(x)

        walk(doc)
        default = language_tag(doc.get("locale"), "en")
        langs = [default]
        for k in found:
            tag = language_tag(k, "")
            if tag and tag not in langs:
                langs.append(tag)
        self.langs, self.default = langs, default

    def _survey_level(self, doc: dict[str, Any]) -> None:
        for key, feature, msg in (
            (
                "triggers",
                "triggers",
                "triggers (complete, skip, setvalue, copyvalue) are not imported",
            ),
            ("showProgressBar", "showProgressBar", "progress bar settings are a theme matter here"),
            (
                "firstPageIsStarted",
                "firstPageIsStarted",
                "a start page is imported as an ordinary page",
            ),
            ("cookieName", "cookieName", "single-response cookies are not imported"),
            ("maxTimeToFinish", "maxTimeToFinish", "time limits are not supported"),
            ("maxTimeToFinishPage", "maxTimeToFinish", "time limits are not supported"),
            ("navigateToUrl", "navigateToUrl", "redirects after completion are not imported"),
            (
                "navigateToUrlOnCondition",
                "navigateToUrl",
                "redirects after completion are not imported",
            ),
            (
                "completedBeforeHtml",
                "completedBeforeHtml",
                "'completed before' text is not imported",
            ),
            ("loadingHtml", "loadingHtml", "loading text is not imported"),
            ("checkErrorsMode", "checkErrorsMode", "validation always runs on page submit here"),
        ):
            if key in doc:
                sev = "warning" if key in ("checkErrorsMode", "showProgressBar") else "loss"
                self.d.add(sev, "survey_property", feature, pointer(key), msg)
        if doc.get("showPrevButton") is False:
            self.survey["settings"]["backNavigation"] = False
        if doc.get("questionsOrder") == "random":
            self.d.warn(
                "questions_order",
                "questionsOrder",
                "/questionsOrder",
                "survey-wide random question order is applied per page",
            )

    def _calculated(self, doc: dict[str, Any]) -> None:
        for i, cv in enumerate(doc.get("calculatedValues") or []):
            p = pointer("calculatedValues", i)
            if not isinstance(cv, dict) or not cv.get("name"):
                self.d.loss(
                    "calculated_value",
                    "calculatedValues",
                    p,
                    "a calculated value without a name was skipped",
                )
                continue
            vid = self.ids.claim(cv["name"])
            expr = self._expr(cv.get("expression"), p + "/expression", value=True)
            if expr is None:
                continue
            self.survey["variables"].append({"kind": "computed", "id": vid, "expr": expr})
            self.names[str(cv["name"])] = vid
            self.types[vid] = "computed"

    def _end(self, doc: dict[str, Any]) -> None:
        msg = self._localised(doc.get("completedHtml"), "/completedHtml")
        node: dict[str, Any] = {"type": "end", "id": self.ids.claim("end")}
        if msg:
            node["message"] = text_value(msg, self.langs, self.default)
        if doc.get("completedHtmlOnCondition"):
            self.d.loss(
                "completed_on_condition",
                "completedHtmlOnCondition",
                "/completedHtmlOnCondition",
                "conditional completion texts are not imported (the plain one is)",
            )
        self.survey["flow"].append(node)

    # -- pages and questions -------------------------------------------------------------

    def _allocate(self, pages: list[Any]) -> None:
        def walk(elements: Any) -> None:
            if not isinstance(elements, list):
                return
            for el in elements:
                if not isinstance(el, dict):
                    continue
                if el.get("type") in ("panel",) or (
                    "elements" in el and el.get("type") not in _LOST
                ):
                    walk(el.get("elements"))
                    continue
                name = el.get("name")
                if isinstance(name, str) and name and name not in self.names:
                    self.names[name] = self.ids.claim(name)

        for page in pages:
            if isinstance(page, dict):
                walk(page.get("elements") or page.get("questions"))

    def _page(self, page: dict[str, Any], p: str, block: dict[str, Any]) -> None:
        pid = self.ids.claim(page.get("name") or f"page{len(block['pages']) + 1}")
        out: dict[str, Any] = {"id": pid, "items": []}
        title = self._localised(page.get("title"), p + "/title")
        if title:
            out["title"] = text_value(title, self.langs, self.default)
        if page.get("description"):
            self.d.info(
                "page_description",
                "description",
                p + "/description",
                "page descriptions become a note",
            )
            desc = self._localised(page.get("description"), p + "/description")
            if desc:
                out["items"].append(
                    {
                        "type": "note",
                        "id": self.ids.claim(pid + "_desc"),
                        "label": text_value(desc, self.langs, self.default),
                    }
                )
        cond = self._expr(page.get("visibleIf"), p + "/visibleIf")
        if cond is not None:
            out["showIf"] = cond
        if page.get("questionsOrder") == "random":
            out["itemOrder"] = "shuffle"
        for key in ("enableIf", "requiredIf", "maxTimeToFinish", "navigationTitle"):
            if key in page:
                self.d.loss("page_property", key, p + "/" + key, f"page '{key}' is not supported")
        self._elements(page.get("elements") or page.get("questions") or [], p + "/elements", out)
        block["pages"].append(out)

    def _elements(self, elements: Any, p: str, page: dict[str, Any]) -> None:
        if not isinstance(elements, list):
            return
        for i, el in enumerate(elements):
            ep = p + pointer(i)
            if not isinstance(el, dict):
                self.d.loss(
                    "element", "element", ep, "an element that is not an object was skipped"
                )
                continue
            kind = el.get("type")
            if kind == "panel" or (kind is None and "elements" in el):
                self._panel(el, ep, page)
                continue
            self._question(el, ep, page)

    def _panel(self, el: dict[str, Any], p: str, page: dict[str, Any]) -> None:
        self.d.info(
            "panel", "panel", p, "panel flattened: its questions follow one another on the page"
        )
        title = self._localised(el.get("title"), p + "/title")
        if title:
            page["items"].append(
                {
                    "type": "note",
                    "id": self.ids.claim(el.get("name") or "panel"),
                    "label": text_value(title, self.langs, self.default),
                }
            )
        if el.get("visibleIf"):
            self.d.warn(
                "panel_visible_if",
                "visibleIf",
                p + "/visibleIf",
                "a panel's visibleIf is applied to each of its questions",
            )
        inner = el.get("elements") or el.get("questions") or []
        before = len(page["items"])
        self._elements(inner, p + "/elements", page)
        cond = self._expr(el.get("visibleIf"), p + "/visibleIf")
        if cond is not None:
            for q in page["items"][before:]:
                q.setdefault("showIf", cond)

    def _question(self, el: dict[str, Any], p: str, page: dict[str, Any]) -> None:
        kind = str(el.get("type") or "text")
        name = el.get("name")
        if not isinstance(name, str) or not name:
            name = f"q{len(self.names) + 1}"
        qid = self.names.get(name) or self.ids.claim(name)
        self.names[name] = qid
        if kind in _LOST:
            self.d.loss(
                "question_type",
                f"type={kind}",
                p,
                f"{_LOST[kind]} are not supported: '{name}' left out",
            )
            return
        label = self._label(el, p, name)
        base: dict[str, Any] = {"id": qid, "label": label}
        if el.get("description"):
            help_text = self._localised(el.get("description"), p + "/description")
            if help_text:
                base["help"] = text_value(help_text, self.langs, self.default)
        cond = self._expr(el.get("visibleIf"), p + "/visibleIf")
        if cond is not None:
            base["showIf"] = cond
        if kind in _NOTE:
            q = {"type": "note", **base}
            if kind == "image":
                self.d.loss(
                    "image",
                    "image",
                    p,
                    "images are not shown: a note with the image's name stands in",
                )
            page["items"].append(q)
            self.types[qid] = "note"
            self._report_ignored(el, p, kind)
            return
        if kind == "multipletext":
            self._multipletext(el, p, page, base)
            return
        if kind == "expression":
            expr = self._expr(el.get("expression"), p + "/expression", value=True)
            if expr is not None:
                self.survey["variables"].append({"kind": "computed", "id": qid, "expr": expr})
                self.types[qid] = "computed"
                self.d.info(
                    "expression",
                    "expression",
                    p,
                    f"'{name}' becomes a computed variable (not shown)",
                )
            return

        q: dict[str, Any] = base
        if kind in _SINGLE or kind in _MULTI:
            q["type"] = "single" if kind in _SINGLE else "multi"
            choices = self._choices(el.get("choices"), p + "/choices", qid)
            if choices is None:
                self.d.loss("no_choices", "choices", p, f"'{name}' has no choices: left out")
                return
            q["choices"] = choices
            if el.get("choicesOrder") == "random":
                q["choiceOrder"] = "shuffle"
            elif el.get("choicesOrder") in ("asc", "desc"):
                self.d.warn(
                    "choices_order",
                    "choicesOrder",
                    p + "/choicesOrder",
                    "sorted choice order is kept as written",
                )
        elif kind == "boolean":
            q["type"] = "single"
            yes = self._localised(el.get("labelTrue"), p + "/labelTrue") or {self.default: "Yes"}
            no = self._localised(el.get("labelFalse"), p + "/labelFalse") or {self.default: "No"}
            q["choices"] = [
                {"value": "true", "label": text_value(yes, self.langs, self.default)},
                {"value": "false", "label": text_value(no, self.langs, self.default)},
            ]
            self.values[qid] = {"true": "true", "false": "false", "True": "true", "False": "false"}
            self.d.info("boolean", "boolean", p, f"'{name}' becomes a single choice (true / false)")
        elif kind == "rating":
            q["type"] = "single"
            q["choices"] = self._rating(el, p, qid)
        elif kind == "matrix":
            if not self._matrix(el, p, q):
                return
        elif kind in _SLIDER:
            q["type"] = "slider"
            lo, hi = el.get("rangeMin", el.get("min", 0)), el.get("rangeMax", el.get("max", 100))
            step = el.get("step", 1)
            q["min"], q["max"], q["step"] = _num(lo, 0), _num(hi, 100), _num(step, 1)
            q["valueType"] = (
                "integer"
                if all(isinstance(x, int) for x in (q["min"], q["max"], q["step"]))
                else "decimal"
            )
            if q["valueType"] == "decimal":
                q["min"], q["max"], q["step"] = str(q["min"]), str(q["max"]), str(q["step"])
        elif kind == "comment":
            q["type"] = "text"
            q["multiline"] = True
        elif kind == "text":
            self._text_question(el, p, q)
        else:
            self.d.loss(
                "question_type",
                f"type={kind}",
                p,
                f"question type '{kind}' is not supported: '{name}' left out",
            )
            return
        self.types[qid] = q["type"]
        if q["type"] in ("single", "multi") and qid not in self.values:
            self.values[qid] = {str(c["value"]): c["value"] for c in q["choices"]}
        self._required(el, p, q)
        self._validators(el, p, q)
        self._report_ignored(el, p, kind)
        page["items"].append(q)

    def _text_question(self, el: dict[str, Any], p: str, q: dict[str, Any]) -> None:
        input_type = str(el.get("inputType") or "text")
        if input_type in ("number", "range"):
            q["type"] = "decimal"
            for key in ("min", "max"):
                if key in el:
                    v = _num(el[key], None)
                    if v is not None:
                        q[key] = v if isinstance(v, int) else str(v)
            if "step" in el:
                self.d.warn("step", "step", p + "/step", "number steps are not enforced")
        elif input_type == "date":
            q["type"] = "date"
            for key in ("min", "max"):
                if key in el:
                    self.d.loss(
                        "date_bounds", "min/max", p + "/" + key, "date limits are not supported"
                    )
        else:
            q["type"] = "text"
            if input_type not in (
                "text",
                "email",
                "tel",
                "url",
                "password",
                "color",
                "month",
                "week",
                "time",
                "datetime-local",
            ):
                self.d.warn(
                    "input_type",
                    f"inputType={input_type}",
                    p + "/inputType",
                    "imported as plain text",
                )
            elif input_type != "text":
                self.d.info(
                    "input_type",
                    f"inputType={input_type}",
                    p + "/inputType",
                    "imported as plain text (no format check)",
                )

    def _multipletext(
        self, el: dict[str, Any], p: str, page: dict[str, Any], base: dict[str, Any]
    ) -> None:
        items = el.get("items") or []
        self.d.info("multipletext", "multipletext", p, "each item becomes its own text question")
        page["items"].append({"type": "note", **base})
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            iname = str(item.get("name") or f"item{i + 1}")
            iid = self.ids.claim(f"{base['id']}_{iname}")
            title = self._localised(item.get("title"), p + pointer("items", i, "title")) or {
                self.default: iname
            }
            q = {"type": "text", "id": iid, "label": text_value(title, self.langs, self.default)}
            if "showIf" in base:
                q["showIf"] = base["showIf"]
            if item.get("isRequired") or el.get("isRequired"):
                q["required"] = True
            page["items"].append(q)
            self.types[iid] = "text"
            self.names[f"{el.get('name')}.{iname}"] = iid

    def _matrix(self, el: dict[str, Any], p: str, q: dict[str, Any]) -> bool:
        q["type"] = "matrix"
        columns = self._choices(el.get("columns"), p + "/columns", q["id"])
        if columns is None:
            self.d.loss(
                "no_choices", "columns", p, f"grid '{el.get('name')}' has no columns: left out"
            )
            return False
        q["choices"] = columns
        rows: list[dict[str, Any]] = []
        taken: set[str] = set()
        for i, r in enumerate(el.get("rows") or []):
            value, text = (r.get("value"), r.get("text")) if isinstance(r, dict) else (r, r)
            preferred = value if value not in (None, "") else f"row{i + 1}"
            rid = row_id(self.ids, q["id"], preferred, taken)
            label = self._localised(text, p + pointer("rows", i)) or {self.default: str(value)}
            rows.append({"id": rid, "label": text_value(label, self.langs, self.default)})
            self.names[f"{el.get('name')}.{value}"] = f"{q['id']}_{rid}"
            self.types[f"{q['id']}_{rid}"] = "single"
            self.values[f"{q['id']}_{rid}"] = {str(c["value"]): c["value"] for c in columns}
        if not rows:
            self.d.loss("no_rows", "rows", p, f"grid '{el.get('name')}' has no rows: left out")
            return False
        q["rows"] = rows
        if el.get("isAllRowRequired"):
            q["required"] = True
        for key in (
            "rowsVisibleIf",
            "columnsVisibleIf",
            "eachRowUnique",
            "hideIfRowsEmpty",
            "rowsOrder",
        ):
            if key in el:
                self.d.loss("matrix_property", key, p + "/" + key, f"grid '{key}' is not supported")
        return True

    def _rating(self, el: dict[str, Any], p: str, qid: str) -> list[dict[str, Any]]:
        values = el.get("rateValues")
        if isinstance(values, list) and values:
            choices = self._choices(values, p + "/rateValues", qid)
            if choices:
                return choices
        lo, hi, step = (
            _int(el.get("rateMin"), 1),
            _int(el.get("rateMax"), 5),
            _int(el.get("rateStep"), 1),
        )
        if step <= 0 or hi < lo or (hi - lo) // step > 100:
            lo, hi, step = 1, 5, 1
            self.d.warn("rating_range", "rateMin/rateMax", p, "unusable rating range: 1 to 5 used")
        out = [{"value": v, "label": str(v)} for v in range(lo, hi + 1, step)]
        min_label = self._localised(el.get("minRateDescription"), p + "/minRateDescription")
        max_label = self._localised(el.get("maxRateDescription"), p + "/maxRateDescription")
        if min_label:
            out[0]["label"] = text_value(
                {k: f"{lo} ({v})" for k, v in min_label.items() if v}, self.langs, self.default
            )
        if max_label:
            out[-1]["label"] = text_value(
                {k: f"{hi} ({v})" for k, v in max_label.items() if v}, self.langs, self.default
            )
        if el.get("rateType") in ("stars", "smileys"):
            self.d.info(
                "rating_type",
                f"rateType={el['rateType']}",
                p + "/rateType",
                "shown as numbered choices",
            )
        self.values[qid] = {str(c["value"]): c["value"] for c in out}
        return out

    def _choices(self, raw: Any, p: str, qid: str) -> list[dict[str, Any]] | None:
        if not isinstance(raw, list) or not raw:
            return None
        values: list[int | str] = []
        labels: list[dict[str, str]] = []
        for i, c in enumerate(raw):
            if isinstance(c, dict):
                v = c.get("value")
                label = self._localised(c.get("text"), p + pointer(i, "text")) or {
                    self.default: str(v)
                }
                if c.get("visibleIf") or c.get("enableIf"):
                    self.d.loss(
                        "choice_visible_if",
                        "choicesVisibleIf",
                        p + pointer(i),
                        "per-choice visibility is not supported",
                    )
            else:
                v = c
                label = {self.default: str(c)}
            values.append(choice_value(v))
            labels.append(label)
        values = harmonise_values(values)
        values, renamed = unique_values(values)
        for i in renamed:
            self.d.warn(
                "duplicate_choice",
                "choices",
                p + pointer(i),
                f"duplicate choice value renamed to {values[i]!r}",
            )
        self.values[qid] = {
            str(raw_v if not isinstance(raw_v, dict) else raw_v.get("value")): v
            for raw_v, v in zip(raw, values, strict=True)
        }
        return [
            {"value": v, "label": text_value(label, self.langs, self.default)}
            for v, label in zip(values, labels, strict=True)
        ]

    def _required(self, el: dict[str, Any], p: str, q: dict[str, Any]) -> None:
        if q["type"] == "note":
            return
        if el.get("isRequired") is True:
            q["required"] = True
        rif = el.get("requiredIf")
        if rif:
            self.d.warn(
                "required_if",
                "requiredIf",
                p + "/requiredIf",
                "conditional required is not supported: the question is optional",
            )
        if el.get("requiredErrorText"):
            self.d.info(
                "required_error_text",
                "requiredErrorText",
                p + "/requiredErrorText",
                "the standard 'required' message is shown",
            )

    def _validators(self, el: dict[str, Any], p: str, q: dict[str, Any]) -> None:
        for i, v in enumerate(el.get("validators") or []):
            vp = p + pointer("validators", i)
            if not isinstance(v, dict):
                continue
            vtype = v.get("type")
            if vtype == "numeric" and q["type"] in ("decimal", "integer", "slider"):
                for key, src in (("min", "minValue"), ("max", "maxValue")):
                    n = _num(v.get(src), None)
                    if n is not None:
                        q[key] = n if isinstance(n, int) else str(n)
                if v.get("text"):
                    self.d.info(
                        "validator_text",
                        "validators.text",
                        vp + "/text",
                        "the standard range message is shown",
                    )
                continue
            if vtype == "expression":
                cond = self._expr(v.get("expression"), vp + "/expression")
                if cond is not None and q["type"] != "note":
                    q["constraint"] = cond
                    msg = self._localised(v.get("text"), vp + "/text")
                    if msg:
                        q["constraintMessage"] = text_value(msg, self.langs, self.default)
                    continue
            self.d.loss(
                "validator", f"validator={vtype}", vp, f"validator '{vtype}' is not supported"
            )

    def _report_ignored(self, el: dict[str, Any], p: str, kind: str) -> None:
        for key, spec in _IGNORED_PROPS.items():
            if key not in el or spec is None:
                continue
            if (
                key
                in (
                    "showOtherItem",
                    "hasOther",
                    "showNoneItem",
                    "hasNone",
                    "showSelectAllItem",
                    "hasSelectAll",
                    "showCommentArea",
                    "hasComment",
                )
                and not el[key]
            ):
                continue
            feature, msg = spec
            self.d.loss("question_property", feature, p + "/" + key, msg)

    # -- text ----------------------------------------------------------------------------

    def _label(self, el: dict[str, Any], p: str, name: str) -> str | dict[str, str]:
        src = (
            el.get("title")
            if el.get("title") not in (None, "")
            else el.get("html")
            if el.get("type") == "html"
            else None
        )
        if src is None and el.get("type") == "image":
            src = el.get("imageLink") or name
        texts = self._localised(src, p + "/title") or {self.default: name}
        return text_value(texts, self.langs, self.default)

    def _localised(self, raw: Any, p: str) -> dict[str, str]:
        """A SurveyJS localisable string as {language: plain text}."""
        if raw is None:
            return {}
        if isinstance(raw, (int, float, bool)):
            raw = str(raw)
        if isinstance(raw, str):
            return {self.default: self._plain(raw, p)}
        if isinstance(raw, dict):
            out: dict[str, str] = {}
            for k, v in raw.items():
                if not isinstance(v, str):
                    continue
                lang = self.default if k == "default" else language_tag(k, "")
                if lang in self.langs:
                    out[lang] = self._plain(v, p)
            if self.default not in out and out:
                out[self.default] = next(iter(out.values()))
            return out
        return {}

    def _plain(self, raw: str, p: str) -> str:
        text, stripped = html_to_text(raw)
        if stripped:
            self.html_count += 1
        text, unresolved = rewrite_pipes(text, SJS_PIPE, lambda m: self.names.get(m.group(1)))
        for token in unresolved:
            self.d.loss(
                "pipe", "piping", p, f"piped value {token} could not be mapped and is shown as text"
            )
        text, bad = guard_our_pipes(text, lambda i: i in self.types or i in self.names.values())
        for token in bad:
            self.d.loss(
                "pipe", "piping", p, f"piped value {token} names no question and is shown as text"
            )
        return text

    # -- expressions ---------------------------------------------------------------------

    def _expr(self, raw: Any, p: str, value: bool = False) -> dict[str, Any] | None:
        if raw in (None, "", False):
            return None
        if not isinstance(raw, str):
            self.d.loss("expression", "expression", p, "an expression that is not text was dropped")
            return None
        result = parse_expression(raw, self.names, self.types, self.values, value=value)
        if result.expr is None:
            self.d.loss(
                "expression",
                "expression",
                p,
                f"expression {raw[:80]!r} could not be converted: {result.reason}",
            )
            return None
        for note in result.notes:
            self.d.warn("expression_approximated", "expression", p, note)
        return result.expr


def _num(v: Any, default: Any) -> Any:
    if isinstance(v, bool):
        return default
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v) if v.is_integer() else str(v)
    if isinstance(v, str):
        s = v.strip()
        try:
            return int(s)
        except ValueError:
            try:
                f = float(s)
            except ValueError:
                return default
            return int(f) if f.is_integer() else s
    return default


def _int(v: Any, default: int) -> int:
    n = _num(v, default)
    return n if isinstance(n, int) else default


__all__ = ["import_surveyjs"]
