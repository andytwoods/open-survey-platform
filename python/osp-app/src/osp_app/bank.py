"""Question bank commands (planning/question-bank.md §3; task QB4).

A lab (tenant) keeps bank items: a question, page or block cut out of a survey
(``osp_spec.bank.extract_fragment``) with its metadata, versioned. Three sources show up in
one list: the lab's own items (``lab``), other labs' items shared on this host (``host``,
read-only, and only while the host's ``OSP_BANK_HOST_SHARING`` switch is on: lead decision
2) and the bundled instrument library (``bundled``, ``osp_instruments``, read-only).

Permissions: ``bank.view`` (every member: browse, search, read) ; ``bank.manage`` (owner,
editor: save, new version, metadata, delete, import, export, copy); ``bank.share`` (owner:
host visibility, relicensing at share time, a ``licensed-to-lab`` item). Saving from a
survey also needs to read that survey. Inserting into a survey is a survey op (QB3) and
needs the survey's edit permission like any op.

Licence rules (lead decisions 3 and 4): a lab's own words default to ``unknown``;
``unknown`` and ``licensed-to-lab`` items are never host-visible, and an owner may relicense
an item as they share it ("these are our own words, CC BY 4.0"). A ``licensed-to-lab`` item
leaves the lab only in its own backup file, exported by an owner, and is imported only by
an owner who attests the lab holds the licence.

The store keeps documents opaque; everything is validated here with ``osp_spec.bank``
(a bad document is ``Rejected`` with diagnostics, never saved). Registered on import
(``osp_app/__init__.py``); dispatched through ``Builder.run``.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from osp_instruments import load_document, load_library
from osp_spec import Diagnostic
from osp_spec.bank import (
    BANK_VERSION,
    KINDS,
    check_bank_item,
    extract_fragment,
    fragment_checksum,
    fragment_kind,
    fragment_languages,
)
from osp_store import (
    BankItemMeta,
    BankQuery,
    Conflict,
    InvalidInput,
    NotFound,
    StoredBankItem,
    StoredBankVersion,
    TenantContext,
)

from .auth.permissions import Action, Actor, Resource, can
from .builder import Builder
from .commands import command
from .errors import ConflictError, Forbidden, InvalidRequest, NotFoundError, Rejected

BANK_FILE_VERSION = "osp-bank-file/0.1"
SOURCES = ("lab", "host", "bundled")
DEFAULT_LICENCE_CLASS = "unknown"  # a lab's own words (lead decision 3)
#: Licence classes that never leave the lab at host level (question-bank.md §2.1).
NOT_SHAREABLE = frozenset({"licensed-to-lab", "unknown"})
LICENSED = "licensed-to-lab"
META_FIELDS = ("title", "abbreviation", "description", "tags")
MAX_PAGE_SIZE = 200
MAX_IMPORT_ITEMS = 200
PLACEHOLDER_ID = "pending"  # the store assigns the real id
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)  # the "created at" of a bundled version


# -- views -------------------------------------------------------------------------------


@dataclass(frozen=True)
class BankSummary:
    id: str
    source: str  # lab | host | bundled
    kind: str
    title: str
    abbreviation: str | None
    description: str | None
    tags: list[str]
    languages: list[str]
    licence_class: str
    version: int  # the current version
    item_count: int
    visibility: str | None  # lab | host; None for bundled
    lab_id: str | None  # the owning lab; None for bundled
    can_edit: bool
    created_by: str | None = None
    created_at: datetime | None = None
    updated_by: str | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None


@dataclass(frozen=True)
class BankListView:
    tenant_id: str
    items: list[BankSummary]
    total: int
    page: int
    page_size: int
    can_manage: bool
    can_share: bool
    host_sharing: bool


@dataclass(frozen=True)
class BankItemView:
    summary: BankSummary
    document: dict[str, Any]  # the requested version's osp-bank-item/0.1 document
    version: int
    checksum: str | None  # of the fragment (None for bundled)


@dataclass(frozen=True)
class BankVersionInfo:
    version: int
    title: str
    checksum: str
    created_by: str
    created_at: datetime


@dataclass(frozen=True)
class BankSaveResult:
    item: BankItemView
    diagnostics: list[Diagnostic]  # warnings from the extraction (references cut)


@dataclass(frozen=True)
class BankImportResult:
    items: list[BankSummary]
    diagnostics: list[Diagnostic]


# -- helpers -----------------------------------------------------------------------------


def _ctx(actor: Actor, tenant_id: object, action: Action) -> TenantContext:
    """The lab to act in: ``tenant_id``, or the actor's only lab with this permission."""
    if tenant_id is not None:
        if not isinstance(tenant_id, str) or not can(actor, action, Resource.tenant(tenant_id)):
            # A lab the actor can't see is "not permitted" whether or not it exists.
            raise Forbidden("Not permitted.")
        return TenantContext(tenant_id, actor.user_id)
    labs = sorted(t for t in actor.roles if can(actor, action, Resource.tenant(t)))
    if len(labs) != 1:
        raise Forbidden("Not permitted.") if not labs else InvalidRequest("tenantId is required")
    return TenantContext(labs[0], actor.user_id)


def _may(actor: Actor, action: Action, ctx: TenantContext) -> bool:
    return can(actor, action, Resource.tenant(ctx.tenant_id))


def _require(actor: Actor, action: Action, ctx: TenantContext) -> None:
    if not _may(actor, action, ctx):
        raise Forbidden("Not permitted.")


def _store_call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except NotFound as exc:
        raise NotFoundError("Bank item not found.") from exc
    except Conflict as exc:
        raise ConflictError("That bank item was deleted.") from exc
    except InvalidInput as exc:
        raise InvalidRequest(str(exc)) from exc


def _diag(code: str, message: str, pointer: str = "") -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, pointer=pointer)


def _questions(fragment: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    kind = fragment_kind(fragment)
    obj = fragment.get(kind) if kind else None
    if not isinstance(obj, Mapping):
        return
    if kind == "question":
        yield obj
        return
    pages = [obj] if kind == "page" else obj.get("pages") or []
    for p in pages:
        for q in p.get("items") or [] if isinstance(p, Mapping) else []:
            if isinstance(q, Mapping):
                yield q


def item_count(fragment: Mapping[str, Any]) -> int:
    """How many items the fragment holds: a matrix counts its rows (each is a variable),
    every other question or note counts one (QB5: the audit tables count that way)."""
    n = 0
    for q in _questions(fragment):
        rows = q.get("rows") if q.get("type") == "matrix" else None
        n += len(rows) if isinstance(rows, list) and rows else 1
    return n


def _texts(node: Any) -> Iterator[str]:
    """Every label/title text in a fragment (all languages), for the search bag."""
    if isinstance(node, Mapping):
        for k, v in node.items():
            if k in ("label", "title"):
                if isinstance(v, str):
                    yield v
                elif isinstance(v, Mapping):
                    yield from (s for s in v.values() if isinstance(s, str))
            elif k not in ("showIf", "constraint", "expr"):
                yield from _texts(v)
    elif isinstance(node, list):
        for v in node:
            yield from _texts(v)


def search_text(document: Mapping[str, Any]) -> str:
    """The lower-cased bag of words the bank search runs over: title, abbreviation,
    description, tags and every item label."""
    parts = [
        str(document.get("title") or ""),
        str(document.get("abbreviation") or ""),
        str(document.get("description") or ""),
        *(str(tag) for tag in document.get("tags") or []),
        *_texts(document.get("fragment") or {}),
    ]
    return " ".join(" ".join(p.split()) for p in parts if p).lower()


def _matches(text: str, q: str | None) -> bool:
    return all(term in text for term in (q or "").lower().split())


def _meta_of(document: Mapping[str, Any]) -> BankItemMeta:
    return BankItemMeta(
        title=document["title"],
        kind=document["kind"],
        licence_class=document["licence"]["class"],
        search_text=search_text(document),
        abbreviation=document.get("abbreviation"),
        tags=list(document.get("tags") or []),
        languages=list(document.get("languages") or []),
    )


def _checked(document: Mapping[str, Any], message: str, base: str = "") -> dict[str, Any]:
    """The document, or ``Rejected`` with the spec's diagnostics (pointers under ``base``)."""
    diags = check_bank_item(document)
    errors = [d for d in diags if d.severity == "error"]
    if errors:
        if base:
            errors = [d.model_copy(update={"pointer": base + d.pointer}) for d in errors]
        raise Rejected(message, errors)
    return copy.deepcopy(dict(document))


def _document(
    *,
    kind: str,
    fragment: Mapping[str, Any],
    title: object,
    abbreviation: object = None,
    description: object = None,
    tags: object = (),
    licence: object = None,
    citation: object = None,
    scoring: object = None,
    provenance: object = None,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "bankVersion": BANK_VERSION,
        "id": PLACEHOLDER_ID,
        "version": 1,
        "kind": kind,
        "title": title,
        "abbreviation": abbreviation,
        "description": description,
        "tags": list(tags) if isinstance(tags, Sequence) and not isinstance(tags, str) else tags,
        "languages": fragment_languages(fragment),
        "licence": {"class": DEFAULT_LICENCE_CLASS} if licence is None else licence,
        "citation": citation,
        "source": None,
        "scoring": scoring,
        "provenance": provenance,
        "fragment": fragment,
    }
    return {k: v for k, v in doc.items() if v is not None}


def _licence_class(document: Mapping[str, Any]) -> str:
    lic = document.get("licence")
    return str(lic.get("class")) if isinstance(lic, Mapping) else DEFAULT_LICENCE_CLASS


# -- summaries ---------------------------------------------------------------------------


def _stored_summary(
    actor: Actor, ctx: TenantContext, item: StoredBankItem, document: Mapping[str, Any]
) -> BankSummary:
    own = item.tenant_id == ctx.tenant_id
    return BankSummary(
        id=item.id,
        source="lab" if own else "host",
        kind=item.kind,
        title=item.title,
        abbreviation=item.abbreviation,
        description=document.get("description"),
        tags=list(item.tags),
        languages=list(item.languages),
        licence_class=item.licence_class,
        version=item.current_version,
        item_count=item_count(document.get("fragment") or {}),
        visibility=item.visibility,
        lab_id=item.tenant_id,
        can_edit=own and item.deleted_at is None and _may(actor, Action.BANK_MANAGE, ctx),
        created_by=item.created_by,
        created_at=item.created_at,
        updated_by=item.updated_by,
        updated_at=item.updated_at,
        deleted_at=item.deleted_at,
    )


def _bundled_summary(document: Mapping[str, Any]) -> BankSummary:
    return BankSummary(
        id=str(document["id"]),
        source="bundled",
        kind=str(document["kind"]),
        title=str(document["title"]),
        abbreviation=document.get("abbreviation"),
        description=document.get("description"),
        tags=list(document.get("tags") or []),
        languages=list(document.get("languages") or []),
        licence_class=_licence_class(document),
        version=int(document["version"]),
        item_count=item_count(document.get("fragment") or {}),
        visibility=None,
        lab_id=None,
        can_edit=False,
    )


def _bundled_documents() -> list[dict[str, Any]]:
    return [
        item.model_dump(mode="json", by_alias=True, exclude_none=True) for item in load_library()
    ]


def _bundled_document(item_id: object) -> dict[str, Any] | None:
    if not isinstance(item_id, str) or not 0 < len(item_id) <= 64:
        return None
    return load_document(item_id)


# -- locating ----------------------------------------------------------------------------


@dataclass(frozen=True)
class _Located:
    source: str
    document: dict[str, Any]
    version: int
    checksum: str | None
    item: StoredBankItem | None = None  # None: bundled


def _host_on(builder: Builder) -> bool:
    return bool(getattr(builder, "bank_host_sharing", True))


def _locate(
    builder: Builder, ctx: TenantContext, item_id: object, version: int | None = None
) -> _Located:
    """A stored item the lab may read (own or host-shared), else a bundled one."""
    include_host = _host_on(builder)
    if version is not None and (type(version) is not int or version < 1):
        raise NotFoundError("Bank item version not found.")
    try:
        item = builder.store.get_bank_item(ctx, item_id, include_host=include_host)
        stored = builder.store.get_bank_version(ctx, item.id, version, include_host=include_host)
    except NotFound:
        doc = _bundled_document(item_id)
        if doc is None or (version is not None and version != doc.get("version")):
            raise NotFoundError("Bank item not found.") from None
        return _Located("bundled", doc, int(doc["version"]), None)
    return _Located(
        "lab" if item.tenant_id == ctx.tenant_id else "host",
        dict(stored.body),
        stored.version,
        stored.checksum,
        item,
    )


def _view(actor: Actor, ctx: TenantContext, found: _Located) -> BankItemView:
    if found.item is None:
        summary = _bundled_summary(found.document)
    else:
        summary = _stored_summary(actor, ctx, found.item, found.document)
    return BankItemView(summary, found.document, found.version, found.checksum)


def _stored_view(
    actor: Actor, ctx: TenantContext, item: StoredBankItem, version: StoredBankVersion
) -> BankItemView:
    return BankItemView(
        _stored_summary(actor, ctx, item, version.body),
        dict(version.body),
        version.version,
        version.checksum,
    )


def _own_item(builder: Builder, ctx: TenantContext, item_id: object) -> StoredBankItem:
    """The lab's own, live item (for a write); anything else is not found / conflict."""
    item = _store_call(builder.store.get_bank_item, ctx, item_id, include_host=False)
    if item.deleted_at is not None:
        raise ConflictError("That bank item was deleted.")
    return item


# -- commands ----------------------------------------------------------------------------


@command("bank.list", label="Search the question bank", action=Action.BANK_VIEW)
def list_items(
    builder: Builder,
    actor: Actor,
    *,
    q: str | None = None,
    kind: str | None = None,
    source: str | None = None,
    language: str | None = None,
    licence: str | None = None,
    tags: Sequence[str] = (),
    page: int = 1,
    page_size: int = 50,
    tenant_id: str | None = None,
) -> BankListView:
    """One list over the lab's items, host-shared items and the bundled library, filtered
    and paged; ``source`` restricts it to one of the three."""
    ctx = _ctx(actor, tenant_id, Action.BANK_VIEW)
    if source is not None and source not in SOURCES:
        raise InvalidRequest(f"source must be one of {', '.join(SOURCES)}")
    if kind is not None and kind not in KINDS:
        raise InvalidRequest(f"kind must be one of {', '.join(KINDS)}")
    if type(page) is not int or page < 1:
        raise InvalidRequest("page must be a positive integer")
    if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise InvalidRequest(f"pageSize must be 1-{MAX_PAGE_SIZE}")
    if q is not None and (not isinstance(q, str) or len(q) > 200):
        raise InvalidRequest("q must be a string of at most 200 characters")
    host_on = _host_on(builder)
    found: list[BankSummary] = []
    if source != "bundled":
        query = BankQuery(
            q=q,
            kind=kind,
            source=None if source is None else source,
            licence_class=licence,
            language=language,
            tags=tuple(tags),
        )
        items = _store_call(builder.store.list_bank_items, ctx, query, include_host=host_on)
        for item in items:
            version = builder.store.get_bank_version(ctx, item.id, include_host=host_on)
            found.append(_stored_summary(actor, ctx, item, version.body))
    if source in (None, "bundled"):
        for doc in _bundled_documents():
            if kind is not None and doc["kind"] != kind:
                continue
            if licence is not None and _licence_class(doc) != licence:
                continue
            if language is not None and language not in (doc.get("languages") or []):
                continue
            if tags and not set(tags) <= set(doc.get("tags") or []):
                continue
            if not _matches(search_text(doc), q):
                continue
            found.append(_bundled_summary(doc))
    found.sort(key=lambda s: (s.title.lower(), s.source, s.id))
    start = (page - 1) * page_size
    return BankListView(
        ctx.tenant_id,
        found[start : start + page_size],
        len(found),
        page,
        page_size,
        _may(actor, Action.BANK_MANAGE, ctx),
        _may(actor, Action.BANK_SHARE, ctx),
        host_on,
    )


@command("bank.library", label="The bundled instrument library", action=Action.BANK_VIEW)
def library(builder: Builder, actor: Actor) -> list[BankSummary]:
    """Every bundled instrument (read-only, the same for every lab)."""
    if not any(_may(actor, Action.BANK_VIEW, TenantContext(t, actor.user_id)) for t in actor.roles):
        raise Forbidden("Not permitted.")
    return [_bundled_summary(doc) for doc in _bundled_documents()]


@command("bank.get", label="Get a bank item", action=Action.BANK_VIEW)
def get_item(
    builder: Builder,
    actor: Actor,
    *,
    item_id: str,
    version: int | None = None,
    tenant_id: str | None = None,
) -> BankItemView:
    """One version of an item (``None``: the current one) with its document."""
    ctx = _ctx(actor, tenant_id, Action.BANK_VIEW)
    return _view(actor, ctx, _locate(builder, ctx, item_id, version))


@command("bank.versions", label="A bank item's versions", action=Action.BANK_VIEW)
def list_versions(
    builder: Builder, actor: Actor, *, item_id: str, tenant_id: str | None = None
) -> list[BankVersionInfo]:
    ctx = _ctx(actor, tenant_id, Action.BANK_VIEW)
    found = _locate(builder, ctx, item_id)
    if found.item is None:  # bundled: one version, dated by its licence evidence
        doc = found.document
        checksum = fragment_checksum(doc["fragment"])
        return [BankVersionInfo(found.version, str(doc["title"]), checksum, "bundled", _EPOCH)]
    versions = _store_call(
        builder.store.list_bank_versions, ctx, found.item.id, include_host=_host_on(builder)
    )
    return [
        BankVersionInfo(
            v.version, str(v.body.get("title") or ""), v.checksum, v.created_by, v.created_at
        )
        for v in versions
    ]


def _extract(builder: Builder, ctx: TenantContext, survey_id: object, target_id: object):
    draft = builder._draft(ctx, survey_id)  # noqa: SLF001 - same package
    if not isinstance(target_id, str):
        raise InvalidRequest("targetId must be a string")
    fragment, diags = extract_fragment(draft.body, target_id)
    if fragment is None:
        raise Rejected("Nothing to save: that part can't be cut out of the survey.", diags)
    return fragment, [d for d in diags if d.severity != "error"]


def _save_ctx(builder: Builder, actor: Actor, survey_id: object) -> TenantContext:
    """The survey's lab, where the item is saved: read the survey, manage the bank."""
    ctx = builder._locate(actor, survey_id, Action.SURVEY_READ)  # noqa: SLF001
    _require(actor, Action.BANK_MANAGE, ctx)
    return ctx


def _licence_ok(actor: Actor, ctx: TenantContext, document: Mapping[str, Any]) -> None:
    """Only an owner adds a ``licensed-to-lab`` item (question-bank.md §1.7)."""
    if _licence_class(document) == LICENSED and not _may(actor, Action.BANK_SHARE, ctx):
        raise Forbidden("Not permitted.")


@command("bank.save", label="Save to the question bank", action=Action.BANK_MANAGE)
def save_item(
    builder: Builder,
    actor: Actor,
    *,
    survey_id: str,
    target_id: str,
    title: str,
    abbreviation: str | None = None,
    description: str | None = None,
    tags: Sequence[str] = (),
    licence: Mapping[str, Any] | None = None,
    citation: Mapping[str, Any] | None = None,
    scoring: Mapping[str, Any] | None = None,
) -> BankSaveResult:
    """A new item (version 1) from a question, page or block of a survey draft. The
    fragment is validated; references outside it are cut and reported as warnings. The
    licence defaults to ``unknown``."""
    ctx = _save_ctx(builder, actor, survey_id)
    fragment, warnings = _extract(builder, ctx, survey_id, target_id)
    doc = _checked(
        _document(
            kind=fragment_kind(fragment) or "block",
            fragment=fragment,
            title=title,
            abbreviation=abbreviation,
            description=description,
            tags=tags,
            licence=licence,
            citation=citation,
            scoring=scoring,
        ),
        "That is not a valid bank item.",
    )
    _licence_ok(actor, ctx, doc)
    item, version = _store_call(
        builder.store.create_bank_item, ctx, _meta_of(doc), doc, fragment_checksum(fragment)
    )
    return BankSaveResult(_stored_view(actor, ctx, item, version), warnings)


@command("bank.new_version", label="New version of a bank item", action=Action.BANK_MANAGE)
def new_version(
    builder: Builder,
    actor: Actor,
    *,
    item_id: str,
    survey_id: str,
    target_id: str,
    title: str | None = None,
    abbreviation: str | None = None,
    description: str | None = None,
    tags: Sequence[str] | None = None,
    licence: Mapping[str, Any] | None = None,
    citation: Mapping[str, Any] | None = None,
    scoring: Mapping[str, Any] | None = None,
) -> BankSaveResult:
    """Version *n+1* of the lab's own item from a survey target; metadata not given is
    kept from the current version. The item must be in the survey's lab."""
    ctx = _save_ctx(builder, actor, survey_id)
    item = _own_item(builder, ctx, item_id)
    current = builder.store.get_bank_version(ctx, item.id, include_host=False).body
    fragment, warnings = _extract(builder, ctx, survey_id, target_id)
    kind = fragment_kind(fragment)
    if kind != item.kind:
        raise Rejected(
            f"That is a {kind}; the bank item is a {item.kind}.",
            [_diag("bank.kind_mismatch", f"a {item.kind} item can't become a {kind}", "/kind")],
        )

    def pick(key: str, given: Any) -> Any:
        return current.get(key) if given is None else given

    doc = _checked(
        _document(
            kind=item.kind,
            fragment=fragment,
            title=pick("title", title),
            abbreviation=pick("abbreviation", abbreviation),
            description=pick("description", description),
            tags=pick("tags", tags) or [],
            licence=pick("licence", licence),
            citation=pick("citation", citation),
            scoring=pick("scoring", scoring),
            provenance=current.get("provenance"),
        ),
        "That is not a valid bank item.",
    )
    _licence_ok(actor, ctx, doc)
    saved, version = _store_call(
        builder.store.add_bank_version,
        ctx,
        item.id,
        _meta_of(doc),
        doc,
        fragment_checksum(fragment),
    )
    return BankSaveResult(_stored_view(actor, ctx, saved, version), warnings)


@command("bank.update", label="Edit bank item metadata", action=Action.BANK_MANAGE)
def update_item(
    builder: Builder,
    actor: Actor,
    *,
    item_id: str,
    fields: Mapping[str, Any],
    tenant_id: str | None = None,
) -> BankItemView:
    """Title, abbreviation, description and tags of the lab's own item, without a new
    version (the fragment is version-bound)."""
    ctx = _ctx(actor, tenant_id, Action.BANK_MANAGE)
    if not isinstance(fields, Mapping) or not set(fields) <= set(META_FIELDS):
        raise InvalidRequest(f"fields must be a subset of {', '.join(META_FIELDS)}")
    item = _own_item(builder, ctx, item_id)
    current = builder.store.get_bank_version(ctx, item.id, include_host=False).body
    merged = {**current, **fields}
    merged = {k: v for k, v in merged.items() if not (k in fields and v is None)}
    doc = _checked(merged, "That is not a valid bank item.")
    saved, version = _store_call(
        builder.store.update_bank_item, ctx, item.id, _meta_of(doc), dict(fields)
    )
    return _stored_view(actor, ctx, saved, version)


@command("bank.share", label="Share a bank item with the host", action=Action.BANK_SHARE)
def share_item(
    builder: Builder,
    actor: Actor,
    *,
    item_id: str,
    visibility: str,
    licence_class: str | None = None,
    tenant_id: str | None = None,
) -> BankItemView:
    """``host`` makes the lab's own item readable by every lab on this host (read-only
    for them), ``lab`` takes it back. ``unknown`` and ``licensed-to-lab`` items can't be
    shared; an owner may relicense an item as they share it (``licence_class``, e.g.
    ``cc-by-4.0`` for the lab's own words). Refused when the host switched sharing off."""
    ctx = _ctx(actor, tenant_id, Action.BANK_SHARE)
    if visibility not in ("lab", "host"):
        raise InvalidRequest("visibility must be lab or host")
    item = _own_item(builder, ctx, item_id)
    version = builder.store.get_bank_version(ctx, item.id, include_host=False)
    if licence_class is not None:
        if licence_class == LICENSED:
            raise Rejected(
                "A licensed instrument stays private to the lab.",
                [_diag("bank.not_shareable", "licensed-to-lab can't be shared", "/licence/class")],
            )
        licence = {**(version.body.get("licence") or {}), "class": licence_class}
        doc = _checked({**version.body, "licence": licence}, "That is not a valid licence.")
        item, version = _store_call(
            builder.store.update_bank_item, ctx, item.id, _meta_of(doc), {"licence": licence}
        )
    if visibility == "host":
        if not _host_on(builder):
            raise InvalidRequest("Host sharing is switched off on this host.")
        if item.licence_class in NOT_SHAREABLE:
            raise Rejected(
                "Say what licence the item is under before sharing it.",
                [
                    _diag(
                        "bank.not_shareable",
                        f"an item with licence class {item.licence_class!r} can't be shared "
                        "at host level",
                        "/licence/class",
                    )
                ],
            )
    item = _store_call(builder.store.set_bank_visibility, ctx, item.id, visibility)
    return _stored_view(actor, ctx, item, version)


@command("bank.delete", label="Delete a bank item", action=Action.BANK_MANAGE)
def delete_item(
    builder: Builder, actor: Actor, *, item_id: str, tenant_id: str | None = None
) -> None:
    """Soft delete: surveys that inserted it keep their provenance; the item leaves every
    list. Deleting again is a conflict."""
    ctx = _ctx(actor, tenant_id, Action.BANK_MANAGE)
    _own_item(builder, ctx, item_id)
    _store_call(builder.store.delete_bank_item, ctx, item_id)


def _file(documents: Sequence[Mapping[str, Any]], exported_at: datetime) -> dict[str, Any]:
    private = any(_licence_class(d) == LICENSED for d in documents)
    return {
        "bankFile": BANK_FILE_VERSION,
        "exportedAt": exported_at.isoformat(),
        "private": private,
        "items": [copy.deepcopy(dict(d)) for d in documents],
    }


@command("bank.export", label="Export a bank item file", action=Action.BANK_MANAGE)
def export_item(
    builder: Builder,
    actor: Actor,
    *,
    item_id: str,
    version: int | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """The portable ``*.osp-bank.json`` file holding one version of an item the lab may
    read. A ``licensed-to-lab`` item is exported only by an owner (the lab's own backup)."""
    ctx = _ctx(actor, tenant_id, Action.BANK_MANAGE)
    found = _locate(builder, ctx, item_id, version)
    if _licence_class(found.document) == LICENSED:
        _require(actor, Action.BANK_SHARE, ctx)
    return _file([found.document], builder.store._now())  # noqa: SLF001 - the store clock


def _file_items(file: object) -> list[dict[str, Any]]:
    if not isinstance(file, Mapping) or file.get("bankFile") != BANK_FILE_VERSION:
        raise Rejected(
            "That is not a bank file.",
            [_diag("bank.file", f"a bank file has bankFile {BANK_FILE_VERSION!r}", "/bankFile")],
        )
    items = file.get("items")
    if not isinstance(items, list) or not items:
        raise Rejected("The file holds no items.", [_diag("bank.file", "items is empty", "/items")])
    if len(items) > MAX_IMPORT_ITEMS:
        raise Rejected(
            f"A file holds at most {MAX_IMPORT_ITEMS} items.",
            [_diag("bank.too_large", f"{len(items)} items", "/items")],
        )
    return [item if isinstance(item, dict) else {"_": item} for item in items]


@command("bank.import", label="Import a bank item file", action=Action.BANK_MANAGE)
def import_file(
    builder: Builder,
    actor: Actor,
    *,
    file: Mapping[str, Any],
    attest_licensed: bool = False,
    tenant_id: str | None = None,
) -> BankImportResult:
    """Every item of a bank file becomes a new lab item at version 1, licence class kept,
    ``provenance.from`` pointing at the file's id and version. All or nothing: one bad item
    rejects the file with diagnostics under ``/items/<i>``. A ``licensed-to-lab`` item is
    taken only from an owner who attests the lab holds the licence."""
    ctx = _ctx(actor, tenant_id, Action.BANK_MANAGE)
    docs: list[dict[str, Any]] = []
    for i, raw in enumerate(_file_items(file)):
        base = f"/items/{i}"
        doc = _checked(raw, f"Item {i + 1} of the file is not a valid bank item.", base)
        if _licence_class(doc) == LICENSED and not (
            attest_licensed is True and _may(actor, Action.BANK_SHARE, ctx)
        ):
            raise Rejected(
                "A licensed instrument is imported only by an owner who attests the lab "
                "holds the licence.",
                [_diag("bank.licensed_attestation", "attestation required", base + "/licence")],
            )
        doc["provenance"] = {
            "from": {"library": "file", "id": doc["id"], "version": doc["version"]}
        }
        doc.pop("source", None)
        docs.append(doc)
    out: list[BankSummary] = []
    for doc in docs:
        item, version = _store_call(
            builder.store.create_bank_item,
            ctx,
            _meta_of(doc),
            doc,
            fragment_checksum(doc["fragment"]),
            imported=True,
        )
        out.append(_stored_summary(actor, ctx, item, version.body))
    return BankImportResult(out, [])


@command("bank.copy", label="Copy a bank item into the lab", action=Action.BANK_MANAGE)
def copy_item(
    builder: Builder,
    actor: Actor,
    *,
    item_id: str,
    version: int | None = None,
    tenant_id: str | None = None,
) -> BankItemView:
    """An editable lab copy (version 1) of a bundled or host-shared item (or one of the
    lab's own), with ``provenance.from`` remembering where it came from."""
    ctx = _ctx(actor, tenant_id, Action.BANK_MANAGE)
    found = _locate(builder, ctx, item_id, version)
    doc = copy.deepcopy(found.document)
    doc["provenance"] = {
        "from": {"library": found.source, "id": doc["id"], "version": doc["version"]}
    }
    doc.update({"id": PLACEHOLDER_ID, "version": 1})
    doc = _checked(doc, "That bank item can't be copied.")
    item, saved = _store_call(
        builder.store.create_bank_item, ctx, _meta_of(doc), doc, fragment_checksum(doc["fragment"])
    )
    return _stored_view(actor, ctx, item, saved)
