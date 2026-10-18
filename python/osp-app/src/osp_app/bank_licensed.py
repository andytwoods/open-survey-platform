"""Question bank: the builder's helpers for QB5 (planning/question-bank.md §1.7, §6).

Three commands beside ``osp_app.bank``'s:

- ``bank.preview``: what "Save to bank…" would cut out of a survey draft, before it is
  saved (kind, item count, languages, the choice lists and scoring variables that travel,
  and the references outside the part that would be dropped), so the dialog can show it.
- ``bank.stubs``: the instrument stubs (``osp_instruments.stubs``): metadata, response
  format and scoring recipe for instruments the project may not bundle, with no item text.
- ``bank.compose_licensed``: the "Add a licensed instrument privately" wizard's save. An
  **owner** pastes the lab's own copy of the items (from a stub or from scratch) and
  attests that the lab holds a licence; the result is a ``licensed-to-lab`` bank item
  (``osp_instruments.compose``), private to the lab like every item of that class
  (``bank.share`` refuses it, ``bank.export`` is the owner's backup only). The store's
  ``bank.save`` audit row records the class; the attestation is in its ``statement``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from osp_instruments import (
    ComposeRequest,
    compose_fragment,
    load_stub,
    load_stubs,
    prefix_from,
    request_from_stub,
)
from osp_spec import Diagnostic
from osp_spec.bank import extract_fragment, fragment_checksum, fragment_kind, fragment_languages
from osp_store import TenantContext

from .auth.permissions import Action, Actor
from .bank import (
    LICENSED,
    BankItemView,
    _checked,
    _ctx,
    _document,
    _may,
    _meta_of,
    _require,
    _store_call,
    _stored_view,
    item_count,
)
from .builder import Builder
from .commands import command
from .errors import InvalidRequest, Rejected

MAX_ITEM_LINES = 200
MAX_LINE = 2000
MAX_LABELS = 21


@dataclass(frozen=True)
class BankPreview:
    kind: str
    item_count: int
    languages: list[str]
    choice_lists: list[str]  # ids of the shared lists that travel
    variables: list[str]  # ids of the computed variables that travel
    diagnostics: list[Diagnostic]  # what would be cut (warnings)


def _diag(code: str, message: str, pointer: str = "") -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, pointer=pointer)


@command("bank.preview", label="Preview a save to the bank", action=Action.BANK_VIEW)
def preview(builder: Builder, actor: Actor, *, survey_id: str, target_id: str) -> BankPreview:
    """What saving ``target_id`` of the draft would keep and cut. Reads the survey; a part
    that can't be cut out is ``Rejected`` with the extraction's diagnostics."""
    ctx = builder._locate(actor, survey_id, Action.SURVEY_READ)  # noqa: SLF001 - same package
    _require(actor, Action.BANK_VIEW, ctx)
    draft = builder._draft(ctx, survey_id)  # noqa: SLF001
    if not isinstance(target_id, str):
        raise InvalidRequest("targetId must be a string")
    fragment, diags = extract_fragment(draft.body, target_id)
    if fragment is None:
        raise Rejected("That part can't be cut out of the survey.", diags)
    return BankPreview(
        kind=fragment_kind(fragment) or "block",
        item_count=item_count(fragment),
        languages=fragment_languages(fragment),
        choice_lists=[str(cl.get("id")) for cl in fragment.get("choiceLists") or []],
        variables=[str(v.get("id")) for v in fragment.get("variables") or []],
        diagnostics=[d for d in diags if d.severity != "error"],
    )


@command("bank.stubs", label="Instrument stubs", action=Action.BANK_VIEW)
def stubs(builder: Builder, actor: Actor) -> list[dict[str, Any]]:
    """Every stub (read-only, the same for every lab), as JSON documents."""
    if not any(_may(actor, Action.BANK_VIEW, TenantContext(t, actor.user_id)) for t in actor.roles):
        from .errors import Forbidden

        raise Forbidden("Not permitted.")
    return [s.model_dump(mode="json") for s in load_stubs()]


def _str_list(value: object, what: str, max_len: int, max_line: int) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise InvalidRequest(f"{what} must be a list of strings")
    out: list[str] = []
    for v in value:
        if not isinstance(v, str) or len(v) > max_line:
            raise InvalidRequest(f"{what} must be a list of strings of at most {max_line} chars")
        out.append(v)
    if len(out) > max_len:
        raise InvalidRequest(f"{what} holds at most {max_len} entries")
    return out


@command("bank.compose_licensed", label="Add a licensed instrument", action=Action.BANK_SHARE)
def compose_licensed(
    builder: Builder,
    actor: Actor,
    *,
    items: Sequence[str],
    attest: bool,
    stub_id: str | None = None,
    title: str | None = None,
    abbreviation: str | None = None,
    prefix: str | None = None,
    layout: str = "matrix",
    stem: str | None = None,
    labels: Sequence[str] | None = None,
    scale: Mapping[str, Any] | None = None,
    scoring: Mapping[str, Any] | None = None,
    description: str | None = None,
    tags: Sequence[str] | None = None,
    language: str | None = None,
    tenant_id: str | None = None,
) -> BankItemView:
    """A private ``licensed-to-lab`` bank item from the lab's own copy of an instrument.

    With ``stub_id`` the stub supplies the title, abbreviation, response format, scoring
    recipe, citation, holder and tags (``title`` / ``abbreviation`` override the names);
    the item count must match the stub's. Without one, ``scale`` (``{min, max}``) is
    needed and ``scoring`` (``{aggregate, reversed, subscales, total, offset, factor}``)
    is optional. ``items`` are the pasted lines (``text`` or ``text | option | …``);
    ``labels`` name the shared scale's points. Owner only, and only with ``attest`` true.
    """
    ctx = _ctx(actor, tenant_id, Action.BANK_SHARE)
    if attest is not True:
        raise Rejected(
            "Tick the attestation: your lab holds a licence for this instrument and it "
            "stays private to this lab.",
            [_diag("bank.licensed_attestation", "attestation required", "/attest")],
        )
    lines = _str_list(items, "items", MAX_ITEM_LINES, MAX_LINE)
    label_list = None if labels is None else _str_list(labels, "labels", MAX_LABELS, 200)
    if layout not in ("matrix", "single"):
        raise InvalidRequest("layout must be matrix or single")
    for name, value in (("title", title), ("abbreviation", abbreviation), ("prefix", prefix)):
        if value is not None and (not isinstance(value, str) or len(value) > 200):
            raise InvalidRequest(f"{name} must be a string of at most 200 characters")
    if stem is not None and (not isinstance(stem, str) or len(stem) > MAX_LINE):
        raise InvalidRequest("stem must be a string")
    if language is not None and (not isinstance(language, str) or not 2 <= len(language) <= 12):
        raise InvalidRequest("language must be a language tag")

    stub = None
    if stub_id is not None:
        stub = load_stub(stub_id) if isinstance(stub_id, str) and len(stub_id) <= 64 else None
        if stub is None:
            raise InvalidRequest("Unknown instrument stub.")
        n = len([x for x in lines if x.strip()])
        if n != stub.itemCount:
            raise Rejected(
                f"{stub.abbreviation} has {stub.itemCount} items; {n} lines were given.",
                [
                    _diag(
                        "bank.stub_items",
                        f"{stub.itemCount} items expected, {n} given",
                        "/items",
                    )
                ],
            )
        req = request_from_stub(
            stub,
            lines,
            layout=layout,  # type: ignore[arg-type]
            stem=stem,
            labels=label_list,
            prefix=prefix,
            title=title or stub.title,
            language=language,
        )
        abbreviation = abbreviation or stub.abbreviation
        title = title or stub.title
    else:
        if not isinstance(title, str) or not title.strip():
            raise InvalidRequest("title is required without a stub")
        if not isinstance(scale, Mapping):
            raise InvalidRequest("scale {min, max} is required without a stub")
        sc = scoring if isinstance(scoring, Mapping) else {}
        req = ComposeRequest(
            prefix=prefix or prefix_from(abbreviation or title),
            title=title,
            items=lines,
            layout=layout,  # type: ignore[arg-type]
            stem=stem,
            scale_min=scale.get("min"),  # type: ignore[arg-type]
            scale_max=scale.get("max"),  # type: ignore[arg-type]
            labels=label_list,
            reversed=list(sc.get("reversed") or []),
            subscales={str(k): list(v) for k, v in (sc.get("subscales") or {}).items()},
            aggregate=sc.get("aggregate", "sum"),
            total=bool(sc.get("total", True)),
            offset=sc.get("offset", 0),
            factor=sc.get("factor"),
            language=language,
        )
    fragment, diags = compose_fragment(req)
    if fragment is None:
        raise Rejected("The instrument could not be built from those lines.", diags)

    when = builder.store._now().date().isoformat()  # noqa: SLF001 - the store clock
    licence: dict[str, Any] = {
        "class": LICENSED,
        "statement": (
            f"Our lab holds a licence for this instrument; attested by {actor.user_id} on "
            f"{when}. Private to this lab: not shared at host level, exported only as the "
            "lab's own backup."
        ),
    }
    citation = None
    scoring_text = None
    stub_tags: list[str] = []
    if stub is not None:
        licence["holder"] = stub.holder.name
        if stub.holder.url:
            licence["url"] = stub.holder.url
        citation = {
            "text": stub.citation.text,
            **({"doi": stub.citation.doi} if stub.citation.doi else {}),
        }
        scoring_text = stub.scoring.text
        stub_tags = list(stub.tags)
        description = description or stub.description
    tag_list = list(dict.fromkeys([*(tags or []), *stub_tags, "licensed"]))[:20]
    doc = _checked(
        _document(
            kind="block",
            fragment=fragment,
            title=title,
            abbreviation=abbreviation,
            description=description,
            tags=tag_list,
            licence=licence,
            citation=citation,
            scoring={"text": scoring_text} if scoring_text else None,
        ),
        "That is not a valid bank item.",
    )
    item, version = _store_call(
        builder.store.create_bank_item, ctx, _meta_of(doc), doc, fragment_checksum(fragment)
    )
    return _stored_view(actor, ctx, item, version)


__all__ = ["BankPreview", "compose_licensed", "preview", "stubs"]
