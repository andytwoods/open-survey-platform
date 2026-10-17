"""LimeSurvey ``.lss`` → ``osp-survey`` (task IM1).

Written from the public LimeSurvey manual (question types, question attributes, Expression
Manager) and the layout of our own hand-written spike file and exporter
(``osp_targets.lss``): a ``<document>`` of tables (``groups``, ``questions``,
``subquestions``, ``answers``, their ``*_l10ns`` companions, ``question_attributes``,
``surveys``, ``surveys_languagesettings``, ``quota*``). Both the 4.x+ layout (texts in
``*_l10ns`` tables) and the older one (texts inline with a ``language`` column) are read.
Clean-room: no LimeSurvey code.

Mapping (every other feature is reported):

| LimeSurvey                                   | osp-survey                                    |
|----------------------------------------------|-----------------------------------------------|
| question group                               | block (format G: one page; S: a page per
|                                              | question; A: one page for all) |
| N (numerical)                                | integer (``num_value_int_only``) or decimal |
| S, U, T (short / huge / long text)           | text (U, T multiline)                         |
| L, ! (list radio / dropdown), O (with comment)| single (the comment box is reported)          |
| M, P (multiple choice, with comments)        | multi (comments reported)                     |
| 5, Y, G (5 point, yes/no, gender)            | single with the fixed codes                   |
| F, H, A, B, C, E (arrays)                    | matrix (rows = subquestions, columns = answers) |
| K, Q (multiple numerical / short text)       | one decimal / text question per row (lowered) |
| D (date), X (text display)                   | date, note                                    |
| * (equation)                                 | computed variable when the expression maps    |
| hidden S with a default                      | embedded variable (URL parameter = code)      |
| relevance, grelevance                        | showIf (question, page)                       |
| em_validation_q (+ tip)                      | constraint (+ message)                        |
| random_order, random_group, randomization_group | choiceOrder, itemOrder, a randomiser node  |
| mandatory Y / S                              | required / optional (soft mandatory reported) |
| quotas (answer-code members)                 | quotas + a quota check after the last member  |
| welcome / end text                           | a note on a first page / the end message      |
| R, :, ;, 1, file upload, I, other=Y, array_filter, defaults, assessments … | reported losses |
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
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
    rewrite_pipes,
    skeleton,
    text_value,
    unique_values,
)
from .em_expr import EMNames, latched_draw, level_chain, parse_em, slider_step, strip_guards

MAX_BYTES = 50_000_000
_DOCTYPE = re.compile(r"<!(?:DOCTYPE|ENTITY)", re.IGNORECASE)
# Our own exporter lists the question codes it had to rename in a comment at the top.
_RENAMES = re.compile(r"Renamed question codes: ([^>]*?)\s*-->")
_PIPE = re.compile(r"\{([A-Za-z][A-Za-z0-9_]*)(?:\.(?:shown|NAOK|value|code))?\}")
_DECIMAL = re.compile(r"^-?\d+(\.\d+)?$")

_FIXED_SCALES: dict[str, list[tuple[str, str]]] = {
    "5": [(str(i), str(i)) for i in range(1, 6)],
    "A": [(str(i), str(i)) for i in range(1, 6)],
    "B": [(str(i), str(i)) for i in range(1, 11)],
    "Y": [("Y", "Yes"), ("N", "No")],
    "G": [("F", "Female"), ("M", "Male")],
    "C": [("Y", "Yes"), ("N", "No"), ("U", "Uncertain")],
    "E": [("I", "Increase"), ("S", "Same"), ("D", "Decrease")],
}
_LOST_TYPES = {
    "R": "ranking",
    ":": "array (numbers)",
    ";": "array (texts)",
    "1": "array (dual scale)",
    "|": "file upload",
    "I": "language switch",
}
_TYPE_NAMES = {
    "N": "numerical input",
    "S": "short free text",
    "U": "huge free text",
    "T": "long free text",
    "L": "list (radio)",
    "!": "list (dropdown)",
    "O": "list with comment",
    "M": "multiple choice",
    "P": "multiple choice with comments",
    "5": "5 point choice",
    "Y": "yes/no",
    "G": "gender",
    "F": "array",
    "H": "array by column",
    "A": "array (5 point)",
    "B": "array (10 point)",
    "C": "array (yes/no/uncertain)",
    "E": "array (increase/same/decrease)",
    "K": "multiple numerical input",
    "Q": "multiple short text",
    "D": "date/time",
    "X": "text display",
    "*": "equation",
}
# Attributes with a direct meaning here; every other non-empty attribute is reported once.
_HANDLED_ATTRS = {
    "hidden",
    "random_order",
    "random_group",
    "num_value_int_only",
    "min_num_value_n",
    "max_num_value_n",
    "em_validation_q",
    "em_validation_q_tip",
    "slider_min",
    "slider_max",
    "slider_accuracy",
    "slider_layout",
}
_LOST_ATTRS = {
    "array_filter": "array filters (choices shown by another answer)",
    "array_filter_exclude": "array filters (choices shown by another answer)",
    "exclude_all_others": "exclusive options",
    "exclude_all_others_auto": "exclusive options",
    "min_answers": "limits on the number of selected answers",
    "max_answers": "limits on the number of selected answers",
    "other_replace_text": "an 'Other' option",
    "other_comment_mandatory": "an 'Other' option",
    "other_numbers_only": "an 'Other' option",
    "equals_num_value": "sum checks on numbers",
    "min_num_value": "sum checks on numbers",
    "max_num_value": "sum checks on numbers",
    "preg_validation": "regular-expression validation",
    "em_validation_sq": "per-subquestion validation",
    "em_validation_sq_tip": "per-subquestion validation",
    "time_limit": "time limits",
    "maximum_chars": "text length limits",
    "numbers_only": "digits-only text boxes",
    "input_boxes": "input boxes in arrays",
    "dropdown_dates": "date drop-downs",
    "date_min": "date limits",
    "date_max": "date limits",
    "cssclass": "custom CSS classes",
    "statistics_showgraph": "statistics settings",
    "page_break": "page breaks inside a group (printable only)",
    "answer_order": "sorted answer order (kept as written)",
    "question_template": "question themes",
}


@dataclass
class _Q:
    qid: str
    gid: str
    type: str
    code: str
    order: int
    relevance: str
    mandatory: str
    other: str
    parent: str
    texts: dict[str, str] = field(default_factory=dict)  # lang -> question (HTML)
    helps: dict[str, str] = field(default_factory=dict)
    scale: str = "0"


@dataclass
class _Ans:
    aid: str
    qid: str
    code: str
    order: int
    scale: str
    texts: dict[str, str] = field(default_factory=dict)


@dataclass
class _Group:
    gid: str
    order: int
    relevance: str
    random: str
    names: dict[str, str] = field(default_factory=dict)
    descriptions: dict[str, str] = field(default_factory=dict)


def import_lss(content: str | bytes) -> ImportResult:
    """Import a LimeSurvey ``.lss`` survey structure file. Never raises."""
    return guarded("lss", lambda diags: _Importer(diags).run(content))


def _rows(root: ET.Element, table: str) -> list[dict[str, str]]:
    el = root.find(table)
    if el is None:
        return []
    out: list[dict[str, str]] = []
    for row in el.iter("row"):
        out.append({c.tag: (c.text or "") for c in row})
    return out


def _int(v: str | None, default: int = 0) -> int:
    try:
        return int(str(v).strip())
    except TypeError, ValueError:
        return default


class _Importer:
    def __init__(self, diags: Diagnostics) -> None:
        self.d = diags
        self.ids = Ids()
        self.langs: list[str] = ["en"]
        self.default = "en"
        self.lang_map: dict[str, str] = {}  # LimeSurvey code -> our tag
        self.codes: dict[str, str] = {}  # LS question code -> our id
        self.qid_code: dict[str, str] = {}  # qid -> code
        self.types: dict[str, str] = {}  # our id -> type
        self.values: dict[str, dict[str, int | str]] = {}  # our id -> {answer code: value}
        self.multi_codes: dict[str, dict[str, int | str]] = {}
        self.html_count = 0
        self.survey: dict[str, Any] = {}
        self.question_block: dict[str, str] = {}  # qid -> block id (for quota checks)
        self.block_order: list[str] = []
        self.preferred: dict[str, str] = {}  # LS code -> the name it had before our export
        self.draws: dict[str, int] = {}  # our exporter's latched random draws: code -> N
        self.assigned: list[str] = []  # assigned variables recovered from draw chains

    # -- entry ---------------------------------------------------------------------------

    def run(self, content: str | bytes) -> ImportResult:
        raw = content if isinstance(content, bytes) else content.encode("utf-8", "surrogatepass")
        if len(raw) > MAX_BYTES:
            self.d.error("too_large", "", "the file is larger than 50 MB")
            return ImportResult("lss", None, self.d.items, [], None)
        head = raw[:4096].decode("utf-8", errors="replace")
        if _DOCTYPE.search(head):
            self.d.error("doctype", "", "XML with a DOCTYPE or entity declarations is refused")
            return ImportResult("lss", None, self.d.items, [], None)
        m = _RENAMES.search(head)
        if m:
            for pair in m.group(1).split(","):
                ours, _, code = pair.strip().partition("=")
                if ours and code:
                    self.preferred[code.strip()] = ours.strip()
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            self.d.error("not_xml", "", f"not well-formed XML: {str(exc)[:80]}")
            return ImportResult("lss", None, self.d.items, [], None)
        doctype = root.findtext("LimeSurveyDocType")
        if root.tag != "document" or (doctype or "").strip() != "Survey":
            self.d.error(
                "not_lss",
                "",
                "not a LimeSurvey survey structure (LimeSurveyDocType is not 'Survey')",
            )
            return ImportResult("lss", None, self.d.items, [], None)

        survey_row = next(iter(_rows(root, "surveys")), {})
        self._languages(root, survey_row)
        self.ids.reserve("survey")
        l10n = {r.get("surveyls_language", ""): r for r in _rows(root, "surveys_languagesettings")}
        titles = self._texts_by_lang(
            {k: v.get("surveyls_title", "") for k, v in l10n.items()}, "/surveys_languagesettings"
        )
        if not any(titles.values()):
            titles = {self.default: "Imported survey"}
        self.survey = skeleton(
            text_value(titles, self.langs, self.default), self.langs, self.default
        )
        descs = self._texts_by_lang(
            {k: v.get("surveyls_description", "") for k, v in l10n.items()},
            "/surveys_languagesettings",
        )
        if any(descs.values()):
            self.survey["metadata"]["description"] = text_value(descs, self.langs, self.default)
        if survey_row.get("allowprev", "Y").strip().upper() == "N":
            self.survey["settings"]["backNavigation"] = False
        self._survey_notes(root, survey_row)

        groups = self._groups(root)
        questions, subs = self._questions(root)
        answers = self._answers(root)
        attrs: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        for r in _rows(root, "question_attributes"):
            attrs[r.get("qid", "")].append(
                (r.get("attribute", ""), r.get("value", ""), r.get("language", ""))
            )
        defaults = self._defaults(root)

        # Allocate ids for parent questions in document order, so references resolve.
        by_group: dict[str, list[_Q]] = defaultdict(list)
        for q in questions:
            by_group[q.gid].append(q)
        for g in groups:
            for q in sorted(by_group.get(g.gid, []), key=lambda x: (x.order, _int(x.qid))):
                self.qid_code[q.qid] = q.code
                if q.code and q.code not in self.codes:
                    self.codes[q.code] = self.ids.claim(self.preferred.get(q.code, q.code))
                else:
                    self.codes[q.code or q.qid] = self.ids.claim(q.code or f"q{q.qid}")
                    if q.code in self.codes:
                        self.d.warn(
                            "duplicate_code",
                            "question code",
                            f"/questions/{q.qid}",
                            f"question code {q.code!r} is used twice",
                        )

        fmt = (survey_row.get("format") or "G").strip().upper()
        if fmt not in ("G", "S", "A"):
            fmt = "G"
        welcome = self._texts_by_lang(
            {k: v.get("surveyls_welcometext", "") for k, v in l10n.items()},
            "/surveys_languagesettings",
        )
        if any(welcome.values()):
            wid = self.ids.claim("welcome")
            self.survey["blocks"].append(
                {
                    "id": wid,
                    "pages": [
                        {
                            "id": self.ids.claim("welcome_page"),
                            "items": [
                                {
                                    "type": "note",
                                    "id": self.ids.claim("welcome_text"),
                                    "label": text_value(welcome, self.langs, self.default),
                                }
                            ],
                        }
                    ],
                }
            )
            self.survey["flow"].append(
                {"type": "block", "id": self.ids.claim("n_welcome"), "block": wid}
            )
            self.d.info(
                "welcome_text",
                "welcome text",
                "/surveys_languagesettings",
                "the welcome text becomes a note on its own first page",
            )

        all_in_one: dict[str, Any] | None = None
        if fmt == "A":
            all_in_one = {
                "id": self.ids.claim("all"),
                "pages": [{"id": self.ids.claim("page"), "items": []}],
            }
            self.survey["blocks"].append(all_in_one)
            self.survey["flow"].append(
                {"type": "block", "id": self.ids.claim("n_all"), "block": all_in_one["id"]}
            )
            self.d.info(
                "format",
                "format=A",
                "/surveys/format",
                "all questions on one page, as the survey was set up",
            )

        random_run: list[dict[str, Any]] = []
        random_name: str | None = None
        for g in groups:
            gq = sorted(by_group.get(g.gid, []), key=lambda x: (x.order, _int(x.qid)))
            gptr = f"/groups/{g.gid}"
            page_cond = self._condition(g.relevance, gptr + "/grelevance")
            if all_in_one is not None:
                if page_cond is not None:
                    self.d.warn(
                        "group_relevance_all_in_one",
                        "grelevance",
                        gptr,
                        "a group condition on an all-in-one survey is applied to each of its "
                        "questions",
                    )
                for q in gq:
                    self._question(
                        q,
                        subs.get(q.qid, []),
                        answers.get(q.qid, []),
                        attrs.get(q.qid, []),
                        defaults,
                        all_in_one["pages"][0],
                        all_in_one["id"],
                        page_cond,
                    )
                continue
            block_id = self.ids.claim(
                "g" + (g.names.get(self.default) or g.gid)
                if not g.names.get(self.default)
                else g.names.get(self.default, g.gid)
            )
            block: dict[str, Any] = {"id": block_id, "pages": []}
            title = self._texts_by_lang(g.names, gptr)
            if any(title.values()):
                block["title"] = title.get(self.default) or next(iter(title.values()))
            if fmt == "S":
                pages = [
                    {"id": self.ids.claim(f"{block_id}_p{i + 1}"), "items": []}
                    for i in range(len(gq))
                ]
            else:
                pages = [{"id": self.ids.claim(block_id + "_page"), "items": []}]
            desc = self._texts_by_lang(g.descriptions, gptr + "/description")
            if pages and any(desc.values()):
                pages[0]["title"] = text_value(
                    title if any(title.values()) else desc, self.langs, self.default
                )
                if any(title.values()):
                    pages[0]["items"].append(
                        {
                            "type": "note",
                            "id": self.ids.claim(block_id + "_desc"),
                            "label": text_value(desc, self.langs, self.default),
                        }
                    )
            for p in pages:
                if page_cond is not None:
                    p["showIf"] = page_cond
            for i, q in enumerate(gq):
                self._question(
                    q,
                    subs.get(q.qid, []),
                    answers.get(q.qid, []),
                    attrs.get(q.qid, []),
                    defaults,
                    pages[i if fmt == "S" else 0],
                    block_id,
                    None,
                )
            if fmt != "S":
                self._item_order(pages[0], gq, attrs)
            block["pages"] = pages
            self.survey["blocks"].append(block)
            self.block_order.append(block_id)
            node = {"type": "block", "id": self.ids.claim("n_" + block_id), "block": block_id}
            if g.random:
                if g.random == random_name:
                    random_run.append(node)
                    continue
                self._flush_random(random_run, random_name)
                random_run, random_name = [node], g.random
                continue
            self._flush_random(random_run, random_name)
            random_run, random_name = [], None
            self.survey["flow"].append(node)
        self._flush_random(random_run, random_name)

        self._quotas(root)
        if self.assigned:
            self.survey["flow"].insert(
                0,
                {
                    "type": "assign",
                    "id": self.ids.claim("assign"),
                    "variables": list(self.assigned),
                },
            )
        end: dict[str, Any] = {"type": "end", "id": self.ids.claim("end")}
        endtext = self._texts_by_lang(
            {k: v.get("surveyls_endtext", "") for k, v in l10n.items()}, "/surveys_languagesettings"
        )
        if any(endtext.values()):
            end["message"] = text_value(endtext, self.langs, self.default)
        self.survey["flow"].append(end)
        if self.html_count:
            self.d.info(
                "html_stripped",
                "html",
                "",
                f"HTML formatting was removed from {self.html_count} text(s)",
            )
        ensure_not_empty(self.survey, self.d, self.ids)
        return finish("lss", self.survey, self.d)

    def _flush_random(self, run: list[dict[str, Any]], name: str | None) -> None:
        if not run:
            return
        if len(run) == 1:
            self.survey["flow"].append(run[0])
            return
        self.survey["flow"].append(
            {
                "type": "randomiser",
                "id": self.ids.claim("rand_" + (name or "groups")),
                "children": list(run),
            }
        )
        self.d.warn(
            "randomization_group",
            "randomization_group",
            "/groups",
            f"groups in randomization group {name!r} are shuffled by a randomiser node "
            "(LimeSurvey's own order is not reproduced)",
        )

    # -- survey level --------------------------------------------------------------------

    def _languages(self, root: ET.Element, survey_row: dict[str, str]) -> None:
        listed = [el.text.strip() for el in root.iter("language") if el.text and el.text.strip()]
        base = (survey_row.get("language") or (listed[0] if listed else "en")).strip()
        extra = [x for x in (survey_row.get("additional_languages") or "").split() if x]
        ls_langs = [
            base,
            *[x for x in extra if x != base],
            *[x for x in listed if x not in (base, *extra)],
        ]
        ours: list[str] = []
        for ls in ls_langs:
            tag = language_tag(ls, "")
            if not tag:
                self.d.warn(
                    "language",
                    "language",
                    "/languages",
                    f"language code {ls!r} is not a valid tag: its texts are left out",
                )
                continue
            if tag in ours:
                continue
            ours.append(tag)
            self.lang_map[ls] = tag
        if not ours:
            ours = ["en"]
            self.lang_map[base] = "en"
        self.langs, self.default = ours, ours[0]

    def _survey_notes(self, root: ET.Element, survey_row: dict[str, str]) -> None:
        if _rows(root, "conditions"):
            self.d.info(
                "conditions_table",
                "conditions",
                "/conditions",
                "the legacy conditions table is ignored: relevance equations carry the logic",
            )
        if _rows(root, "assessments"):
            self.d.loss(
                "assessments",
                "assessments",
                "/assessments",
                "assessments (scores) are not imported",
            )
        if _rows(root, "survey_url_parameters"):
            self.d.loss(
                "url_parameters",
                "survey_url_parameters",
                "/survey_url_parameters",
                "URL parameters that prefill questions are not imported",
            )
        for key, feature, msg in (
            ("tokenanswerspersistence", "tokens", "token-based access is a hosting matter here"),
            ("usecaptcha", "captcha", "CAPTCHA settings are not imported"),
            ("showprogress", "showprogress", "the progress bar is a theme matter here"),
            ("questionindex", "questionindex", "a question index is not shown"),
        ):
            v = (survey_row.get(key) or "").strip().upper()
            if v and v not in ("N", "0"):
                self.d.info("survey_setting", feature, f"/surveys/{key}", msg)
        if (survey_row.get("anonymized") or "").strip().upper() == "Y":
            self.d.info(
                "survey_setting",
                "anonymized",
                "/surveys/anonymized",
                "responses here carry no identity unless a host adds one",
            )

    # -- tables --------------------------------------------------------------------------

    def _groups(self, root: ET.Element) -> list[_Group]:
        groups: dict[str, _Group] = {}
        for r in _rows(root, "groups"):
            gid = r.get("gid", "")
            g = groups.get(gid)
            if g is None:
                g = groups[gid] = _Group(
                    gid,
                    _int(r.get("group_order")),
                    r.get("grelevance", "") or "",
                    (r.get("randomization_group") or "").strip(),
                )
            if "group_name" in r:  # old layout: one row per language
                lang = self.lang_map.get(r.get("language", ""), "")
                if lang:
                    g.names[lang] = r.get("group_name", "")
                    g.descriptions[lang] = r.get("description", "")
        for r in _rows(root, "group_l10ns"):
            g = groups.get(r.get("gid", ""))
            lang = self.lang_map.get(r.get("language", ""), "")
            if g is not None and lang:
                g.names[lang] = r.get("group_name", "")
                g.descriptions[lang] = r.get("description", "")
        return sorted(groups.values(), key=lambda g: (g.order, _int(g.gid)))

    def _questions(self, root: ET.Element) -> tuple[list[_Q], dict[str, list[_Q]]]:
        parents: dict[str, _Q] = {}
        subs: dict[str, _Q] = {}
        for table in ("questions", "subquestions"):
            for r in _rows(root, table):
                qid = r.get("qid", "")
                parent = (r.get("parent_qid") or "0").strip()
                store = parents if parent in ("", "0") else subs
                q = store.get(qid)
                if q is None:
                    q = store[qid] = _Q(
                        qid=qid,
                        gid=r.get("gid", ""),
                        type=(r.get("type") or "T").strip(),
                        code=(r.get("title") or "").strip(),
                        order=_int(r.get("question_order")),
                        relevance=(r.get("relevance") or "").strip(),
                        mandatory=(r.get("mandatory") or "N").strip().upper(),
                        other=(r.get("other") or "N").strip().upper(),
                        parent=parent,
                        scale=(r.get("scale_id") or "0").strip(),
                    )
                if "question" in r:  # old layout
                    lang = self.lang_map.get(r.get("language", ""), "")
                    if lang:
                        q.texts[lang] = r.get("question", "")
                        q.helps[lang] = r.get("help", "")
        for r in _rows(root, "question_l10ns"):
            q = parents.get(r.get("qid", "")) or subs.get(r.get("qid", ""))
            lang = self.lang_map.get(r.get("language", ""), "")
            if q is not None and lang:
                q.texts[lang] = r.get("question", "")
                q.helps[lang] = r.get("help", "")
        by_parent: dict[str, list[_Q]] = defaultdict(list)
        for s in subs.values():
            by_parent[s.parent].append(s)
        for lst in by_parent.values():
            lst.sort(key=lambda s: (s.scale, s.order, _int(s.qid)))
        return list(parents.values()), by_parent

    def _answers(self, root: ET.Element) -> dict[str, list[_Ans]]:
        answers: dict[str, _Ans] = {}
        by_q: dict[str, list[_Ans]] = defaultdict(list)
        for r in _rows(root, "answers"):
            aid = r.get("aid") or f"{r.get('qid')}:{r.get('code')}:{r.get('scale_id', '0')}"
            a = answers.get(aid)
            if a is None:
                a = answers[aid] = _Ans(
                    aid,
                    r.get("qid", ""),
                    (r.get("code") or "").strip(),
                    _int(r.get("sortorder")),
                    (r.get("scale_id") or "0").strip(),
                )
                by_q[a.qid].append(a)
            if "answer" in r:  # old layout
                lang = self.lang_map.get(r.get("language", ""), "")
                if lang:
                    a.texts[lang] = r.get("answer", "")
        for r in _rows(root, "answer_l10ns"):
            a = answers.get(r.get("aid", ""))
            lang = self.lang_map.get(r.get("language", ""), "")
            if a is not None and lang:
                a.texts[lang] = r.get("answer", "")
        for lst in by_q.values():
            lst.sort(key=lambda a: (a.scale, a.order, a.code))
        return by_q

    def _defaults(self, root: ET.Element) -> dict[str, str]:
        """qid → default value (base language, scale 0, no subquestion)."""
        by_dvid: dict[str, str] = {}
        for r in _rows(root, "defaultvalues"):
            if (r.get("sqid") or "0").strip() in ("", "0") and (
                r.get("scale_id") or "0"
            ).strip() in ("", "0"):
                by_dvid[r.get("dvid", "")] = r.get("qid", "")
                if "defaultvalue" in r:  # old layout
                    by_dvid[r.get("dvid", "")] = r.get("qid", "")
        out: dict[str, str] = {}
        for r in _rows(root, "defaultvalue_l10ns"):
            qid = by_dvid.get(r.get("dvid", ""))
            if qid and qid not in out and (r.get("defaultvalue") or "") != "":
                out[qid] = r.get("defaultvalue", "")
        for r in _rows(root, "defaultvalues"):  # old layout
            if (
                "defaultvalue" in r
                and (r.get("defaultvalue") or "") != ""
                and r.get("qid", "") not in out
            ):
                out[r.get("qid", "")] = r.get("defaultvalue", "")
        return out

    # -- questions -----------------------------------------------------------------------

    def _question(
        self,
        q: _Q,
        subs: list[_Q],
        answers: list[_Ans],
        attrs: list[tuple[str, str, str]],
        defaults: dict[str, str],
        page: dict[str, Any],
        block_id: str,
        extra_cond: dict[str, Any] | None,
    ) -> None:
        ptr = f"/questions/{q.qid}"
        qid = self.codes.get(q.code or q.qid) or self.ids.claim(q.code or f"q{q.qid}")
        self.question_block[q.qid] = block_id
        a = {name: value for name, value, _lang in attrs}
        tips = {
            self.lang_map.get(lang, ""): value
            for name, value, lang in attrs
            if name == "em_validation_q_tip" and value
        }
        hidden = a.get("hidden", "").strip() in ("1", "Y")
        tname = _TYPE_NAMES.get(q.type, q.type)
        label = self._texts_by_lang(q.texts, ptr + "/question")
        help_text = self._texts_by_lang(q.helps, ptr + "/help")

        if q.type in _LOST_TYPES:
            self.d.loss(
                "question_type",
                f"type={q.type}",
                ptr,
                f"{_LOST_TYPES[q.type]} questions are not supported: {q.code!r} left out",
            )
            return
        if q.type == "*":
            text = (q.texts.get(self.default) or next(iter(q.texts.values()), "")).strip()
            m = re.fullmatch(r"\{(.*)\}", text, re.DOTALL)
            if not m:
                self.d.loss(
                    "equation",
                    "equation",
                    ptr,
                    f"equation {q.code!r} is not a single {{...}} expression: left out",
                )
                return
            n = latched_draw(m.group(1), q.code)
            if n is not None:
                self.draws[q.code] = n
                self.d.info(
                    "random_draw",
                    "equation",
                    ptr,
                    f"random draw {q.code!r} is replaced by this platform's own seeded "
                    "randomisation",
                )
                return
            chain = level_chain(m.group(1))
            if chain is not None and chain[0] in self.draws:
                levels = harmonise_values([choice_value(x) for x in chain[1]])
                self.survey["variables"].append({"kind": "assigned", "id": qid, "levels": levels})
                self.types[qid] = "assigned"
                self.values[qid] = {x: v for x, v in zip(chain[1], levels, strict=True)}
                self.assigned.append(qid)
                self.d.info(
                    "assignment",
                    "equation",
                    ptr,
                    f"{q.code!r} is an assignment to one of {len(levels)} conditions: restored "
                    "as an assigned variable",
                )
                return
            result = parse_em(m.group(1), self._names(), value=True)
            if result.expr is None:
                self.d.loss(
                    "equation",
                    "equation",
                    ptr,
                    f"equation {q.code!r} could not be converted: {result.reason}",
                )
                return
            self.survey["variables"].append({"kind": "computed", "id": qid, "expr": result.expr})
            self.types[qid] = "computed"
            for n in result.notes:
                self.d.warn("expression_approximated", "equation", ptr, n)
            return
        if hidden and q.type in ("S", "T", "U", "N"):
            var: dict[str, Any] = {"kind": "embedded", "id": qid, "param": q.code or qid}
            if q.type == "N":
                var["valueType"] = "decimal"
            dv = defaults.get(q.qid)
            if dv is not None:
                var["default"] = (
                    dv if q.type != "N" or not _DECIMAL.match(dv) or "." in dv else int(dv)
                )
                if q.type == "N" and not _DECIMAL.match(dv):
                    var.pop("default")
            self.survey["variables"].append(var)
            self.types[qid] = "embedded"
            self.d.info(
                "hidden_field",
                "hidden",
                ptr,
                f"hidden {tname} {q.code!r} becomes a URL-parameter variable",
            )
            return
        if hidden:
            self.d.loss(
                "hidden_question",
                "hidden",
                ptr,
                f"hidden {tname} {q.code!r} cannot be imported: left out",
            )
            return

        base: dict[str, Any] = {"id": qid, "label": text_value(label, self.langs, self.default)}
        if any(help_text.values()):
            base["help"] = text_value(help_text, self.langs, self.default)
        cond = self._condition(q.relevance, ptr + "/relevance")
        if cond is not None and extra_cond is not None:
            cond = {"kind": "and", "args": [extra_cond, cond]}
        elif extra_cond is not None:
            cond = extra_cond
        if cond is not None:
            base["showIf"] = cond
        if q.other == "Y":
            self.d.loss(
                "other_option",
                "other=Y",
                ptr,
                f"the 'Other' option of {q.code!r} is not supported: add a text question",
            )
        if q.mandatory == "S":
            self.d.warn(
                "soft_mandatory",
                "mandatory=S",
                ptr,
                f"{q.code!r} is soft-mandatory in LimeSurvey: optional here",
            )
        required = q.mandatory == "Y"
        if q.type in ("K", "Q"):
            self._split(q, subs, base, page, required, a, tname)
            self._report_attrs(q, a, ptr)
            return

        out: dict[str, Any] = base
        if q.type == "X":
            out["type"] = "note"
        elif q.type == "D":
            out["type"] = "date"
        elif q.type in ("S", "T", "U"):
            out["type"] = "text"
            if q.type != "S":
                out["multiline"] = True
        elif q.type == "N":
            self._numeric(out, a, qid, ptr)
        elif q.type in ("L", "!", "O"):
            out["type"] = "single"
            out["choices"] = self._choices(answers, ptr, qid)
            if out["choices"] is None:
                self.d.loss(
                    "no_answers", "answers", ptr, f"{q.code!r} has no answer options: left out"
                )
                return
            if q.type == "O":
                self.d.loss(
                    "comment_box", "type=O", ptr, f"the comment box of {q.code!r} is not supported"
                )
        elif q.type in ("M", "P"):
            out["type"] = "multi"
            out["choices"] = self._sub_choices(subs, ptr, qid)
            if out["choices"] is None:
                self.d.loss(
                    "no_answers", "subquestions", ptr, f"{q.code!r} has no options: left out"
                )
                return
            if q.type == "P":
                self.d.loss(
                    "comment_box",
                    "type=P",
                    ptr,
                    f"the comment boxes of {q.code!r} are not supported",
                )
        elif q.type in ("5", "Y", "G"):
            out["type"] = "single"
            out["choices"] = self._fixed(q.type, qid)
        elif q.type in ("F", "H", "A", "B", "C", "E"):
            out["type"] = "matrix"
            cols = (
                self._choices([x for x in answers if x.scale in ("0", "")], ptr, qid)
                if q.type in ("F", "H")
                else self._fixed(q.type, qid)
            )
            if not cols:
                self.d.loss(
                    "no_answers", "answers", ptr, f"array {q.code!r} has no columns: left out"
                )
                return
            out["choices"] = cols
            rows = self._rows_of(subs, ptr, qid)
            if not rows:
                self.d.loss(
                    "no_rows", "subquestions", ptr, f"array {q.code!r} has no rows: left out"
                )
                return
            out["rows"] = rows
            if q.type == "H":
                self.d.info(
                    "array_by_column", "type=H", ptr, "array by column is shown as an ordinary grid"
                )
        else:
            self.d.loss(
                "question_type",
                f"type={q.type}",
                ptr,
                f"question type {q.type!r} is not supported: {q.code!r} left out",
            )
            return

        self.types[qid] = out["type"]
        if out["type"] in ("single", "multi", "matrix") and qid not in self.values:
            self.values[qid] = {}
        if out["type"] != "note":
            if required:
                out["required"] = True
            if out["type"] in ("single", "multi") and a.get("random_order", "").strip() == "1":
                out["choiceOrder"] = "shuffle"
            self._validation(out, a, tips, qid, ptr)
        if defaults.get(q.qid) not in (None, ""):
            self.d.loss(
                "default_value",
                "defaultvalues",
                ptr,
                f"the default answer of {q.code!r} is not imported: questions start unanswered",
            )
        self._report_attrs(q, a, ptr)
        page["items"].append(out)

    def _numeric(self, out: dict[str, Any], a: dict[str, str], qid: str, ptr: str) -> None:
        integer = a.get("num_value_int_only", "").strip() == "1"
        out["type"] = "integer" if integer else "decimal"
        for key, attr in (("min", "min_num_value_n"), ("max", "max_num_value_n")):
            raw = a.get(attr, "").strip()
            if not raw:
                continue
            if not _DECIMAL.match(raw):
                self.d.loss("bound", attr, ptr, f"{attr}={raw!r} is not a number: ignored")
                continue
            if integer and "." in raw:
                self.d.warn(
                    "bound", attr, ptr, f"{attr}={raw!r} rounded for a whole-number question"
                )
                raw = str(int(float(raw)))
            out[key] = int(raw) if "." not in raw else raw
        if a.get("slider_layout", "").strip() == "1":
            self.d.info(
                "slider_layout", "slider_layout", ptr, "a slider layout is shown as a number box"
            )

    def _split(
        self,
        q: _Q,
        subs: list[_Q],
        base: dict[str, Any],
        page: dict[str, Any],
        required: bool,
        a: dict[str, str],
        tname: str,
    ) -> None:
        ptr = f"/questions/{q.qid}"
        self.d.info(
            "split", f"type={q.type}", ptr, f"{tname} {q.code!r}: each row becomes its own question"
        )
        page["items"].append({"type": "note", **base})
        for s in subs:
            sid = self.ids.claim(f"{base['id']}_{s.code}")
            label = self._texts_by_lang(s.texts, f"/subquestions/{s.qid}/question")
            item: dict[str, Any] = {
                "type": "text" if q.type == "Q" else "decimal",
                "id": sid,
                "label": text_value(label, self.langs, self.default),
            }
            if "showIf" in base:
                item["showIf"] = base["showIf"]
            if required:
                item["required"] = True
            if q.type == "K":
                if a.get("num_value_int_only", "").strip() == "1":
                    item["type"] = "integer"
                for key, attr in (("min", "min_num_value_n"), ("max", "max_num_value_n")):
                    raw = a.get(attr, "").strip()
                    if raw and _DECIMAL.match(raw):
                        item[key] = int(raw) if "." not in raw else raw
            page["items"].append(item)
            self.codes[f"{q.code}_{s.code}"] = sid
            self.types[sid] = item["type"]

    def _validation(
        self, out: dict[str, Any], a: dict[str, str], tips: dict[str, str], qid: str, ptr: str
    ) -> None:
        raw = a.get("em_validation_q", "").strip()
        if not raw:
            return
        text = strip_guards(raw)
        step = slider_step(text) if out["type"] in ("integer", "decimal") else None
        if step is not None and self.codes.get(step[0]) == qid:
            # Our exporter's slider: a number box checked against min + k * step.
            integer = out["type"] == "integer"
            out["type"] = "slider"
            out["valueType"] = "integer" if integer else "decimal"
            out["step"] = int(float(step[2])) if integer else step[2]
            out["min"], out["max"] = (0, 100) if integer else ("0", "100")
            text = step[3]
        result = parse_em(text, self._names())
        if result.expr is None:
            self.d.loss(
                "validation",
                "em_validation_q",
                ptr,
                f"validation {raw[:80]!r} could not be converted: {result.reason}",
            )
            return
        for n in result.notes:
            self.d.warn("expression_approximated", "em_validation_q", ptr, n)
        expr: dict[str, Any] | None = result.expr
        if out["type"] == "matrix":
            if self._rows_required(out, expr):
                return
            self.d.loss(
                "validation", "em_validation_q", ptr, "grid validation equations are not supported"
            )
            return
        if out["type"] in ("integer", "decimal", "slider"):
            expr = self._lift_bounds(out, expr)
        if expr is None:
            return
        out["constraint"] = expr
        tips = {k: v for k, v in tips.items() if k}
        if tips:
            out["constraintMessage"] = text_value(
                self._texts_by_lang(tips, ptr), self.langs, self.default
            )

    def _lift_bounds(self, out: dict[str, Any], expr: dict[str, Any]) -> dict[str, Any] | None:
        """``q >= a and q <= b`` at the top of a constraint become ``min`` / ``max``."""
        args = list(expr["args"]) if expr.get("kind") == "and" else [expr]
        kept: list[dict[str, Any]] = []
        integer = out["type"] == "integer" or out.get("valueType") == "integer"
        for e in args:
            if (
                e.get("kind") == "compare"
                and e["op"] in (">=", "<=")
                and e["left"] == {"kind": "ref", "id": out["id"]}
                and e["right"]["kind"] in ("int", "decimal")
            ):
                value = e["right"]["value"]
                if integer and isinstance(value, str):
                    value = int(float(value))
                elif out["type"] == "slider" and not integer:
                    value = str(value)
                out["min" if e["op"] == ">=" else "max"] = value
                continue
            kept.append(e)
        if not kept or kept == [{"kind": "bool", "value": True}]:
            return None
        return kept[0] if len(kept) == 1 else {"kind": "and", "args": kept}

    def _rows_required(self, out: dict[str, Any], expr: dict[str, Any]) -> bool:
        """``!is_empty(m_r1.NAOK) and ...`` on a grid: those rows are required."""
        args = list(expr["args"]) if expr.get("kind") == "and" else [expr]
        rows = {f"{out['id']}_{r['id']}": r for r in out["rows"]}
        picked: list[dict[str, Any]] = []
        for e in args:
            if e.get("kind") != "answered" or e["ref"]["id"] not in rows:
                return False
            picked.append(rows[e["ref"]["id"]])
        for r in picked:
            r["required"] = True
        return True

    def _report_attrs(self, q: _Q, a: dict[str, str], ptr: str) -> None:
        for name, value in a.items():
            if not value.strip() or name in _HANDLED_ATTRS:
                continue
            if name in _LOST_ATTRS:
                if value.strip() in ("0", "N", "") and name not in (
                    "array_filter",
                    "preg_validation",
                    "em_validation_sq",
                    "date_min",
                    "date_max",
                ):
                    continue
                self.d.loss(
                    "attribute",
                    name,
                    f"/question_attributes/{name}",
                    f"{_LOST_ATTRS[name]} are not supported ({name})",
                )
            else:
                self.d.info(
                    "attribute_ignored",
                    name,
                    f"/question_attributes/{name}",
                    f"question attribute {name!r} has no counterpart and is ignored",
                )

    def _item_order(
        self, page: dict[str, Any], gq: list[_Q], attrs: dict[str, list[tuple[str, str, str]]]
    ) -> None:
        groups = [
            v.strip()
            for q in gq
            for n, v, _l in attrs.get(q.qid, [])
            if n == "random_group" and v.strip()
        ]
        if len(groups) >= 2:
            page["itemOrder"] = "shuffle"
            if len(groups) != len(gq) or len(set(groups)) > 1:
                self.d.warn(
                    "random_group",
                    "random_group",
                    f"/groups/{gq[0].gid}",
                    "only some questions of the group are shuffled in LimeSurvey: here the whole "
                    "page is",
                )

    # -- choices -------------------------------------------------------------------------

    def _choices(self, answers: list[_Ans], ptr: str, qid: str) -> list[dict[str, Any]] | None:
        if not answers:
            return None
        values = harmonise_values([choice_value(a.code) for a in answers])
        values, renamed = unique_values(values)
        for i in renamed:
            self.d.warn(
                "duplicate_answer",
                "answers",
                ptr,
                f"duplicate answer code renamed to {values[i]!r}",
            )
        self.values[qid] = {a.code: v for a, v in zip(answers, values, strict=True)}
        return [
            {
                "value": v,
                "label": text_value(
                    self._texts_by_lang(a.texts, f"/answers/{a.aid}"), self.langs, self.default
                ),
            }
            for a, v in zip(answers, values, strict=True)
        ]

    def _sub_choices(self, subs: list[_Q], ptr: str, qid: str) -> list[dict[str, Any]] | None:
        if not subs:
            return None
        values = harmonise_values([choice_value(s.code) for s in subs])
        values, renamed = unique_values(values)
        for i in renamed:
            self.d.warn(
                "duplicate_answer",
                "subquestions",
                ptr,
                f"duplicate option code renamed to {values[i]!r}",
            )
        self.multi_codes[qid] = {s.code: v for s, v in zip(subs, values, strict=True)}
        self.values[qid] = dict(self.multi_codes[qid])
        return [
            {
                "value": v,
                "label": text_value(
                    self._texts_by_lang(s.texts, f"/subquestions/{s.qid}"), self.langs, self.default
                ),
            }
            for s, v in zip(subs, values, strict=True)
        ]

    def _fixed(self, t: str, qid: str) -> list[dict[str, Any]]:
        scale = _FIXED_SCALES[t]
        values = harmonise_values([choice_value(c) for c, _ in scale])
        self.values[qid] = {c: v for (c, _), v in zip(scale, values, strict=True)}
        return [{"value": v, "label": label} for (_, label), v in zip(scale, values, strict=True)]

    def _rows_of(self, subs: list[_Q], ptr: str, qid: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        row_ids = Ids()
        for s in subs:
            if s.scale not in ("0", ""):
                continue
            rid = row_ids.claim(s.code, "row")
            rows.append(
                {
                    "id": rid,
                    "label": text_value(
                        self._texts_by_lang(s.texts, f"/subquestions/{s.qid}"),
                        self.langs,
                        self.default,
                    ),
                }
            )
            var = f"{qid}_{rid}"
            self.ids.reserve(var)
            self.codes[f"{self.qid_code.get(s.parent, '')}_{s.code}"] = var
            self.types[var] = "single"
            self.values[var] = self.values.get(qid, {})
        return rows

    # -- quotas --------------------------------------------------------------------------

    def _quotas(self, root: ET.Element) -> None:
        members: dict[str, list[dict[str, str]]] = defaultdict(list)
        for r in _rows(root, "quota_members"):
            members[r.get("quota_id", "")].append(r)
        names = {
            r.get("quotals_quota_id", ""): r.get("quotals_name", "")
            for r in _rows(root, "quota_languagesettings")
        }
        for r in _rows(root, "quota"):
            qid = r.get("id", "")
            ptr = f"/quota/{qid}"
            name = names.get(qid) or r.get("name") or f"quota{qid}"
            if (r.get("active") or "1").strip() not in ("1", "Y"):
                self.d.info("quota_inactive", "quota", ptr, f"inactive quota {name!r} is left out")
                continue
            by_question: dict[str, list[str]] = defaultdict(list)
            for m in members.get(qid, []):
                by_question[m.get("qid", "")].append((m.get("code") or "").strip())
            if not by_question:
                self.d.loss("quota", "quota", ptr, f"quota {name!r} has no members: left out")
                continue
            parts: list[dict[str, Any]] = []
            last_block: str | None = None
            ok = True
            for lqid, codes in by_question.items():
                code = self.qid_code.get(lqid)
                ours = self.codes.get(code or "")
                if ours is None or self.types.get(ours) not in ("single", "multi"):
                    ok = False
                    break
                alts: list[dict[str, Any]] = []
                for c in codes:
                    v = self.values.get(ours, {}).get(c)
                    if v is None:
                        ok = False
                        break
                    lit = (
                        {"kind": "int", "value": v}
                        if isinstance(v, int)
                        else {"kind": "text", "value": v}
                    )
                    if self.types[ours] == "multi":
                        alts.append(
                            {"kind": "contains", "ref": {"kind": "ref", "id": ours}, "value": lit}
                        )
                    else:
                        alts.append(
                            {
                                "kind": "compare",
                                "op": "==",
                                "left": {"kind": "ref", "id": ours},
                                "right": lit,
                            }
                        )
                if not ok:
                    break
                parts.append(alts[0] if len(alts) == 1 else {"kind": "or", "args": alts})
                last_block = self.question_block.get(lqid, last_block)
            if not ok or not parts:
                self.d.loss(
                    "quota",
                    "quota",
                    ptr,
                    f"quota {name!r} refers to answers that were not imported: left out",
                )
                continue
            quota_id = self.ids.claim(name, "quota")
            self.survey["quotas"].append(
                {
                    "id": quota_id,
                    "when": parts[0] if len(parts) == 1 else {"kind": "and", "args": parts},
                    "limit": max(0, _int(r.get("qlimit"))),
                    "onFull": {"outcome": "quota_full"},
                }
            )
            check = {
                "type": "quotaCheck",
                "id": self.ids.claim("check_" + quota_id),
                "quota": quota_id,
            }
            self._insert_after_block(last_block, check)
            self.d.warn(
                "quota",
                "quota",
                ptr,
                f"quota {name!r} is checked after the page of its last question; LimeSurvey's "
                "message and URL are not imported",
            )

    def _insert_after_block(self, block_id: str | None, node: dict[str, Any]) -> None:
        flow = self.survey["flow"]
        if block_id is not None:
            for i, n in enumerate(flow):
                if n["type"] == "block" and n["block"] == block_id:
                    flow.insert(i + 1, node)
                    return
                if n["type"] == "randomiser" and any(
                    c.get("block") == block_id for c in n["children"]
                ):
                    flow.insert(i + 1, node)
                    return
        flow.append(node)

    # -- text and expressions ------------------------------------------------------------

    def _texts_by_lang(self, texts: dict[str, str], ptr: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for lang, raw in texts.items():
            if lang not in self.langs or raw is None:
                continue
            text, stripped = html_to_text(raw)
            if stripped:
                self.html_count += 1
            text, unresolved = rewrite_pipes(text, _PIPE, lambda m: self.codes.get(m.group(1)))
            for token in unresolved:
                self.d.loss(
                    "pipe",
                    "piping",
                    ptr,
                    f"placeholder {token} could not be mapped and is shown as text",
                )
            text, bad = guard_our_pipes(text, lambda i: i in self.types or i in self.codes.values())
            for token in bad:
                self.d.loss(
                    "pipe",
                    "piping",
                    ptr,
                    f"placeholder {token} names no question and is shown as text",
                )
            out[lang] = text
        return out

    def _names(self) -> EMNames:
        return EMNames(self.codes, self.qid_code, self.types, self.multi_codes, self.values)

    def _condition(self, raw: str, ptr: str) -> dict[str, Any] | None:
        text = (raw or "").strip()
        if text in ("", "1"):
            return None
        if text == "0":
            return {"kind": "bool", "value": False}
        result = parse_em(text, self._names())
        if result.expr is None:
            self.d.loss(
                "relevance",
                "relevance",
                ptr,
                f"condition {text[:80]!r} could not be converted: shown always ({result.reason})",
            )
            return None
        for n in result.notes:
            self.d.warn("expression_approximated", "relevance", ptr, n)
        if result.expr == {"kind": "bool", "value": True}:
            return None
        return result.expr


__all__ = ["import_lss"]
