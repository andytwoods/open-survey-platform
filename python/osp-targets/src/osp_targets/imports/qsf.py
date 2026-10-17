"""Qualtrics ``.qsf`` → ``osp-survey`` (task IM1).

Written from the public Qualtrics documentation and the shape of ``.qsf`` exports as
described there: a JSON object with ``SurveyEntry`` and ``SurveyElements`` (``BL`` blocks,
``FL`` flow, ``SQ`` questions, and bookkeeping elements). Clean-room: no Qualtrics code.

Mapping (every other feature is reported):

| Qualtrics                                        | osp-survey                                   |
|--------------------------------------------------|----------------------------------------------|
| block; "Page Break" elements                     | block; pages                                 |
| MC single (SAVR, SAHR, DL, SB, NPS)              | single                                       |
| MC multiple (MAVR, MAHR, MSB)                    | multi                                        |
| TE (SL, ML, ESTB, PW)                            | text (ML/ESTB multiline)                     |
| TE with ContentType ValidNumber / ValidDate      | decimal (or integer) / date                  |
| TE FORM                                          | one text question per field (lowered)        |
| Matrix Likert SingleAnswer / Bipolar / Profile   | matrix (statements × scale points)           |
| Matrix Likert MultipleAnswer                     | one multi question per statement (lowered)   |
| Slider (HSLIDER, HBAR, STAR)                     | one slider per statement                     |
| DB (descriptive text)                            | note                                         |
| DisplayLogic / BranchLogic (Selected, EqualTo …, EmbeddedField) | showIf / branch condition  |
| Flow: Block, Branch, BlockRandomizer, EndSurvey  | block, branch, randomiser, end nodes         |
| Flow: EmbeddedData, Group                        | embedded variables; children inline          |
| Randomization (choices), RandomizeQuestions      | choiceOrder / itemOrder shuffle              |
| ForceResponse ON / RequestResponse               | required / optional (reported)               |
| RecodeValues, DataExportTag, Language            | choice values, ids, translations             |
| RO, CS, SBS, HL, HM, PGR, DD, Timing, Meta, Captcha, FileUpload, Signature, |
  Authenticator, WebService, quotas, text-entry choices, custom validation … | reported losses |
"""

from __future__ import annotations

import json
import re
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
    skeleton,
    text_value,
    unique_values,
)

MAX_BYTES = 50_000_000
_PIPE = re.compile(r"\$\{(e://Field/([^}]+)|q://(QID[0-9]+)/[^}]*)\}")
_LOCATOR = re.compile(r"^q://(QID[0-9A-Za-z_]+)/([A-Za-z]+)(?:/([^/]+))?(?:/([^/]+))?$")

_SINGLE_SELECTORS = {"SAVR", "SAHR", "SACOL", "DL", "SB", "NPS"}
_MULTI_SELECTORS = {"MAVR", "MAHR", "MACOL", "MSB"}
_LOST_TYPES = {
    "RO": "rank order",
    "CS": "constant sum",
    "SBS": "side by side",
    "HL": "highlight",
    "HM": "heat map",
    "PGR": "pick, group and rank",
    "DD": "drill down",
    "Timing": "timing",
    "Meta": "meta info",
    "Captcha": "CAPTCHA",
    "FileUpload": "file upload",
    "Draw": "drawing",
    "Signature": "signature",
    "GAP": "graphic slider",
    "TB": "text/graphic block",
}
_COMPARE_OPS = {
    "EqualTo": "==",
    "NotEqualTo": "!=",
    "GreaterThan": ">",
    "LessThan": "<",
    "GreaterThanOrEqual": ">=",
    "LessThanOrEqual": "<=",
}


class _Skip(Exception):
    """A logic condition that cannot be expressed; carries the reason."""


def import_qsf(content: str | bytes) -> ImportResult:
    """Import a Qualtrics ``.qsf`` export. Never raises."""
    return guarded("qsf", lambda diags: _Importer(diags).run(content))


class _Importer:
    def __init__(self, diags: Diagnostics) -> None:
        self.d = diags
        self.ids = Ids()
        self.langs: list[str] = ["en"]
        self.default = "en"
        self.lang_map: dict[str, str] = {}  # Qualtrics code (upper) -> our tag
        self.questions: dict[str, dict[str, Any]] = {}  # QID -> payload
        self.qids: dict[str, str] = {}  # QID -> our id (the question, or the note of a split)
        self.types: dict[str, str] = {}  # our id -> type
        self.values: dict[str, dict[str, int | str]] = {}  # our id -> {choice id: value}
        self.rows: dict[str, dict[str, str]] = {}  # matrix our id -> {choice id: row id}
        self.split: dict[str, dict[str, str]] = {}  # QID -> {choice id: our id} (lowered)
        self.embedded: dict[str, str] = {}  # field -> our variable id
        self.embedded_types: dict[str, str] = {}  # our variable id -> text | decimal
        self.blocks: dict[str, str] = {}  # BL id -> our block id
        self.html_count = 0
        self.survey: dict[str, Any] = {}

    # -- entry ---------------------------------------------------------------------------

    def run(self, content: str | bytes) -> ImportResult:
        text = (
            content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
        )
        if len(text) > MAX_BYTES:
            self.d.error("too_large", "", "the file is larger than 50 MB")
            return ImportResult("qsf", None, self.d.items, [], None)
        try:
            doc = json.loads(text)
        except ValueError as exc:
            self.d.error("not_json", "", f"not valid JSON: {str(exc)[:80]}")
            return ImportResult("qsf", None, self.d.items, [], None)
        if not isinstance(doc, dict) or not isinstance(doc.get("SurveyElements"), list):
            self.d.error("not_qsf", "", "no 'SurveyElements' list: not a Qualtrics .qsf export")
            return ImportResult("qsf", None, self.d.items, [], None)
        entry = doc.get("SurveyEntry") if isinstance(doc.get("SurveyEntry"), dict) else {}
        elements = [e for e in doc["SurveyElements"] if isinstance(e, dict)]
        for i, e in enumerate(elements):
            if e.get("Element") == "SQ" and isinstance(e.get("Payload"), dict):
                qid = str(e.get("PrimaryAttribute") or e["Payload"].get("QuestionID") or f"QID{i}")
                self.questions[qid] = {
                    **e["Payload"],
                    "__ptr": pointer("SurveyElements", i, "Payload"),
                }
        blocks_payload = next(
            (e.get("Payload") for e in elements if e.get("Element") == "BL"), None
        )
        flow_payload = next((e.get("Payload") for e in elements if e.get("Element") == "FL"), None)
        options = next((e.get("Payload") for e in elements if e.get("Element") == "SO"), None)

        self._languages(entry)
        self.ids.reserve("survey")
        title = str(entry.get("SurveyName") or "Imported survey")
        self.survey = skeleton(self._text({self.default: title}), self.langs, self.default)
        if isinstance(options, dict):
            if str(options.get("BackButton", "")).lower() == "false":
                self.survey["settings"]["backNavigation"] = False
            for key, feature, msg in (
                ("Header", "header", "survey header HTML is not imported"),
                ("Footer", "footer", "survey footer HTML is not imported"),
                (
                    "EOSMessage",
                    "EOSMessage",
                    "custom end-of-survey messages from the library are not imported",
                ),
                ("SurveyExpiration", "SurveyExpiration", "expiry dates are a hosting matter here"),
                ("SurveyTermination", "SurveyTermination", "redirects at the end are not imported"),
                (
                    "ProgressBarDisplay",
                    "ProgressBarDisplay",
                    "the progress bar is a theme matter here",
                ),
                (
                    "PartialData",
                    "PartialData",
                    "partial-response handling is set under Settings here",
                ),
                (
                    "BallotBoxStuffingPrevention",
                    "BallotBoxStuffingPrevention",
                    "duplicate-response prevention is a hosting matter",
                ),
            ):
                v = options.get(key)
                if v not in (None, "", False, "false", "None", "NoProgressBar") and not (
                    key in ("Header", "Footer") and not str(v).strip()
                ):
                    sev = (
                        "info"
                        if key
                        in (
                            "ProgressBarDisplay",
                            "PartialData",
                            "BallotBoxStuffingPrevention",
                            "SurveyExpiration",
                        )
                        else "loss"
                    )
                    self.d.add(sev, "survey_option", feature, "/SurveyOptions/" + key, msg)
        for e in elements:
            if e.get("Element") in ("QO", "QUOTA", "Quota") or (e.get("Element") == "QC" and False):
                self.d.loss("quotas", "quotas", "/SurveyElements", "quotas are not imported")
            if e.get("Element") == "SCO" and isinstance(e.get("Payload"), dict) and e["Payload"]:
                self.d.loss(
                    "scoring", "scoring", "/SurveyElements", "scoring categories are not imported"
                )

        self._embedded(flow_payload)
        self._allocate(blocks_payload, flow_payload)
        self._blocks(blocks_payload)
        self.survey["flow"] = self._flow(flow_payload)
        if not any(n["type"] == "end" for n in self.survey["flow"]):
            self.survey["flow"].append({"type": "end", "id": self.ids.claim("end")})
        for qid, q in self.questions.items():
            if qid not in self.qids and qid not in self.split:
                self.d.info(
                    "question_not_in_block",
                    "question",
                    q["__ptr"],
                    f"{qid} is in no block and was left out",
                )
        if self.html_count:
            self.d.info(
                "html_stripped",
                "html",
                "",
                f"HTML formatting was removed from {self.html_count} text(s)",
            )
        ensure_not_empty(self.survey, self.d, self.ids)
        return finish("qsf", self.survey, self.d)

    # -- languages and text --------------------------------------------------------------

    def _languages(self, entry: dict[str, Any]) -> None:
        base = str(entry.get("SurveyLanguage") or "EN")
        found: list[str] = [base]
        for q in self.questions.values():
            lang = q.get("Language")
            if isinstance(lang, dict):
                found.extend(k for k in lang if isinstance(k, str))
        ours: list[str] = []
        for code in found:
            tag = language_tag(code, "")
            if not tag:
                self.d.warn(
                    "language",
                    "language",
                    "/SurveyEntry/SurveyLanguage",
                    f"language code {code!r} is not a valid tag: its texts are left out",
                )
                continue
            if tag not in ours:
                ours.append(tag)
            self.lang_map[code.upper()] = tag
        self.langs, self.default = (ours or ["en"]), (ours[0] if ours else "en")

    def _plain(self, raw: Any, ptr: str) -> str:
        text, stripped = html_to_text(raw)
        if stripped:
            self.html_count += 1
        text, unresolved = rewrite_pipes(text, _PIPE, self._pipe_target)
        for token in unresolved:
            self.d.loss(
                "pipe",
                "piping",
                ptr,
                f"piped text {token} could not be mapped and is shown as text",
            )
        text, bad = guard_our_pipes(text, lambda i: i in self.types)
        for token in bad:
            self.d.loss(
                "pipe", "piping", ptr, f"piped text {token} names no question and is shown as text"
            )
        return text

    def _pipe_target(self, m: re.Match[str]) -> str | None:
        if m.group(2):
            return self.embedded.get(m.group(2))
        ours = self.qids.get(m.group(3) or "")
        if ours is not None and self.types.get(ours) not in (None, "note", "matrix"):
            return ours
        return None

    def _text(self, texts: dict[str, str]) -> str | dict[str, str]:
        return text_value(texts, self.langs, self.default)

    def _localised(self, q: dict[str, Any], key: str, ptr: str, base: Any = None) -> dict[str, str]:
        out = {self.default: self._plain(q.get(key) if base is None else base, ptr)}
        lang = q.get("Language")
        if isinstance(lang, dict):
            for code, tr in lang.items():
                tag = self.lang_map.get(str(code).upper())
                if tag and isinstance(tr, dict) and isinstance(tr.get(key), str):
                    out[tag] = self._plain(tr[key], ptr)
        return out

    def _localised_choice(
        self, q: dict[str, Any], group: str, cid: str, ptr: str
    ) -> dict[str, str]:
        items = q.get(group) if isinstance(q.get(group), dict) else {}
        item = items.get(cid) if isinstance(items, dict) else None
        display = item.get("Display") if isinstance(item, dict) else item
        out = {self.default: self._plain(display if display is not None else cid, ptr)}
        lang = q.get("Language")
        if isinstance(lang, dict):
            for code, tr in lang.items():
                tag = self.lang_map.get(str(code).upper())
                if not tag or not isinstance(tr, dict):
                    continue
                titems = tr.get(group)
                titem = titems.get(cid) if isinstance(titems, dict) else None
                tdisplay = titem.get("Display") if isinstance(titem, dict) else titem
                if isinstance(tdisplay, str):
                    out[tag] = self._plain(tdisplay, ptr)
        return out

    # -- structure -----------------------------------------------------------------------

    def _block_list(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            items = [v for _k, v in sorted(payload.items(), key=lambda kv: _num_key(kv[0]))]
        elif isinstance(payload, list):
            items = payload
        else:
            return []
        return [b for b in items if isinstance(b, dict)]

    def _embedded(self, flow: Any) -> None:
        """Every EmbeddedData field in the flow becomes a session-start variable."""

        def walk(nodes: Any, ptr: str) -> None:
            if not isinstance(nodes, list):
                return
            for i, n in enumerate(nodes):
                if not isinstance(n, dict):
                    continue
                p = ptr + pointer(i)
                if n.get("Type") == "EmbeddedData":
                    for j, f in enumerate(n.get("EmbeddedData") or []):
                        if not isinstance(f, dict) or not f.get("Field"):
                            continue
                        name = str(f["Field"])
                        if name in self.embedded:
                            continue
                        vid = self.ids.claim(name)
                        var: dict[str, Any] = {"kind": "embedded", "id": vid, "param": name}
                        vt = str(f.get("VariableType") or "String")
                        if vt in ("Number", "Numeric"):
                            var["valueType"] = "decimal"
                        self.embedded_types[vid] = var.get("valueType", "text")
                        value = f.get("Value")
                        if value not in (None, ""):
                            var["default"] = str(value)
                        self.survey["variables"].append(var)
                        self.embedded[name] = vid
                        self.types[vid] = "embedded"
                        self.d.info(
                            "embedded_data",
                            "EmbeddedData",
                            p + pointer("EmbeddedData", j),
                            f"embedded data field {name!r} becomes a URL-parameter variable"
                            + (" with its value as the default" if "default" in var else ""),
                        )
                walk(n.get("Flow"), p + "/Flow")

        if isinstance(flow, dict):
            walk(flow.get("Flow"), "/Flow")

    def _allocate(self, blocks: Any, flow: Any) -> None:
        """Ids for every question in block order (references resolve in that order)."""
        for b in self._block_list(blocks):
            if str(b.get("Type")) == "Trash":
                continue
            for el in b.get("BlockElements") or []:
                if isinstance(el, dict) and el.get("Type") == "Question":
                    qid = str(el.get("QuestionID"))
                    q = self.questions.get(qid)
                    if q is not None and qid not in self.qids:
                        self.qids[qid] = self.ids.claim(q.get("DataExportTag") or qid)

    def _blocks(self, payload: Any) -> None:
        for bi, b in enumerate(self._block_list(payload)):
            bptr = pointer("Blocks", bi)
            if str(b.get("Type")) == "Trash":
                n = len(b.get("BlockElements") or [])
                if n:
                    self.d.info(
                        "trash", "Trash block", bptr, f"{n} question(s) in the trash were left out"
                    )
                continue
            bl_id = str(b.get("ID") or f"BL_{bi}")
            block_id = self.ids.claim(b.get("Description") or bl_id)
            block: dict[str, Any] = {"id": block_id, "pages": []}
            if b.get("Description"):
                block["title"] = str(b["Description"])
            opts = b.get("Options") if isinstance(b.get("Options"), dict) else {}
            shuffle = str(opts.get("RandomizeQuestions", "false")).lower() not in (
                "false",
                "",
                "none",
            )
            if shuffle and str(opts.get("RandomizeQuestions")).lower() not in ("true", "randomall"):
                self.d.warn(
                    "randomize_questions",
                    "RandomizeQuestions",
                    bptr + "/Options",
                    f"question randomisation {opts.get('RandomizeQuestions')!r} is approximated "
                    "by shuffling each page",
                )
            if opts.get("Looping") or opts.get("LoopingOptions"):
                self.d.loss(
                    "loop_and_merge",
                    "Looping",
                    bptr + "/Options",
                    f"loop & merge on block {block_id!r} is not supported: the block runs once",
                )
            page: dict[str, Any] = {"id": self.ids.claim(block_id + "_p1"), "items": []}
            pages = [page]
            for el in b.get("BlockElements") or []:
                if not isinstance(el, dict):
                    continue
                if el.get("Type") == "Page Break":
                    page = {"id": self.ids.claim(f"{block_id}_p{len(pages) + 1}"), "items": []}
                    pages.append(page)
                    continue
                if el.get("Type") != "Question":
                    self.d.loss(
                        "block_element",
                        str(el.get("Type")),
                        bptr,
                        f"block element {el.get('Type')!r} is not supported",
                    )
                    continue
                q = self.questions.get(str(el.get("QuestionID")))
                if q is None:
                    self.d.loss(
                        "missing_question",
                        "Question",
                        bptr,
                        f"question {el.get('QuestionID')} is listed in a block but not in the file",
                    )
                    continue
                self._question(str(el.get("QuestionID")), q, page)
            for p in pages:
                if shuffle and len(p["items"]) > 1:
                    p["itemOrder"] = "shuffle"
            block["pages"] = pages
            self.survey["blocks"].append(block)
            self.blocks[bl_id] = block_id

    def _flow(self, payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            self.d.warn("no_flow", "Flow", "/Flow", "no survey flow: blocks run in order")
            return [
                {"type": "block", "id": self.ids.claim("n_" + b), "block": b}
                for b in self.blocks.values()
            ]
        return self._nodes(payload.get("Flow"), "/Flow")

    def _nodes(self, nodes: Any, ptr: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not isinstance(nodes, list):
            return out
        for i, n in enumerate(nodes):
            if not isinstance(n, dict):
                continue
            p = ptr + pointer(i)
            kind = str(n.get("Type") or "")
            fid = str(n.get("FlowID") or f"fl{i}")
            if kind in ("Block", "Standard"):
                block = self.blocks.get(str(n.get("ID")))
                if block is None:
                    self.d.loss(
                        "flow_block",
                        "Block",
                        p,
                        f"flow refers to block {n.get('ID')!r}, which was not imported",
                    )
                    continue
                if any(_mentions(x, block) for x in out) or any(
                    _mentions(x, block) for x in self.survey["flow"]
                ):
                    self.d.loss(
                        "block_reused",
                        "Block",
                        p,
                        f"block {block!r} appears twice in the flow: the second use was left out",
                    )
                    continue
                out.append({"type": "block", "id": self.ids.claim(fid), "block": block})
            elif kind == "Branch":
                try:
                    cond = self._logic(n.get("BranchLogic"), p + "/BranchLogic")
                except _Skip as exc:
                    self.d.loss(
                        "branch_logic",
                        "BranchLogic",
                        p,
                        f"branch condition could not be converted ({exc}): its contents run for "
                        "everyone",
                    )
                    out.extend(self._nodes(n.get("Flow"), p + "/Flow"))
                    continue
                then = self._nodes(n.get("Flow"), p + "/Flow")
                if then:
                    out.append(
                        {"type": "branch", "id": self.ids.claim(fid), "if": cond, "then": then}
                    )
            elif kind == "BlockRandomizer":
                children = [
                    c
                    for c in (
                        self._nodes([x], p + pointer("Flow", k))
                        for k, x in enumerate(n.get("Flow") or [])
                    )
                    if c
                ]
                flat = [
                    c[0]
                    if len(c) == 1
                    else {
                        "type": "branch",
                        "id": self.ids.claim(fid + "_g"),
                        "if": {"kind": "bool", "value": True},
                        "then": c,
                    }
                    for c in children
                ]
                if not flat:
                    continue
                node: dict[str, Any] = {
                    "type": "randomiser",
                    "id": self.ids.claim(fid),
                    "children": flat,
                }
                subset = n.get("SubSet")
                try:
                    k = int(subset) if subset not in (None, "", False) else 0
                except TypeError, ValueError:
                    k = 0
                if 0 < k < len(flat):
                    node["pick"] = k
                if n.get("EvenPresentation"):
                    self.d.info(
                        "even_presentation",
                        "EvenPresentation",
                        p,
                        "evenly presented randomisation is drawn independently per participant "
                        "here",
                    )
                out.append(node)
            elif kind == "EndSurvey":
                node = {"type": "end", "id": self.ids.claim(fid)}
                opts = n.get("Options") if isinstance(n.get("Options"), dict) else {}
                if str(opts.get("ResponseFlag", "")).lower() == "screened":
                    node["outcome"] = "screened_out"
                if opts.get("SurveyTermination") not in (None, "", "DefaultMessage"):
                    self.d.loss(
                        "end_termination",
                        "SurveyTermination",
                        p,
                        f"end option {opts.get('SurveyTermination')!r} (redirect / custom message) "
                        "is not imported",
                    )
                out.append(node)
            elif kind == "EmbeddedData":
                continue  # declared up front
            elif kind in ("Group", "Root", "TableOfContents"):
                if kind == "TableOfContents":
                    self.d.warn(
                        "table_of_contents",
                        "TableOfContents",
                        p,
                        "a table of contents runs as an ordinary sequence",
                    )
                out.extend(self._nodes(n.get("Flow"), p + "/Flow"))
            elif kind in (
                "Authenticator",
                "WebService",
                "ReferenceSurvey",
                "Conjoint",
                "Quota",
                "Supplemental",
            ):
                self.d.loss(
                    "flow_element",
                    kind,
                    p,
                    f"flow element {kind!r} is not supported"
                    + ("; its contents run for everyone" if n.get("Flow") else ""),
                )
                out.extend(self._nodes(n.get("Flow"), p + "/Flow"))
            else:
                self.d.loss(
                    "flow_element", kind or "?", p, f"unknown flow element {kind!r} was left out"
                )
                out.extend(self._nodes(n.get("Flow"), p + "/Flow"))
        return out

    # -- questions -----------------------------------------------------------------------

    def _question(self, qid: str, q: dict[str, Any], page: dict[str, Any]) -> None:
        ptr = q["__ptr"]
        qtype = str(q.get("QuestionType") or "")
        selector = str(q.get("Selector") or "")
        sub = str(q.get("SubSelector") or "")
        ours = self.qids.get(qid) or self.ids.claim(q.get("DataExportTag") or qid)
        self.qids[qid] = ours
        tag = str(q.get("DataExportTag") or qid)
        if qtype in _LOST_TYPES:
            self.d.loss(
                "question_type",
                f"QuestionType={qtype}",
                ptr,
                f"{_LOST_TYPES[qtype]} questions are not supported: {tag!r} left out",
            )
            return
        base: dict[str, Any] = {
            "id": ours,
            "label": self._text(self._localised(q, "QuestionText", ptr + "/QuestionText")),
        }
        try:
            cond = (
                self._logic(q.get("DisplayLogic"), ptr + "/DisplayLogic")
                if q.get("DisplayLogic")
                else None
            )
        except _Skip as exc:
            cond = None
            self.d.loss(
                "display_logic",
                "DisplayLogic",
                ptr + "/DisplayLogic",
                f"display logic of {tag!r} could not be converted ({exc}): shown always",
            )
        if cond is not None:
            base["showIf"] = cond
        if q.get("SkipLogic"):
            self.d.loss(
                "skip_logic",
                "SkipLogic",
                ptr + "/SkipLogic",
                f"skip logic on {tag!r} is not imported: use a branch in the flow",
            )
        if q.get("InPageDisplayLogic") or (
            isinstance(q.get("DisplayLogic"), dict) and q["DisplayLogic"].get("inPage")
        ):
            self.d.info(
                "in_page_logic",
                "inPage",
                ptr + "/DisplayLogic",
                f"in-page display logic on {tag!r} applies on the page like any condition",
            )
        if q.get("DefaultChoices") not in (None, False, "", {}, []):
            self.d.loss(
                "default_choices",
                "DefaultChoices",
                ptr + "/DefaultChoices",
                f"default choices of {tag!r} are not imported",
            )
        if q.get("CarryForward") or q.get("DynamicChoices") or q.get("DynamicAnswers"):
            self.d.loss(
                "carry_forward",
                "CarryForward",
                ptr,
                f"carried-forward choices on {tag!r} are not imported",
            )

        if qtype == "DB":
            page["items"].append({"type": "note", **base})
            self.types[ours] = "note"
            return
        required = self._required(q, ptr, tag)
        if qtype == "MC":
            if selector in _SINGLE_SELECTORS or selector in _MULTI_SELECTORS:
                out = {"type": "single" if selector in _SINGLE_SELECTORS else "multi", **base}
                choices = self._choices(q, "Choices", "ChoiceOrder", ptr, ours)
                if not choices:
                    self.d.loss("no_choices", "Choices", ptr, f"{tag!r} has no choices: left out")
                    return
                out["choices"] = choices
                self._choice_randomisation(q, out, ptr, tag)
            else:
                self.d.loss(
                    "selector",
                    f"MC/{selector}",
                    ptr,
                    f"multiple choice layout {selector!r} is not supported: {tag!r} left out",
                )
                return
        elif qtype == "TE":
            if selector == "FORM":
                self._split_text(q, base, page, required, ptr, qid)
                return
            out = {"type": "text", **base}
            if selector in ("ML", "ESTB"):
                out["multiline"] = True
            self._content_type(q, out, ptr, tag)
        elif qtype == "Matrix":
            if selector in ("Likert", "Bipolar", "Profile") and sub != "MultipleAnswer":
                out = {"type": "matrix", **base}
                cols = self._choices(q, "Answers", "AnswerOrder", ptr, ours)
                rows = self._matrix_rows(q, ptr, ours)
                if not cols or not rows:
                    self.d.loss(
                        "no_choices",
                        "Answers",
                        ptr,
                        f"grid {tag!r} has no rows or no scale points: left out",
                    )
                    return
                out["choices"], out["rows"] = cols, rows
                if selector == "Bipolar":
                    self.d.info(
                        "bipolar",
                        "Matrix/Bipolar",
                        ptr,
                        "bipolar statements are shown as rows with the scale points as columns",
                    )
                for rid in (r["id"] for r in rows):
                    self.types[f"{ours}_{rid}"] = "single"
                    self.values[f"{ours}_{rid}"] = self.values[ours]
                    self.ids.reserve(f"{ours}_{rid}")
                if sub == "DL":
                    self.d.info(
                        "matrix_dropdown",
                        "Matrix/Likert/DL",
                        ptr,
                        "drop-down grid cells are shown as radio buttons",
                    )
            elif selector == "Likert" and sub == "MultipleAnswer":
                self._split_multi_matrix(q, base, page, required, ptr, qid)
                return
            else:
                self.d.loss(
                    "selector",
                    f"Matrix/{selector}/{sub}",
                    ptr,
                    f"grid type {selector}/{sub} is not supported: {tag!r} left out",
                )
                return
        elif qtype == "Slider":
            self._sliders(q, base, page, required, ptr, qid, selector)
            return
        else:
            self.d.loss(
                "question_type",
                f"QuestionType={qtype}",
                ptr,
                f"question type {qtype!r} is not supported: {tag!r} left out",
            )
            return
        self.types[ours] = out["type"]
        if required and out["type"] != "note":
            out["required"] = True
        self._validation(q, out, ptr, tag)
        page["items"].append(out)

    def _required(self, q: dict[str, Any], ptr: str, tag: str) -> bool:
        settings = (
            (q.get("Validation") or {}).get("Settings")
            if isinstance(q.get("Validation"), dict)
            else None
        )
        if not isinstance(settings, dict):
            return False
        force = str(settings.get("ForceResponse") or "OFF").upper()
        if (
            force == "ON"
            and str(settings.get("ForceResponseType") or "ON").upper() == "REQUESTRESPONSE"
        ):
            self.d.warn(
                "request_response",
                "RequestResponse",
                ptr + "/Validation",
                f"{tag!r} only requests a response in Qualtrics: optional here",
            )
            return False
        if force == "ON":
            return True
        if force == "REQUESTRESPONSE":
            self.d.warn(
                "request_response",
                "RequestResponse",
                ptr + "/Validation",
                f"{tag!r} only requests a response in Qualtrics: optional here",
            )
        return False

    def _validation(self, q: dict[str, Any], out: dict[str, Any], ptr: str, tag: str) -> None:
        settings = (
            (q.get("Validation") or {}).get("Settings")
            if isinstance(q.get("Validation"), dict)
            else None
        )
        if not isinstance(settings, dict):
            return
        vtype = str(settings.get("Type") or "None")
        if vtype in ("None", "", "ContentType"):
            return
        self.d.loss(
            "validation",
            f"Validation={vtype}",
            ptr + "/Validation",
            f"validation {vtype!r} on {tag!r} is not supported",
        )

    def _content_type(self, q: dict[str, Any], out: dict[str, Any], ptr: str, tag: str) -> None:
        settings = (
            (q.get("Validation") or {}).get("Settings")
            if isinstance(q.get("Validation"), dict)
            else None
        )
        if not isinstance(settings, dict):
            return
        ctype = str(settings.get("ContentType") or "")
        if ctype == "ValidNumber":
            out["type"] = "decimal"
            spec = (
                settings.get("ValidNumber") if isinstance(settings.get("ValidNumber"), dict) else {}
            )
            decimals = str(spec.get("NumDecimals") or "").strip()
            if decimals == "0":
                out["type"] = "integer"
            for key in ("Min", "Max"):
                raw = str(spec.get(key) or "").strip()
                if not raw:
                    continue
                if re.fullmatch(r"-?\d+(\.\d+)?", raw):
                    v = int(raw) if "." not in raw else raw
                    if out["type"] == "integer" and isinstance(v, str):
                        v = int(float(v))
                    out[key.lower()] = v
                else:
                    self.d.loss(
                        "bound",
                        key,
                        ptr + "/Validation",
                        f"number limit {raw!r} on {tag!r} is not a number",
                    )
            out.pop("multiline", None)
        elif ctype == "ValidDate":
            out["type"] = "date"
            out.pop("multiline", None)
            self.d.info(
                "date",
                "ValidDate",
                ptr + "/Validation",
                f"{tag!r} becomes a date question (the date format is the browser's)",
            )
        elif ctype:
            self.d.loss(
                "content_type",
                f"ContentType={ctype}",
                ptr + "/Validation",
                f"content check {ctype!r} on {tag!r} is not supported",
            )

    def _choice_randomisation(
        self, q: dict[str, Any], out: dict[str, Any], ptr: str, tag: str
    ) -> None:
        r = q.get("Randomization")
        if (
            not isinstance(r, dict)
            or not r.get("Type")
            or str(r.get("Type")).lower() in ("none", "false")
        ):
            return
        out["choiceOrder"] = "shuffle"
        if str(r.get("Type")) != "All":
            self.d.warn(
                "choice_randomisation",
                f"Randomization={r.get('Type')}",
                ptr + "/Randomization",
                f"advanced choice randomisation on {tag!r} (fixed items, subsets) is "
                "approximated by shuffling all choices",
            )

    def _choice_ids(self, q: dict[str, Any], group: str, order_key: str) -> list[str]:
        items = q.get(group)
        if not isinstance(items, dict) or not items:
            return []
        order = q.get(order_key)
        ids = [str(x) for x in order if str(x) in items] if isinstance(order, list) else []
        ids += [k for k in sorted(items, key=_num_key) if k not in ids]
        return ids

    def _choices(
        self, q: dict[str, Any], group: str, order_key: str, ptr: str, ours: str
    ) -> list[dict[str, Any]]:
        cids = self._choice_ids(q, group, order_key)
        if not cids:
            return []
        recode = (
            q.get("RecodeValues")
            if group == "Choices" and isinstance(q.get("RecodeValues"), dict)
            else {}
        )
        values = harmonise_values([choice_value(recode.get(c, c)) for c in cids])
        values, renamed = unique_values(values)
        for i in renamed:
            self.d.warn(
                "duplicate_choice",
                "RecodeValues",
                ptr + "/RecodeValues",
                f"duplicate recode value renamed to {values[i]!r}",
            )
        self.values[ours] = {c: v for c, v in zip(cids, values, strict=True)}
        out: list[dict[str, Any]] = []
        for c, v in zip(cids, values, strict=True):
            item = q[group].get(c)
            if isinstance(item, dict) and str(item.get("TextEntry", "")).lower() == "true":
                self.d.loss(
                    "text_entry_choice",
                    "TextEntry",
                    ptr + pointer(group, c),
                    f"the text box on choice {c} is not supported",
                )
            if isinstance(item, dict) and item.get("ExclusiveAnswer") not in (None, False, "false"):
                self.d.loss(
                    "exclusive_choice",
                    "ExclusiveAnswer",
                    ptr + pointer(group, c),
                    f"the exclusive choice {c} is an ordinary choice here",
                )
            out.append(
                {
                    "value": v,
                    "label": self._text(
                        self._localised_choice(q, group, c, ptr + pointer(group, c))
                    ),
                }
            )
        return out

    def _matrix_rows(self, q: dict[str, Any], ptr: str, ours: str) -> list[dict[str, Any]]:
        cids = self._choice_ids(q, "Choices", "ChoiceOrder")
        row_ids = Ids()
        rows: list[dict[str, Any]] = []
        mapping: dict[str, str] = {}
        tags = (
            q.get("ChoiceDataExportTags") if isinstance(q.get("ChoiceDataExportTags"), dict) else {}
        )
        for c in cids:
            rid = row_ids.claim(tags.get(c) or f"r{c}", "row")
            mapping[c] = rid
            rows.append(
                {
                    "id": rid,
                    "label": self._text(
                        self._localised_choice(q, "Choices", c, ptr + pointer("Choices", c))
                    ),
                }
            )
        self.rows[ours] = mapping
        if isinstance(q.get("Randomization"), dict) and q["Randomization"].get("Type"):
            self.d.loss(
                "row_randomisation",
                "Randomization",
                ptr + "/Randomization",
                "statement (row) randomisation in grids is not supported",
            )
        return rows

    def _split_text(
        self,
        q: dict[str, Any],
        base: dict[str, Any],
        page: dict[str, Any],
        required: bool,
        ptr: str,
        qid: str,
    ) -> None:
        cids = self._choice_ids(q, "Choices", "ChoiceOrder")
        self.d.info("form", "TE/FORM", ptr, "each form field becomes its own text question")
        page["items"].append({"type": "note", **base})
        self.types[base["id"]] = "note"
        self.split[qid] = {}
        for c in cids:
            cid = self.ids.claim(f"{base['id']}_{c}")
            item: dict[str, Any] = {
                "type": "text",
                "id": cid,
                "label": self._text(
                    self._localised_choice(q, "Choices", c, ptr + pointer("Choices", c))
                ),
            }
            if "showIf" in base:
                item["showIf"] = base["showIf"]
            if required:
                item["required"] = True
            page["items"].append(item)
            self.types[cid] = "text"
            self.split[qid][c] = cid

    def _split_multi_matrix(
        self,
        q: dict[str, Any],
        base: dict[str, Any],
        page: dict[str, Any],
        required: bool,
        ptr: str,
        qid: str,
    ) -> None:
        self.d.info(
            "multi_answer_grid",
            "Matrix/Likert/MultipleAnswer",
            ptr,
            "each statement of a multiple-answer grid becomes its own multiple-choice question",
        )
        page["items"].append({"type": "note", **base})
        self.types[base["id"]] = "note"
        self.split[qid] = {}
        cols_src = self._choice_ids(q, "Answers", "AnswerOrder")
        for c in self._choice_ids(q, "Choices", "ChoiceOrder"):
            cid = self.ids.claim(f"{base['id']}_{c}")
            values = harmonise_values([choice_value(a) for a in cols_src])
            item: dict[str, Any] = {
                "type": "multi",
                "id": cid,
                "label": self._text(
                    self._localised_choice(q, "Choices", c, ptr + pointer("Choices", c))
                ),
                "choices": [
                    {
                        "value": v,
                        "label": self._text(
                            self._localised_choice(q, "Answers", a, ptr + pointer("Answers", a))
                        ),
                    }
                    for a, v in zip(cols_src, values, strict=True)
                ],
            }
            if not item["choices"]:
                continue
            if "showIf" in base:
                item["showIf"] = base["showIf"]
            if required:
                item["required"] = True
            page["items"].append(item)
            self.types[cid] = "multi"
            self.values[cid] = {a: v for a, v in zip(cols_src, values, strict=True)}
            self.split[qid][c] = cid

    def _sliders(
        self,
        q: dict[str, Any],
        base: dict[str, Any],
        page: dict[str, Any],
        required: bool,
        ptr: str,
        qid: str,
        selector: str,
    ) -> None:
        cfg = q.get("Configuration") if isinstance(q.get("Configuration"), dict) else {}
        lo, hi = _num(cfg.get("CSSliderMin"), 0), _num(cfg.get("CSSliderMax"), 100)
        decimals = _num(cfg.get("NumDecimals"), 0)
        step: int | str = 1
        if isinstance(decimals, int) and decimals > 0:
            step = "0." + "0" * (decimals - 1) + "1"
        if selector == "STAR":
            self.d.info("stars", "Slider/STAR", ptr, "star ratings are shown as sliders")
        if selector not in ("HSLIDER", "HBAR", "STAR"):
            self.d.loss(
                "selector",
                f"Slider/{selector}",
                ptr,
                f"slider layout {selector!r} is not supported: left out",
            )
            return
        cids = self._choice_ids(q, "Choices", "ChoiceOrder")
        value_type = (
            "integer" if step == 1 and isinstance(lo, int) and isinstance(hi, int) else "decimal"
        )
        if value_type == "decimal":
            lo, hi, step = str(lo), str(hi), str(step)
        if hi <= lo if isinstance(lo, int) and isinstance(hi, int) else float(hi) <= float(lo):
            lo, hi = (0, 100) if value_type == "integer" else ("0", "100")
            self.d.warn(
                "slider_range",
                "CSSliderMin/Max",
                ptr + "/Configuration",
                "unusable slider range: 0 to 100 used",
            )
        common: dict[str, Any] = {
            "type": "slider",
            "valueType": value_type,
            "min": lo,
            "max": hi,
            "step": step,
        }
        if "showIf" in base:
            common["showIf"] = base["showIf"]
        if required:
            common["required"] = True
        if len(cids) <= 1:
            item = {**common, "id": base["id"], "label": base["label"]}
            page["items"].append(item)
            self.types[base["id"]] = "slider"
            return
        self.d.info(
            "slider_statements",
            "Slider",
            ptr,
            "each slider statement becomes its own slider question",
        )
        page["items"].append(
            {
                "type": "note",
                "id": base["id"],
                "label": base["label"],
                **({"showIf": base["showIf"]} if "showIf" in base else {}),
            }
        )
        self.types[base["id"]] = "note"
        self.split[qid] = {}
        for c in cids:
            cid = self.ids.claim(f"{base['id']}_{c}")
            page["items"].append(
                {
                    **common,
                    "id": cid,
                    "label": self._text(
                        self._localised_choice(q, "Choices", c, ptr + pointer("Choices", c))
                    ),
                }
            )
            self.types[cid] = "slider"
            self.split[qid][c] = cid

    # -- logic ---------------------------------------------------------------------------

    def _logic(self, logic: Any, ptr: str) -> dict[str, Any] | None:
        """DisplayLogic / BranchLogic: numbered condition sets, each a numbered list of
        conditions, joined by each item's ``Conjuction`` (sic) with the previous one."""
        if not isinstance(logic, dict):
            raise _Skip("logic is not an object")
        sets = [(k, v) for k, v in logic.items() if k.isdigit() and isinstance(v, dict)]
        if not sets:
            raise _Skip("no condition sets")
        groups: list[tuple[str, dict[str, Any]]] = []
        for k, s in sorted(sets, key=lambda kv: int(kv[0])):
            conds = [(ck, cv) for ck, cv in s.items() if ck.isdigit() and isinstance(cv, dict)]
            if not conds:
                raise _Skip("empty condition set")
            parts: list[tuple[str, dict[str, Any]]] = []
            for ck, c in sorted(conds, key=lambda kv: int(kv[0])):
                parts.append(
                    (
                        str(c.get("Conjuction") or c.get("Conjunction") or "And"),
                        self._expression(c, ptr + pointer(k, ck)),
                    )
                )
            groups.append((str(s.get("Conjuction") or s.get("Conjunction") or "Or"), _join(parts)))
        return _join(groups)

    def _expression(self, c: dict[str, Any], ptr: str) -> dict[str, Any]:
        ltype = str(c.get("LogicType") or "Question")
        op = str(c.get("Operator") or "")
        if ltype == "EmbeddedField":
            name = str(c.get("LeftOperand") or "")
            vid = self.embedded.get(name)
            if vid is None:
                raise _Skip(f"embedded field {name!r} is not declared in the flow")
            ref = {"kind": "ref", "id": vid}
            return self._compare(
                ref, op, c.get("RightOperand"), self.embedded_types.get(vid, "text")
            )
        if ltype != "Question":
            raise _Skip(f"logic on {ltype} is not supported")
        locator = str(c.get("ChoiceLocator") or c.get("LeftOperand") or "")
        m = _LOCATOR.match(locator)
        if not m:
            raise _Skip(f"unreadable locator {locator!r}")
        qid, part, a, b = m.group(1), m.group(2), m.group(3), m.group(4)
        split = self.split.get(qid)
        ours = self.qids.get(qid)
        if ours is None and split is None:
            raise _Skip(f"{qid} was not imported")
        qtype = self.types.get(ours or "")
        if part == "SelectableChoice":
            if qtype == "matrix" and a is not None and b is not None:
                rid = self.rows.get(ours or "", {}).get(a)
                value = self.values.get(ours or "", {}).get(b)
                if rid is None or value is None:
                    raise _Skip("unknown grid row or column")
                ref = {"kind": "ref", "id": f"{ours}_{rid}"}
                return self._selected(ref, op, value, single=True)
            if split is not None and a in split and b is not None:  # a split multi-answer grid
                cid = split[a]
                value = self.values.get(cid, {}).get(b)
                if value is None:
                    raise _Skip("unknown grid column")
                return self._selected({"kind": "ref", "id": cid}, op, value, single=False)
            if qtype in ("single", "multi") and a is not None:
                value = self.values.get(ours or "", {}).get(a)
                if value is None:
                    raise _Skip(f"choice {a} of {qid} was not imported")
                return self._selected(
                    {"kind": "ref", "id": ours or ""}, op, value, single=qtype == "single"
                )
            raise _Skip(f"choice logic on a {qtype or 'split'} question")
        if part in ("ChoiceTextEntryValue", "ChoiceNumericEntryValue", "SelectableAnswer"):
            if split is not None and a in split:
                return self._compare(
                    {"kind": "ref", "id": split[a]},
                    op,
                    c.get("RightOperand"),
                    self.types.get(split[a]),
                )
            if qtype in ("text", "integer", "decimal", "date", "slider"):
                return self._compare(
                    {"kind": "ref", "id": ours or ""}, op, c.get("RightOperand"), qtype
                )
            raise _Skip(f"text-entry logic on a {qtype} question")
        if part == "QuestionText" or part == "Displayed":
            raise _Skip("logic on whether a question was displayed is not supported")
        raise _Skip(f"locator part {part!r} is not supported")

    def _selected(
        self, ref: dict[str, Any], op: str, value: int | str, single: bool
    ) -> dict[str, Any]:
        lit = (
            {"kind": "int", "value": value}
            if isinstance(value, int)
            else {"kind": "text", "value": value}
        )
        if op in ("Selected", "NotSelected"):
            test = (
                {"kind": "compare", "op": "==", "left": ref, "right": lit}
                if single
                else {"kind": "contains", "ref": ref, "value": lit}
            )
            return test if op == "Selected" else {"kind": "not", "arg": test}
        if op in ("Displayed", "NotDisplayed"):
            raise _Skip("logic on whether a choice was displayed is not supported")
        if op in ("Empty", "NotEmpty"):
            ans = {"kind": "answered", "ref": ref}
            return ans if op == "NotEmpty" else {"kind": "not", "arg": ans}
        raise _Skip(f"operator {op!r} on a choice")

    def _compare(
        self, ref: dict[str, Any], op: str, right: Any, qtype: str | None
    ) -> dict[str, Any]:
        if op in ("Empty", "NotEmpty"):
            ans = {"kind": "answered", "ref": ref}
            return ans if op == "NotEmpty" else {"kind": "not", "arg": ans}
        if op not in _COMPARE_OPS:
            raise _Skip(f"operator {op!r} is not supported")
        text = str(right if right is not None else "")
        if qtype in ("integer", "decimal", "slider") or (
            qtype is None and re.fullmatch(r"-?\d+(\.\d+)?", text)
        ):
            if not re.fullmatch(r"-?\d+(\.\d+)?", text):
                raise _Skip(f"{text!r} is not a number")
            lit: dict[str, Any] = (
                {"kind": "int", "value": int(text)}
                if "." not in text
                else {"kind": "decimal", "value": text}
            )
        else:
            lit = {"kind": "text", "value": text}
        return {"kind": "compare", "op": _COMPARE_OPS[op], "left": ref, "right": lit}


def _join(parts: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """Fold ``[(conj, expr)]`` left to right; ``And`` binds tighter than ``Or``."""
    ors: list[list[dict[str, Any]]] = [[parts[0][1]]]
    for conj, e in parts[1:]:
        if conj.lower() == "or":
            ors.append([e])
        else:
            ors[-1].append(e)
    ands = [g[0] if len(g) == 1 else {"kind": "and", "args": g} for g in ors]
    return ands[0] if len(ands) == 1 else {"kind": "or", "args": ands}


def _mentions(node: dict[str, Any], block: str) -> bool:
    if node["type"] == "block":
        return node["block"] == block
    return any(
        _mentions(c, block)
        for c in [*node.get("then", []), *node.get("else", []), *node.get("children", [])]
    )


def _num_key(k: Any) -> tuple[int, Any]:
    s = str(k)
    return (0, int(s)) if s.isdigit() else (1, s)


def _num(v: Any, default: Any) -> Any:
    if isinstance(v, bool):
        return default
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v) if v.is_integer() else str(v)
    if isinstance(v, str) and v.strip():
        try:
            return int(v.strip())
        except ValueError:
            try:
                f = float(v.strip())
            except ValueError:
                return default
            return int(f) if f.is_integer() else v.strip()
    return default


__all__ = ["import_qsf"]
