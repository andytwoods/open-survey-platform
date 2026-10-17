"""Shared plumbing for the importers (task IM1): diagnostics, the result, identifier
allocation, text handling and the final assembly of an ``osp-survey`` document.

Every importer builds a plain JSON document, then :func:`finish` validates it with
``osp_spec.parse``. A condition the validator refuses (a forward reference, a type
mismatch, an unknown id) is dropped with a ``loss`` diagnostic rather than failing the
import, so a draft can always be created from a file that parsed at all. Importers never
raise on input: :func:`guarded` turns any unexpected exception into an ``error``
diagnostic (AGENTS.md rule 3).
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Literal

from osp_expr.ast import KEYWORDS
from osp_spec import SPEC_VERSION, Diagnostic, parse
from osp_spec.reserved import reserved_reason
from pydantic import BaseModel, ConfigDict

Format = Literal["qsf", "lss", "surveyjs"]
FORMATS: tuple[Format, ...] = ("qsf", "lss", "surveyjs")
FORMAT_LABELS: dict[Format, str] = {
    "qsf": "Qualtrics (.qsf)",
    "lss": "LimeSurvey (.lss)",
    "surveyjs": "SurveyJS JSON",
}

Severity = Literal["info", "warning", "loss", "error"]

ID_MAX = 64
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NON_IDENT = re.compile(r"[^A-Za-z0-9_]+")
_INT = re.compile(r"^-?(0|[1-9][0-9]*)$")
_LANG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")
_WS = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_OUR_PIPE = re.compile(r"\$\{([^}]*)\}")

# Pointers into the imported document where a dropped condition is reported.
_CONDITION_KEYS = frozenset({"showIf", "constraint", "if", "when"})


# --- Diagnostics -------------------------------------------------------------------------


class ImportDiagnostic(BaseModel):
    """One thing the reader should know about the import.

    - ``severity``: ``info`` (carried over with a note), ``warning`` (carried over, but it
      will behave differently), ``loss`` (not carried over), ``error`` (nothing imported).
    - ``code``: ``<format>.<what>``, stable; ``feature``: the source feature concerned.
    - ``pointer``: where in the **source** file (an RFC 6901 pointer for JSON sources, a
      ``/table/row`` style path for ``.lss``); ``target``: an RFC 6901 pointer into the
      imported survey, when there is one.
    """

    model_config = ConfigDict(frozen=True)

    format: Format
    severity: Severity
    code: str
    feature: str
    pointer: str
    message: str
    target: str | None = None


class ImportSummary(BaseModel):
    """What the import produced, for the builder's preview."""

    model_config = ConfigDict(frozen=True)

    title: str
    languages: list[str]
    blocks: int
    pages: int
    questions: int
    byType: dict[str, int]
    choiceLists: int
    variables: int
    quotas: int
    flowNodes: int
    conditions: int  # showIf / constraint / branch conditions carried over
    losses: int
    warnings: int
    infos: int


@dataclass(frozen=True)
class ImportResult:
    """``survey`` is None only when nothing could be imported (``error`` diagnostics)."""

    format: Format
    survey: dict[str, Any] | None
    diagnostics: list[ImportDiagnostic]
    validation: list[Diagnostic]
    summary: ImportSummary | None

    @property
    def ok(self) -> bool:
        return self.survey is not None


def pointer(*parts: str | int) -> str:
    """Build an RFC 6901 pointer from path parts."""
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


class Diagnostics:
    """Collects diagnostics for one import, de-duplicated by (code, feature, pointer)."""

    def __init__(self, fmt: Format) -> None:
        self.format = fmt
        self.items: list[ImportDiagnostic] = []
        self._seen: set[tuple[str, str, str]] = set()

    def add(
        self,
        severity: Severity,
        what: str,
        feature: str,
        ptr: str,
        message: str,
        target: str | None = None,
    ) -> None:
        key = (what, feature, ptr)
        if key in self._seen:
            return
        self._seen.add(key)
        self.items.append(
            ImportDiagnostic(
                format=self.format,
                severity=severity,
                code=f"{self.format}.{what}",
                feature=feature,
                pointer=ptr,
                message=message,
                target=target,
            )
        )

    def info(self, what: str, feature: str, ptr: str, message: str, target: str | None = None):
        self.add("info", what, feature, ptr, message, target)

    def warn(self, what: str, feature: str, ptr: str, message: str, target: str | None = None):
        self.add("warning", what, feature, ptr, message, target)

    def loss(self, what: str, feature: str, ptr: str, message: str, target: str | None = None):
        self.add("loss", what, feature, ptr, message, target)

    def error(self, what: str, ptr: str, message: str) -> None:
        self.add("error", what, "", ptr, message)

    @property
    def failed(self) -> bool:
        return any(d.severity == "error" for d in self.items)


# --- Identifiers --------------------------------------------------------------------------


def sanitise_identifier(raw: object, fallback: str = "item") -> str:
    """``raw`` as an osp identifier: ``[A-Za-z_][A-Za-z0-9_]*``, at most 64 characters,
    not an expression keyword or a reserved name. Not checked for uniqueness."""
    text = str(raw) if raw is not None else ""
    s = _NON_IDENT.sub("_", text.strip()).strip("_")
    if not s:
        s = fallback
    if not (s[0].isalpha() or s[0] == "_"):
        s = "q_" + s
    s = s[:ID_MAX]
    if s.lower() in KEYWORDS or reserved_reason(s) is not None:
        s = (s + "_q")[:ID_MAX]
    while s.startswith("_"):  # a leading underscore is a platform column
        s = "q" + s
    return s[:ID_MAX]


class Ids:
    """Unique identifiers across the whole survey, compared ignoring case (names must be
    unique that way too, and every name defaults to its id)."""

    def __init__(self) -> None:
        self._taken: set[str] = set()

    def claim(self, preferred: object, fallback: str = "item") -> str:
        base = sanitise_identifier(preferred, fallback)
        name, n = base, 1
        while name.lower() in self._taken:
            n += 1
            suffix = f"_{n}"
            name = base[: ID_MAX - len(suffix)] + suffix
        self._taken.add(name.lower())
        return name

    def reserve(self, name: str) -> None:
        self._taken.add(name.lower())

    def is_free(self, name: str) -> bool:
        return name.lower() not in self._taken


# --- Values and text ----------------------------------------------------------------------


def choice_value(code: object) -> int | str:
    """A choice code as our value: an int when it is written as one, else text."""
    if isinstance(code, bool):
        return str(code).lower()
    if isinstance(code, int):
        return code
    text = str(code).strip() if code is not None else ""
    if _INT.match(text):
        try:
            return int(text)
        except ValueError:  # pragma: no cover - the regex rules this out
            return text
    return text


def harmonise_values(values: list[int | str]) -> list[int | str]:
    """One value type per list (a mixed list is a validator warning): all int or all text."""
    if all(isinstance(v, int) for v in values):
        return values
    return [str(v) for v in values]


def unique_values(values: list[int | str]) -> tuple[list[int | str], list[int]]:
    """Make duplicate values distinct (``<v>_2`` ...); returns the renamed indexes."""
    seen: set[str] = set()
    out: list[int | str] = []
    renamed: list[int] = []
    for i, v in enumerate(values):
        key = str(v)
        if key not in seen:
            seen.add(key)
            out.append(v)
            continue
        renamed.append(i)
        n = 2
        while f"{key}_{n}" in seen:
            n += 1
        new = f"{key}_{n}"
        seen.add(new)
        out.append(new)
    return harmonise_values(out), renamed


def language_tag(raw: object, fallback: str = "en") -> str:
    """A BCP 47-shaped tag from a platform's language code (``EN`` → ``en``, ``PT-BR`` →
    ``pt-BR``, ``de-informal`` kept); anything else becomes ``fallback``."""
    text = str(raw or "").strip().replace("_", "-")
    if not _LANG.match(text):
        return fallback
    parts = text.split("-")
    head = parts[0].lower()
    rest = [p.upper() if len(p) == 2 else p for p in parts[1:]]
    return "-".join([head, *rest])


class _TextExtractor(HTMLParser):
    """HTML → plain text: block elements and ``<br>`` become line breaks, scripts and
    styles are dropped, entities decoded."""

    _BLOCK = frozenset(
        {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table"}
    )
    _SKIP = frozenset({"script", "style"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self.saw_tag = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        self.saw_tag = True
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(value: object) -> tuple[str, bool]:
    """Plain text for a platform's HTML label, and whether any markup was removed."""
    raw = "" if value is None else str(value)
    if "<" not in raw and "&" not in raw:
        return _tidy(raw), False
    try:
        p = _TextExtractor()
        p.feed(raw)
        p.close()
        text = "".join(p.parts)
        return _tidy(text), p.saw_tag or text != raw
    except Exception:  # defensive: a broken fragment is kept as it is
        return _tidy(html.unescape(raw)), True


def _tidy(text: str) -> str:
    text = text.replace("\xa0", " ")
    lines = [_WS.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def rewrite_pipes(
    text: str, pattern: re.Pattern[str], resolve: Callable[[re.Match[str]], str | None]
) -> tuple[str, list[str]]:
    """Replace a platform's piping tokens with ours (``${id}``); unresolved tokens are
    kept as text and returned."""
    unresolved: list[str] = []

    def sub(m: re.Match[str]) -> str:
        ours = resolve(m)
        if ours is None:
            unresolved.append(m.group(0))
            return m.group(0)
        return "${" + ours + "}"

    return pattern.sub(sub, text), unresolved


def guard_our_pipes(text: str, known: Callable[[str], bool]) -> tuple[str, list[str]]:
    """A ``${...}`` left in a label that names no question would be a ``pipe.invalid``
    error: neutralise it (``$ {...}``) and report it."""
    bad: list[str] = []

    def sub(m: re.Match[str]) -> str:
        if _IDENT.match(m.group(1)) and known(m.group(1)):
            return m.group(0)
        bad.append(m.group(0))
        return "$ {" + m.group(1) + "}"

    return _OUR_PIPE.sub(sub, text), bad


def text_value(texts: dict[str, str], languages: list[str], default: str) -> str | dict[str, str]:
    """A ``Text`` for the survey: a plain string when there is one language, else a map
    restricted to the survey's languages (an empty map falls back to the default language).
    """
    picked = {lang: texts[lang] for lang in languages if lang in texts and texts[lang] != ""}
    if not picked:
        any_text = next((t for t in texts.values() if t), "")
        picked = {default: any_text}
    if len(languages) == 1:
        return picked.get(languages[0], next(iter(picked.values())))
    return picked


# --- Assembly ----------------------------------------------------------------------------


def skeleton(title: str | dict[str, str], languages: list[str], default: str) -> dict[str, Any]:
    return {
        "specVersion": SPEC_VERSION,
        "id": "survey",
        "metadata": {"title": title, "languages": languages, "defaultLanguage": default},
        "settings": {},
        "choiceLists": [],
        "variables": [],
        "blocks": [],
        "quotas": [],
        "flow": [],
    }


def ensure_not_empty(survey: dict[str, Any], diags: Diagnostics, ids: Ids) -> None:
    """A survey needs one block, one page and one item; blocks without pages and pages
    without items are dropped (reported), and an empty survey gets a note."""
    kept_blocks: list[dict[str, Any]] = []
    for b in survey["blocks"]:
        pages = [p for p in b["pages"] if p["items"]]
        if len(pages) != len(b["pages"]):
            diags.info(
                "empty_page",
                "page",
                "",
                f"block {b['id']!r}: {len(b['pages']) - len(pages)} page(s) without "
                "questions left out",
            )
        if not pages:
            diags.info("empty_block", "block", "", f"block {b['id']!r} has no questions: left out")
            continue
        b["pages"] = pages
        kept_blocks.append(b)
    survey["blocks"] = kept_blocks
    kept_ids = {b["id"] for b in kept_blocks}
    survey["flow"] = _prune_flow(survey["flow"], kept_ids)
    if not kept_blocks:
        bid, pid, nid = ids.claim("block"), ids.claim("page"), ids.claim("intro")
        default = survey["metadata"]["defaultLanguage"]
        survey["blocks"] = [
            {
                "id": bid,
                "pages": [
                    {"id": pid, "items": [{"type": "note", "id": nid, "label": {default: ""}}]}
                ],
            }
        ]
        survey["flow"] = [
            {"type": "block", "id": ids.claim("n_" + bid), "block": bid},
            *survey["flow"],
        ]
        diags.warn(
            "no_questions", "survey", "", "no questions were imported; an empty page was added"
        )
    elif not any(_mentions_block(n) for n in survey["flow"]):
        survey["flow"] = [
            *[
                {"type": "block", "id": ids.claim("n_" + b["id"]), "block": b["id"]}
                for b in kept_blocks
            ],
            *survey["flow"],
        ]


def _mentions_block(node: dict[str, Any]) -> bool:
    if node["type"] == "block":
        return True
    children = [*node.get("then", []), *node.get("else", []), *node.get("children", [])]
    return any(_mentions_block(c) for c in children)


def _prune_flow(nodes: list[dict[str, Any]], blocks: set[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for n in nodes:
        if n["type"] == "block":
            if n["block"] in blocks:
                out.append(n)
            continue
        if n["type"] == "branch":
            n = {
                **n,
                "then": _prune_flow(n["then"], blocks),
                "else": _prune_flow(n.get("else", []), blocks),
            }
            if not n["then"] and not n["else"]:
                continue
            if not n["else"]:
                n.pop("else")
        elif n["type"] == "randomiser":
            n = {**n, "children": _prune_flow(n["children"], blocks)}
            if not n["children"]:
                continue
            if n.get("pick") is not None and n["pick"] > len(n["children"]):
                n["pick"] = len(n["children"])
        out.append(n)
    return out


def resolve(doc: Any, ptr: str) -> Any:
    for raw in ptr.split("/")[1:]:
        part = raw.replace("~1", "/").replace("~0", "~")
        doc = doc[int(part)] if isinstance(doc, list) else doc[part]
    return doc


def _drop_condition(survey: dict[str, Any], ptr: str) -> str | None:
    """Remove the condition the pointer lies in (or the computed variable whose
    expression it is); returns the pointer of what was dropped."""
    parts = ptr.split("/")[1:]
    if len(parts) >= 3 and parts[0] == "variables" and parts[2] == "expr" and parts[1].isdigit():
        i = int(parts[1])
        if i < len(survey["variables"]):
            survey["variables"].pop(i)
            return pointer("variables", i)
    for depth in range(len(parts), 0, -1):
        key = parts[depth - 1].replace("~1", "/").replace("~0", "~")
        if key not in _CONDITION_KEYS:
            continue
        parent_ptr = "/" + "/".join(parts[: depth - 1]) if depth > 1 else ""
        try:
            parent = resolve(survey, parent_ptr) if parent_ptr else survey
        except KeyError, IndexError, ValueError, TypeError:
            return None
        if not isinstance(parent, dict) or key not in parent:
            return None
        if key == "if":  # a branch needs its condition: keep it, always true
            parent["if"] = {"kind": "bool", "value": True}
        elif key == "when":  # a quota needs its condition too
            parent["when"] = {"kind": "bool", "value": False}
        else:
            parent.pop(key, None)
            if key == "constraint":
                parent.pop("constraintMessage", None)
        return parent_ptr + "/" + parts[depth - 1]
    return None


def finish(fmt: Format, survey: dict[str, Any], diags: Diagnostics) -> ImportResult:
    """Validate the built document; drop conditions the validator refuses (reported as
    losses) and give up with an error only if errors remain."""
    validation: list[Diagnostic] = []
    for _attempt in range(50):
        validation = [d for d in parse(survey)[1]]
        errors = [d for d in validation if d.severity == "error"]
        if not errors:
            break
        dropped = False
        for d in errors:
            where = _drop_condition(survey, d.pointer)
            if where is not None:
                dropped = True
                what = "computed variable" if where.startswith("/variables") else "condition"
                diags.loss(
                    "condition_dropped",
                    what,
                    "",
                    f"a {what} could not be kept ({d.code}: {d.message})",
                    target=where,
                )
                break  # pointers shift once something is removed: validate again
        if not dropped:
            for d in errors[:20]:
                diags.error("invalid_result", d.pointer, f"{d.code}: {d.message}")
            return ImportResult(fmt, None, diags.items, validation, None)
    else:  # pragma: no cover - 50 dropped conditions in one file
        diags.error("invalid_result", "", "too many conditions could not be kept")
        return ImportResult(fmt, None, diags.items, validation, None)
    return ImportResult(fmt, survey, diags.items, validation, summarise(survey, diags.items))


def summarise(survey: dict[str, Any], diagnostics: Iterable[ImportDiagnostic]) -> ImportSummary:
    by_type: dict[str, int] = {}
    pages = questions = conditions = 0
    for b in survey["blocks"]:
        for p in b["pages"]:
            pages += 1
            conditions += "showIf" in p
            for q in p["items"]:
                questions += 1
                by_type[q["type"]] = by_type.get(q["type"], 0) + 1
                conditions += ("showIf" in q) + ("constraint" in q)
    conditions += sum(_branches(n) for n in survey["flow"])
    sev = {s: 0 for s in ("loss", "warning", "info")}
    for d in diagnostics:
        if d.severity in sev:
            sev[d.severity] += 1
    meta = survey["metadata"]
    title = meta["title"]
    if isinstance(title, dict):
        title = title.get(meta.get("defaultLanguage") or meta["languages"][0]) or next(
            iter(title.values()), ""
        )
    return ImportSummary(
        title=str(title),
        languages=list(meta["languages"]),
        blocks=len(survey["blocks"]),
        pages=pages,
        questions=questions,
        byType=dict(sorted(by_type.items())),
        choiceLists=len(survey.get("choiceLists", [])),
        variables=len(survey.get("variables", [])),
        quotas=len(survey.get("quotas", [])),
        flowNodes=sum(_count_nodes(n) for n in survey["flow"]),
        conditions=conditions,
        losses=sev["loss"],
        warnings=sev["warning"],
        infos=sev["info"],
    )


def _branches(node: dict[str, Any]) -> int:
    n = 1 if node["type"] == "branch" else 0
    for c in [*node.get("then", []), *node.get("else", []), *node.get("children", [])]:
        n += _branches(c)
    return n


def _count_nodes(node: dict[str, Any]) -> int:
    return 1 + sum(
        _count_nodes(c)
        for c in [*node.get("then", []), *node.get("else", []), *node.get("children", [])]
    )


def guarded(fmt: Format, fn: Callable[[Diagnostics], ImportResult]) -> ImportResult:
    """Run an importer; any unexpected exception becomes an ``error`` diagnostic."""
    diags = Diagnostics(fmt)
    try:
        return fn(diags)
    except Exception as exc:  # never crash on input (AGENTS.md rule 3)
        diags.error("internal", "", f"importer failed: {type(exc).__name__}")
        return ImportResult(fmt, None, diags.items, [], None)


__all__ = [
    "FORMATS",
    "FORMAT_LABELS",
    "Diagnostics",
    "Format",
    "Ids",
    "ImportDiagnostic",
    "ImportResult",
    "ImportSummary",
    "Severity",
    "choice_value",
    "ensure_not_empty",
    "finish",
    "guard_our_pipes",
    "harmonise_values",
    "html_to_text",
    "language_tag",
    "pointer",
    "rewrite_pipes",
    "sanitise_identifier",
    "skeleton",
    "summarise",
    "text_value",
    "unique_values",
]
