"""Question bank documents (planning/question-bank.md §2): the bank item model, fragments
and the survey-level instrument list. Pure, no I/O.

- A **fragment** is the self-contained part of an `osp-survey` document around one
  question, page or block: the object, the shared choice lists it uses and the computed
  variables (the scoring recipe) that read only things inside it.
- `extract_fragment(survey, target_id)` cuts one out of a survey; references that point
  outside it (a `showIf`, `constraint` or `${pipe}`) are dropped and reported as
  `bank.external_ref` warnings.
- `check_fragment(fragment)` validates a fragment by building a one-block throwaway survey
  from it and running the ordinary validator, so a fragment can never be something a
  survey could not hold.
- `with_instruments(survey, lookup)` derives `metadata.instruments` from the `source`
  fields (lead decision 1), at publish.

Every function returns diagnostics instead of raising (golden rule 3).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable, Iterator, Mapping
from typing import Annotated, Any, Literal

from pydantic import Field, StrictInt, StrictStr, StringConstraints, ValidationError

from .diagnostics import Diagnostic, Severity, pointer
from .model import (
    BankLibrary,
    BankRef,
    Block,
    ChoiceList,
    ComputedVariable,
    Date,
    LanguageTag,
    LicenceClass,
    Model,
    Page,
    Question,
    Source,
)
from .validate import parse, validate

BANK_VERSION = "osp-bank-item/0.1"
KINDS = ("question", "page", "block")
MAX_BODY_BYTES = 256 * 1024
MAX_ITEMS = 200
MAX_TAGS = 20

# Every code this module emits, with its severity (tests check each one fires).
BANK_CODES: dict[str, Severity] = {
    "bank.invalid_survey": "error",  # the survey to extract from is not a valid document
    "bank.target_not_found": "error",  # no question, page or block has that id
    "bank.external_ref": "warning",  # a reference to outside the fragment was cut
    "bank.fragment_invalid": "error",  # the fragment (or bank item) breaks the model
    "bank.kind_mismatch": "error",  # `kind` and the fragment's object disagree
    "bank.too_large": "error",  # over MAX_BODY_BYTES or MAX_ITEMS
}

type Tag = Annotated[str, StringConstraints(min_length=1, max_length=40)]


def _diag(code: str, ptr: str, message: str) -> Diagnostic:
    return Diagnostic(severity=BANK_CODES[code], code=code, message=message, pointer=ptr)


# --- Models -----------------------------------------------------------------------------


class Fragment(Model):
    """The payload of a bank item: exactly one of `question`, `page`, `block` (by `kind`),
    with the shared choice lists it uses and its computed (scoring) variables."""

    choiceLists: list[ChoiceList] = Field(default_factory=list)
    variables: list[ComputedVariable] = Field(default_factory=list)
    question: Question | None = None
    page: Page | None = None
    block: Block | None = None


class BankLicence(Model):
    class_: LicenceClass = Field(alias="class")
    holder: StrictStr | None = None
    # The operative sentence of the holder's terms, quoted exactly.
    statement: StrictStr | None = None
    url: StrictStr | None = None  # the terms page the statement was read on
    evidenceDate: Date | None = None  # when it was read
    permission: StrictStr | None = None  # `author-permission`: the file under permissions/


class Citation(Model):
    text: StrictStr = Field(min_length=1)
    doi: StrictStr | None = None


class SourceRef(Model):
    url: StrictStr = Field(min_length=1)
    note: StrictStr | None = None


class Scoring(Model):
    text: StrictStr = Field(min_length=1)  # for people; the recipe is fragment.variables


class ProvenanceFrom(Model):
    library: BankLibrary
    id: BankRef
    version: StrictInt = Field(ge=1)


class Provenance(Model):
    from_: ProvenanceFrom = Field(alias="from")


class BankItem(Model):
    """One version of a bank item (question-bank.md §2.1)."""

    bankVersion: Literal["osp-bank-item/0.1"]
    id: BankRef
    version: StrictInt = Field(ge=1)
    kind: Literal["question", "page", "block"]
    title: StrictStr = Field(min_length=1, max_length=200)
    abbreviation: StrictStr | None = Field(default=None, max_length=40)
    description: StrictStr | None = None
    tags: list[Tag] = Field(default_factory=list, max_length=MAX_TAGS)
    languages: list[LanguageTag] = Field(default_factory=list)
    licence: BankLicence
    citation: Citation | None = None
    source: SourceRef | None = None
    scoring: Scoring | None = None
    provenance: Provenance | None = None
    fragment: Fragment


# --- Helpers ----------------------------------------------------------------------------

_PIPE = re.compile(r"\$\{([^}]*)\}")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Fields holding translatable text (piping allowed) and boolean conditions.
_TEXT_KEYS = frozenset(
    {"label", "help", "constraintMessage", "title", "minLabel", "maxLabel", "message"}
)
_CONDITION_KEYS = ("showIf", "constraint")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fragment_checksum(fragment: Mapping[str, Any]) -> str:
    """`sha256:<hex>` of the fragment's canonical JSON: what `Source.checksum` records."""
    return "sha256:" + hashlib.sha256(canonical_json(fragment).encode("utf-8")).hexdigest()


def fragment_kind(fragment: Mapping[str, Any]) -> str | None:
    present = [k for k in KINDS if fragment.get(k) is not None]
    return present[0] if len(present) == 1 else None


def _refs(node: Any) -> list[str]:
    """Ids referenced by an expression AST in JSON form (`{"kind": "ref", "id": ...}`)."""
    out: dict[str, None] = {}
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, dict):
            if n.get("kind") == "ref" and isinstance(n.get("id"), str):
                out.setdefault(n["id"], None)
            stack.extend(n.values())
        elif isinstance(n, list):
            stack.extend(n)
    return list(out)


def _questions(obj: Mapping[str, Any], kind: str) -> Iterator[dict[str, Any]]:
    if kind == "question":
        yield obj  # type: ignore[misc]
        return
    pages = [obj] if kind == "page" else obj.get("pages") or []
    for p in pages:
        for q in p.get("items") or []:
            if isinstance(q, dict):
                yield q


def _value_ids(obj: Mapping[str, Any], kind: str) -> set[str]:
    """Ids inside the object that a reference can name: questions and matrix rows."""
    ids: set[str] = set()
    for q in _questions(obj, kind):
        qid = q.get("id")
        if not isinstance(qid, str):
            continue
        if q.get("type") == "matrix":
            ids |= {f"{qid}_{r.get('id')}" for r in q.get("rows") or [] if isinstance(r, dict)}
        elif q.get("type") != "note":
            ids.add(qid)
    return ids


def _texts(obj: Any, ptr: str = "") -> Iterator[tuple[dict[str, Any], str, str]]:
    """(container, key, pointer) of every translatable text value under `obj`."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = ptr + pointer(k)
            if k in _TEXT_KEYS and isinstance(v, str):
                yield obj, k, here
            elif k in _TEXT_KEYS and isinstance(v, dict):
                for lang, s in v.items():
                    if isinstance(s, str):
                        yield v, lang, here + pointer(lang)
            elif k not in _CONDITION_KEYS:
                yield from _texts(v, here)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _texts(v, ptr + pointer(i))


def _cut_external(obj: dict[str, Any], inside: set[str], base: str) -> list[Diagnostic]:
    """Drop conditions and pipes in `obj` that name ids outside the fragment."""
    diags: list[Diagnostic] = []

    def walk(node: Any, ptr: str) -> None:
        if isinstance(node, dict):
            for key in _CONDITION_KEYS:
                if key in node and node[key] is not None:
                    outside = [r for r in _refs(node[key]) if r not in inside]
                    if outside:
                        del node[key]
                        diags.append(
                            _diag(
                                "bank.external_ref",
                                ptr + pointer(key),
                                f"{key} cut: it refers to {', '.join(outside)} outside the "
                                "saved part",
                            )
                        )
            for k, v in node.items():
                if k not in _CONDITION_KEYS:
                    walk(v, ptr + pointer(k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, ptr + pointer(i))

    walk(obj, base)
    for holder, key, ptr in list(_texts(obj, base)):
        text = holder[key]
        cut = [
            inner
            for inner in (m.group(1).strip() for m in _PIPE.finditer(text))
            if _IDENT.match(inner) and inner not in inside
        ]
        new = _PIPE.sub(lambda m, cut=cut: "" if m.group(1).strip() in cut else m.group(0), text)
        if cut:
            holder[key] = new
            diags.append(
                _diag(
                    "bank.external_ref",
                    ptr,
                    f"piped value cut: ${{{'}, ${'.join(cut)}}} is outside the saved part",
                )
            )
    return diags


# --- Fragments --------------------------------------------------------------------------


def _locate(data: Mapping[str, Any], target: str) -> tuple[str, dict[str, Any], str] | None:
    """(kind, object, pointer) of the question, page or block with id `target`."""
    for bi, b in enumerate(data.get("blocks") or []):
        if b.get("id") == target:
            return "block", b, pointer("blocks", bi)
        for pi, p in enumerate(b.get("pages") or []):
            if p.get("id") == target:
                return "page", p, pointer("blocks", bi, "pages", pi)
            for qi, q in enumerate(p.get("items") or []):
                if q.get("id") == target:
                    return "question", q, pointer("blocks", bi, "pages", pi, "items", qi)
    return None


def extract_fragment(survey: Any, target_id: str) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    """Cut the question, page or block `target_id` out of `survey` as a fragment.

    Carries every shared choice list the object uses and every computed variable that
    reads something inside it and nothing outside it (transitively: a total of subscale
    totals comes too). Conditions and pipes that refer outside are cut with a
    `bank.external_ref` warning each. Returns `(None, diagnostics)` when there is nothing
    to save. Never raises; never mutates `survey`.
    """
    try:
        model, diags = parse(survey)
        if model is None or not isinstance(survey, dict):
            return None, [
                _diag("bank.invalid_survey", "", "the survey is not a valid osp-survey document"),
                *diags,
            ]
        found = _locate(survey, target_id) if isinstance(target_id, str) else None
        if found is None:
            return None, [
                _diag(
                    "bank.target_not_found",
                    "",
                    f"no question, page or block has the id {str(target_id)[:64]!r}",
                )
            ]
        kind, obj, base = found
        obj = copy.deepcopy(obj)
        inside = _value_ids(obj, kind)

        variables: list[dict[str, Any]] = []
        chosen: set[str] = set()
        computed = [v for v in survey.get("variables") or [] if v.get("kind") == "computed"]
        changed = True
        while changed:  # fixpoint: variables reading included variables come too
            changed = False
            for v in computed:
                vid = v.get("id")
                if vid in chosen:
                    continue
                refs = set(_refs(v.get("expr")))
                if refs and refs <= inside | chosen:
                    chosen.add(vid)
                    changed = True
        variables = [copy.deepcopy(v) for v in computed if v.get("id") in chosen]

        out_diags = _cut_external(obj, inside | chosen, base)
        lists_used = {q.get("choiceList") for q in _questions(obj, kind) if q.get("choiceList")}
        choice_lists = [
            copy.deepcopy(cl)
            for cl in survey.get("choiceLists") or []
            if cl.get("id") in lists_used
        ]
        fragment: dict[str, Any] = {
            "choiceLists": choice_lists,
            "variables": variables,
            kind: obj,
        }
        problems = check_fragment(fragment)
        if any(d.severity == "error" for d in problems):
            return None, [*out_diags, *problems]
        return fragment, [*out_diags, *problems]
    except Exception as exc:  # pragma: no cover - the safety net (golden rule 3)
        return None, [_diag("bank.fragment_invalid", "", f"could not extract: {exc!r}"[:200])]


def fragment_languages(fragment: Mapping[str, Any]) -> list[str]:
    """Languages the fragment's translated texts carry, in first-seen order."""
    seen: dict[str, None] = {}
    for v in _iter_text_maps(fragment):
        for lang in v:
            seen.setdefault(lang, None)
    return list(seen)


def _iter_text_maps(obj: Any) -> Iterator[dict[str, str]]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _TEXT_KEYS and isinstance(v, dict):
                yield v
            elif k not in _CONDITION_KEYS:
                yield from _iter_text_maps(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_text_maps(v)


def _all_ids(obj: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(obj, dict):
        if isinstance(obj.get("id"), str):
            out.add(obj["id"])
        for v in obj.values():
            out |= _all_ids(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _all_ids(v)
    return out


def _fresh(base: str, taken: set[str]) -> str:
    name, n = base, 2
    while name in taken:
        name, n = f"{base}_{n}", n + 1
    taken.add(name)
    return name


def fragment_survey(fragment: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """A one-block throwaway survey holding the fragment, and the pointer of the
    fragment's object inside it (for mapping diagnostics back)."""
    kind = fragment_kind(fragment) or "block"
    obj = fragment.get(kind)
    taken = _all_ids(fragment)
    langs = fragment_languages(fragment) or ["en"]
    if kind == "block":
        block, where = obj, "/blocks/0"
    elif kind == "page":
        block, where = {"id": _fresh("osp_bank_block", taken), "pages": [obj]}, "/blocks/0/pages/0"
    else:
        page = {"id": _fresh("osp_bank_page", taken), "items": [obj]}
        block = {"id": _fresh("osp_bank_block", taken), "pages": [page]}
        where = "/blocks/0/pages/0/items/0"
    block_id = block.get("id") if isinstance(block, dict) else None
    survey = {
        "specVersion": "osp-survey/0.1",
        "id": "osp_bank_fragment",
        "metadata": {"title": "Bank fragment", "languages": langs},
        "choiceLists": list(fragment.get("choiceLists") or []),
        "variables": list(fragment.get("variables") or []),
        "blocks": [block],
        "flow": [{"type": "block", "id": _fresh("osp_bank_flow", taken), "block": block_id}],
    }
    return survey, where


def _remap(ptr: str, where: str, kind: str) -> str:
    if ptr.startswith(where):
        return "/" + kind + ptr[len(where) :]
    for top in ("/choiceLists", "/variables"):
        if ptr == top or ptr.startswith(top + "/"):
            return ptr
    return ""


def check_fragment(fragment: Any) -> list[Diagnostic]:
    """Diagnostics for a fragment: the model (`bank.fragment_invalid`), exactly one object
    (`bank.kind_mismatch`), the item limit (`bank.too_large`), then everything the survey
    validator says about a survey that holds just this fragment, with pointers relative
    to the fragment. Never raises."""
    try:
        if not isinstance(fragment, dict):
            return [_diag("bank.fragment_invalid", "", "a fragment must be a JSON object")]
        try:
            Fragment.model_validate(fragment)
        except ValidationError as exc:
            return [
                _diag(
                    "bank.fragment_invalid",
                    pointer(*e["loc"]),
                    f"{e['msg']}"[:200],
                )
                for e in exc.errors()[:20]
            ]
        kind = fragment_kind(fragment)
        if kind is None:
            return [
                _diag(
                    "bank.kind_mismatch",
                    "",
                    "a fragment holds exactly one of question, page or block",
                )
            ]
        items = sum(1 for _ in _questions(fragment[kind], kind))
        if items > MAX_ITEMS:
            return [
                _diag(
                    "bank.too_large",
                    "/" + kind,
                    f"{items} items; a fragment holds at most {MAX_ITEMS}",
                )
            ]
        survey, where = fragment_survey(fragment)
        out: list[Diagnostic] = []
        for d in validate(survey):
            if d.code in ("flow.empty", "block.unused"):
                continue  # artefacts of the throwaway survey
            out.append(d.model_copy(update={"pointer": _remap(d.pointer, where, kind)}))
        return out
    except Exception as exc:  # pragma: no cover - the safety net
        return [_diag("bank.fragment_invalid", "", f"could not check: {exc!r}"[:200])]


# --- Bank items -------------------------------------------------------------------------


def check_bank_item(data: Any) -> list[Diagnostic]:
    """Diagnostics for a whole bank item document: size, model, kind, fragment."""
    try:
        try:
            size = len(canonical_json(data).encode("utf-8"))
        except TypeError, ValueError:
            return [_diag("bank.fragment_invalid", "", "not a JSON document")]
        if size > MAX_BODY_BYTES:
            return [_diag("bank.too_large", "", f"{size} bytes; a bank item is at most 256 KB")]
        try:
            item = BankItem.model_validate(data)
        except ValidationError as exc:
            return [
                _diag("bank.fragment_invalid", pointer(*e["loc"]), f"{e['msg']}"[:200])
                for e in exc.errors()[:20]
            ]
        frag = data["fragment"]
        if fragment_kind(frag) != item.kind:
            return [
                _diag(
                    "bank.kind_mismatch",
                    "/fragment",
                    f"kind is {item.kind!r} but the fragment holds "
                    f"{fragment_kind(frag) or 'no single object'}",
                )
            ]
        return [
            d.model_copy(update={"pointer": "/fragment" + d.pointer}) for d in check_fragment(frag)
        ]
    except Exception as exc:  # pragma: no cover - the safety net
        return [_diag("bank.fragment_invalid", "", f"could not check: {exc!r}"[:200])]


# --- Provenance and metadata.instruments ------------------------------------------------

type SourceKey = tuple[str, str, int]  # (library, bank, version)
type InstrumentLookup = Callable[[Source], Mapping[str, Any] | None]


def sources(survey: Mapping[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """(object id, effective source) for every question in document order: its own
    `source`, else its page's, else its block's. Questions without one are skipped."""
    for b in survey.get("blocks") or []:
        for p in b.get("pages") or []:
            for q in p.get("items") or []:
                src = q.get("source") or p.get("source") or b.get("source")
                if isinstance(src, dict):
                    yield q.get("id"), src


def source_key(src: Mapping[str, Any]) -> SourceKey:
    return (str(src.get("library")), str(src.get("bank")), int(src.get("version") or 0))


def with_instruments(survey: Any, lookup: InstrumentLookup | None = None) -> Any:
    """The survey with `metadata.instruments` derived from its `source` fields: one entry
    per distinct (library, bank item, version), in document order. Each entry is the
    `lookup`'s description of that source (title, licence, citation), else the entry the
    survey already had for it (captured at insert), else just the reference. Entries no
    source names any more are dropped; without sources the field is removed. Returns a
    new document; anything that is not a survey object comes back unchanged."""
    if not isinstance(survey, dict) or not isinstance(survey.get("metadata"), dict):
        return survey
    existing = {
        source_key(e): e for e in survey["metadata"].get("instruments") or [] if isinstance(e, dict)
    }
    out: dict[SourceKey, dict[str, Any]] = {}
    for _qid, src in sources(survey):
        key = source_key(src)
        if key in out:
            continue
        entry: dict[str, Any] | None = None
        if lookup is not None:
            try:
                found = lookup(Source.model_validate(src))
            except ValidationError, ValueError, TypeError:
                found = None
            if found is not None:
                entry = dict(found)
        if entry is None and key in existing:
            entry = copy.deepcopy(existing[key])
        if entry is None:
            entry = {}
        entry.update({"bank": key[1], "version": key[2], "library": key[0]})
        out[key] = {
            k: entry[k]
            for k in ("bank", "version", "library", "title", "abbreviation", "licence", "citation")
            if entry.get(k) is not None
        }
    metadata = {k: v for k, v in survey["metadata"].items() if k != "instruments"}
    if out:
        metadata["instruments"] = list(out.values())
    return {**survey, "metadata": metadata}


def instrument_entry(item: BankItem | Mapping[str, Any]) -> dict[str, Any]:
    """The `metadata.instruments` description of a bank item (no bank/version/library:
    `with_instruments` adds those from the source)."""
    doc = item.model_dump(mode="json", by_alias=True) if isinstance(item, BankItem) else item
    lic = doc.get("licence") or {}
    licence = {
        k: lic[k] for k in ("class", "holder", "statement", "url", "evidenceDate") if lic.get(k)
    }
    out: dict[str, Any] = {"title": doc.get("title"), "abbreviation": doc.get("abbreviation")}
    if licence:
        out["licence"] = licence
    if doc.get("citation"):
        out["citation"] = {k: v for k, v in doc["citation"].items() if v is not None}
    return {k: v for k, v in out.items() if v is not None}


__all__ = [
    "BANK_CODES",
    "BANK_VERSION",
    "KINDS",
    "MAX_BODY_BYTES",
    "MAX_ITEMS",
    "BankItem",
    "BankLicence",
    "Citation",
    "Fragment",
    "Provenance",
    "ProvenanceFrom",
    "Scoring",
    "SourceRef",
    "canonical_json",
    "check_bank_item",
    "check_fragment",
    "extract_fragment",
    "fragment_checksum",
    "fragment_kind",
    "fragment_languages",
    "fragment_survey",
    "instrument_entry",
    "source_key",
    "sources",
    "with_instruments",
]
