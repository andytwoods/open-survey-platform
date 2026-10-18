"""Question bank (task QB4, planning/question-bank.md §3): a lab's saved bank items and
every version of each.

Mixed into :class:`osp_store.Store`. Same rules as every other repository method: a
:class:`TenantContext` first, every query scoped to its tenant. The one deliberate
exception is *host sharing*: an item whose ``visibility`` is ``host`` is readable by every
lab on the host (``include_host``, the app's ``OSP_BANK_HOST_SHARING`` switch), but only
its own lab may change it. A delete is soft (``deleted_at``): surveys that inserted the
item keep pointing at it, the owning lab still reads it, other labs and every list stop
seeing it.

Documents are opaque here: the app validates an ``osp-bank-item/0.1`` document with
``osp_spec.bank`` and hands the store the document plus the columns lists and filters need
(:class:`BankItemMeta`). The store owns two keys of the document, ``id`` and ``version``,
and writes them on save. A version's ``body`` is never rewritten after it is saved, except
its metadata keys (title, abbreviation, description, tags, licence) on the *current*
version when the item's metadata is edited: the fragment of a saved version is immutable.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, Engine, func, insert, select, update

from . import schema as t
from .context import TenantContext, require_ctx
from .crypto import canonical_json
from .errors import Conflict, InvalidInput, NotFound

MAX_BANK_BYTES = 256 * 1024
MAX_SEARCH_BYTES = 64 * 1024
BANK_KINDS = ("question", "page", "block")
BANK_VISIBILITIES = ("lab", "host")
#: Document keys an item's metadata edit may rewrite on the current version.
META_KEYS = frozenset({"title", "abbreviation", "description", "tags", "licence"})


@dataclass(frozen=True, slots=True)
class StoredBankItem:
    id: str
    tenant_id: str
    visibility: str  # lab | host
    licence_class: str
    title: str
    abbreviation: str | None
    kind: str  # question | page | block
    tags: list[str]
    languages: list[str]
    current_version: int
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime
    deleted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class StoredBankVersion:
    item_id: str
    version: int
    body: Any  # the whole osp-bank-item/0.1 document (an object)
    checksum: str  # sha256:<hex> of the fragment
    created_by: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class BankItemMeta:
    """The columns of a bank item, taken from its validated document by the app."""

    title: str
    kind: str
    licence_class: str
    search_text: str
    abbreviation: str | None = None
    tags: Sequence[str] = ()
    languages: Sequence[str] = ()


def _bank_id(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 36:
        raise NotFound("no such bank item")
    return value


def _str(value: object, what: str, max_len: int, *, optional: bool = False) -> Any:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > max_len:
        raise InvalidInput(f"{what} must be 1-{max_len} characters")
    return value.strip()


def _strings(value: object, what: str, max_len: int = 80) -> list[str]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise InvalidInput(f"{what} must be a list of strings")
    out = []
    for v in value:
        if not isinstance(v, str) or not v or len(v) > max_len:
            raise InvalidInput(f"{what} must be a list of strings of 1-{max_len} characters")
        out.append(v)
    return out


def _meta(value: object) -> BankItemMeta:
    if not isinstance(value, BankItemMeta):
        raise InvalidInput("meta must be a BankItemMeta")
    if value.kind not in BANK_KINDS:
        raise InvalidInput(f"kind must be one of {', '.join(BANK_KINDS)}")
    search = value.search_text
    if not isinstance(search, str) or len(search.encode("utf-8")) > MAX_SEARCH_BYTES:
        raise InvalidInput(f"search_text must be a string of at most {MAX_SEARCH_BYTES} bytes")
    return BankItemMeta(
        _str(value.title, "title", 200),
        value.kind,
        _str(value.licence_class, "licence_class", 40),
        search,
        _str(value.abbreviation, "abbreviation", 40, optional=True),
        _strings(value.tags, "tags", 40),
        _strings(value.languages, "languages", 40),
    )


def _body(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidInput("bank item body must be a JSON object")
    try:
        text = canonical_json(dict(value))
    except (TypeError, ValueError, RecursionError) as exc:
        raise InvalidInput(f"bank item body is not JSON-serialisable: {exc}") from exc
    if len(text.encode("utf-8")) > MAX_BANK_BYTES:
        raise InvalidInput(f"bank item body is larger than {MAX_BANK_BYTES} bytes")
    return json.loads(text)


def _checksum(value: object) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= 80:
        raise InvalidInput("checksum must be a string of 1-80 characters")
    return value


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@dataclass
class BankQuery:
    """Filters for :meth:`BankLibrary.list_bank_items` (all optional)."""

    q: str | None = None  # every whitespace-separated term must appear in search_text
    kind: str | None = None
    source: str | None = None  # "lab" (my lab's items) | "host" (other labs' shared items)
    licence_class: str | None = None
    language: str | None = None
    tags: Sequence[str] = field(default_factory=tuple)  # every tag must be present


class BankLibrary:
    """Question-bank methods; relies on Store's plumbing (engine, transactions, audit)."""

    _engine: Engine
    _tx: Callable[[], AbstractContextManager[Connection]]
    _now: Callable[[], datetime]
    _audit: Callable[..., None]
    _one: Callable[[Connection, Any], Any]

    @staticmethod
    def _stored_item(r: Mapping[str, Any]) -> StoredBankItem:
        return StoredBankItem(
            r["id"],
            r["tenant_id"],
            r["visibility"],
            r["licence_class"],
            r["title"],
            r["abbreviation"],
            r["kind"],
            list(r["tags"]),
            list(r["languages"]),
            r["current_version"],
            r["created_by"],
            r["created_at"],
            r["updated_by"],
            r["updated_at"],
            r["deleted_at"],
        )

    @staticmethod
    def _stored_version(r: Mapping[str, Any]) -> StoredBankVersion:
        return StoredBankVersion(
            r["item_id"], r["version"], r["body"], r["checksum"], r["created_by"], r["created_at"]
        )

    # -- where clauses --------------------------------------------------------------

    @staticmethod
    def _visible(ctx: TenantContext, include_host: bool) -> Any:
        """Rows the lab may read: its own (deleted or not), plus other labs' host-shared
        live items when host sharing is on."""
        own = t.bank_items.c.tenant_id == ctx.tenant_id
        if not include_host:
            return own
        shared = (t.bank_items.c.visibility == "host") & t.bank_items.c.deleted_at.is_(None)
        return own | shared

    def _readable(self, ctx: TenantContext, item_id: object, include_host: bool) -> Any:
        return self._visible(ctx, include_host) & (t.bank_items.c.id == _bank_id(item_id))

    @staticmethod
    def _owned(ctx: TenantContext, item_id: object) -> Any:
        return (t.bank_items.c.tenant_id == ctx.tenant_id) & (
            t.bank_items.c.id == _bank_id(item_id)
        )

    def _load_owned(self, conn: Connection, ctx: TenantContext, item_id: object) -> StoredBankItem:
        """The lab's own item, for a write. A deleted item can't be changed."""
        item = self._stored_item(
            self._one(conn, select(t.bank_items).where(self._owned(ctx, item_id)))
        )
        if item.deleted_at is not None:
            raise Conflict("bank item is deleted")
        return item

    def _load_version(self, conn: Connection, item_id: str, version: int) -> StoredBankVersion:
        return self._stored_version(
            self._one(
                conn,
                select(t.bank_item_versions).where(
                    (t.bank_item_versions.c.item_id == item_id)
                    & (t.bank_item_versions.c.version == version)
                ),
            )
        )

    @staticmethod
    def _row_values(meta: BankItemMeta) -> dict[str, Any]:
        return {
            "licence_class": meta.licence_class,
            "title": meta.title,
            "abbreviation": meta.abbreviation,
            "kind": meta.kind,
            "tags": list(meta.tags),
            "languages": list(meta.languages),
            "search_text": meta.search_text,
        }

    # -- writes ---------------------------------------------------------------------

    def create_bank_item(
        self,
        ctx: TenantContext,
        meta: BankItemMeta,
        body: object,
        checksum: str,
        *,
        imported: bool = False,
    ) -> tuple[StoredBankItem, StoredBankVersion]:
        """Save a new item at version 1 (visibility ``lab``). The store assigns the id and
        writes ``id`` and ``version`` into the document. Audited as ``bank.save`` (or
        ``bank.import`` when ``imported``) with the version, kind and licence class, never
        the item text."""
        ctx = require_ctx(ctx)
        meta, doc, digest = _meta(meta), _body(body), _checksum(checksum)
        item_id, now = str(uuid.uuid4()), self._now()
        doc.update({"id": item_id, "version": 1})
        row = {
            "id": item_id,
            "tenant_id": ctx.tenant_id,
            "visibility": "lab",
            "current_version": 1,
            "created_by": ctx.actor,
            "created_at": now,
            "updated_by": ctx.actor,
            "updated_at": now,
            "deleted_at": None,
            **self._row_values(meta),
        }
        with self._tx() as conn:
            self._one(conn, select(t.tenants.c.id).where(t.tenants.c.id == ctx.tenant_id))
            conn.execute(insert(t.bank_items).values(**row))
            conn.execute(
                insert(t.bank_item_versions).values(
                    item_id=item_id,
                    version=1,
                    tenant_id=ctx.tenant_id,
                    body=doc,
                    checksum=digest,
                    created_by=ctx.actor,
                    created_at=now,
                )
            )
            self._audit(
                conn,
                ctx.tenant_id,
                ctx.actor,
                "bank.import" if imported else "bank.save",
                "bank_item",
                item_id,
                {"version": 1, "kind": meta.kind, "licence_class": meta.licence_class},
            )
            item = self._stored_item(
                self._one(conn, select(t.bank_items).where(t.bank_items.c.id == item_id))
            )
        return item, StoredBankVersion(item_id, 1, doc, digest, ctx.actor, now)

    def add_bank_version(
        self, ctx: TenantContext, item_id: str, meta: BankItemMeta, body: object, checksum: str
    ) -> tuple[StoredBankItem, StoredBankVersion]:
        """Version *n+1* of the lab's own item; the item's columns follow the new document.
        Older versions stay as they are. Audited as ``bank.save``."""
        ctx = require_ctx(ctx)
        meta, doc, digest = _meta(meta), _body(body), _checksum(checksum)
        now = self._now()
        with self._tx() as conn:
            current = self._load_owned(conn, ctx, item_id)
            if meta.kind != current.kind:
                raise InvalidInput(f"a {current.kind} item can't become a {meta.kind}")
            number = current.current_version + 1
            doc.update({"id": current.id, "version": number})
            conn.execute(
                insert(t.bank_item_versions).values(
                    item_id=current.id,
                    version=number,
                    tenant_id=ctx.tenant_id,
                    body=doc,
                    checksum=digest,
                    created_by=ctx.actor,
                    created_at=now,
                )
            )
            conn.execute(
                update(t.bank_items)
                .where(self._owned(ctx, current.id))
                .values(
                    current_version=number,
                    updated_by=ctx.actor,
                    updated_at=now,
                    **self._row_values(meta),
                )
            )
            self._audit(
                conn,
                ctx.tenant_id,
                ctx.actor,
                "bank.save",
                "bank_item",
                current.id,
                {"version": number, "kind": meta.kind, "licence_class": meta.licence_class},
            )
            item = self._stored_item(
                self._one(conn, select(t.bank_items).where(t.bank_items.c.id == current.id))
            )
        return item, StoredBankVersion(current.id, number, doc, digest, ctx.actor, now)

    def update_bank_item(
        self,
        ctx: TenantContext,
        item_id: str,
        meta: BankItemMeta,
        fields: Mapping[str, Any],
    ) -> tuple[StoredBankItem, StoredBankVersion]:
        """Metadata edit without a new version: ``fields`` (a subset of :data:`META_KEYS`,
        already validated by the app as part of the whole document) are written into the
        current version's document and ``meta`` into the item's columns. The fragment is
        untouched. Audited as ``bank.update`` with the field names."""
        ctx = require_ctx(ctx)
        meta = _meta(meta)
        if not isinstance(fields, Mapping) or not set(fields) <= META_KEYS:
            raise InvalidInput(f"fields must be a subset of {sorted(META_KEYS)}")
        patch = _body(dict(fields))
        now = self._now()
        with self._tx() as conn:
            current = self._load_owned(conn, ctx, item_id)
            if meta.kind != current.kind:
                raise InvalidInput("kind can't change in a metadata edit")
            version = self._load_version(conn, current.id, current.current_version)
            doc = {**version.body, **patch}
            doc = {k: v for k, v in doc.items() if not (k in patch and v is None)}
            conn.execute(
                update(t.bank_item_versions)
                .where(
                    (t.bank_item_versions.c.item_id == current.id)
                    & (t.bank_item_versions.c.version == current.current_version)
                )
                .values(body=doc)
            )
            conn.execute(
                update(t.bank_items)
                .where(self._owned(ctx, current.id))
                .values(updated_by=ctx.actor, updated_at=now, **self._row_values(meta))
            )
            self._audit(
                conn,
                ctx.tenant_id,
                ctx.actor,
                "bank.update",
                "bank_item",
                current.id,
                {"fields": sorted(patch), "licence_class": meta.licence_class},
            )
            item = self._stored_item(
                self._one(conn, select(t.bank_items).where(t.bank_items.c.id == current.id))
            )
            version = self._load_version(conn, current.id, current.current_version)
        return item, version

    def set_bank_visibility(
        self, ctx: TenantContext, item_id: str, visibility: str
    ) -> StoredBankItem:
        """``lab`` (private) or ``host`` (readable by every lab on the host). The licence
        rules for sharing are the app's. Audited as ``bank.share``."""
        ctx = require_ctx(ctx)
        if visibility not in BANK_VISIBILITIES:
            raise InvalidInput(f"visibility must be one of {', '.join(BANK_VISIBILITIES)}")
        with self._tx() as conn:
            current = self._load_owned(conn, ctx, item_id)
            if current.visibility != visibility:
                conn.execute(
                    update(t.bank_items)
                    .where(self._owned(ctx, current.id))
                    .values(visibility=visibility, updated_by=ctx.actor, updated_at=self._now())
                )
                self._audit(
                    conn,
                    ctx.tenant_id,
                    ctx.actor,
                    "bank.share",
                    "bank_item",
                    current.id,
                    {"visibility": visibility, "licence_class": current.licence_class},
                )
            return self._stored_item(
                self._one(conn, select(t.bank_items).where(t.bank_items.c.id == current.id))
            )

    def delete_bank_item(self, ctx: TenantContext, item_id: str) -> StoredBankItem:
        """Soft delete: the row and its versions stay (surveys point at them), the owning
        lab still reads it, lists and other labs don't. Audited as ``bank.delete``."""
        ctx = require_ctx(ctx)
        with self._tx() as conn:
            current = self._load_owned(conn, ctx, item_id)
            now = self._now()
            conn.execute(
                update(t.bank_items)
                .where(self._owned(ctx, current.id))
                .values(deleted_at=now, updated_by=ctx.actor, updated_at=now)
            )
            self._audit(conn, ctx.tenant_id, ctx.actor, "bank.delete", "bank_item", current.id)
            return self._stored_item(
                self._one(conn, select(t.bank_items).where(t.bank_items.c.id == current.id))
            )

    # -- reads ----------------------------------------------------------------------

    def get_bank_item(
        self, ctx: TenantContext, item_id: str, *, include_host: bool = True
    ) -> StoredBankItem:
        """The lab's own item (deleted or not), or another lab's live host-shared item."""
        ctx = require_ctx(ctx)
        with self._engine.connect() as conn:
            return self._stored_item(
                self._one(
                    conn,
                    select(t.bank_items).where(self._readable(ctx, item_id, include_host)),
                )
            )

    def get_bank_version(
        self,
        ctx: TenantContext,
        item_id: str,
        version: int | None = None,
        *,
        include_host: bool = True,
    ) -> StoredBankVersion:
        """One version's document (``None``: the current one)."""
        ctx = require_ctx(ctx)
        if version is not None and (type(version) is not int or version < 1):
            raise NotFound("no such bank item version")
        with self._engine.connect() as conn:
            item = self._stored_item(
                self._one(
                    conn,
                    select(t.bank_items).where(self._readable(ctx, item_id, include_host)),
                )
            )
            return self._load_version(
                conn, item.id, item.current_version if version is None else version
            )

    def list_bank_versions(
        self, ctx: TenantContext, item_id: str, *, include_host: bool = True
    ) -> list[StoredBankVersion]:
        """Every version of an item the lab may read, oldest first."""
        ctx = require_ctx(ctx)
        with self._engine.connect() as conn:
            item = self._stored_item(
                self._one(
                    conn,
                    select(t.bank_items).where(self._readable(ctx, item_id, include_host)),
                )
            )
            rows = conn.execute(
                select(t.bank_item_versions)
                .where(t.bank_item_versions.c.item_id == item.id)
                .order_by(t.bank_item_versions.c.version)
            ).mappings()
            return [self._stored_version(r) for r in rows]

    def list_bank_items(
        self, ctx: TenantContext, query: BankQuery | None = None, *, include_host: bool = True
    ) -> list[StoredBankItem]:
        """Live items the lab may read (its own, plus other labs' host-shared ones when
        ``include_host``), filtered by ``query``, ordered by title then id. The search is a
        case-insensitive LIKE over ``search_text``: every term must appear."""
        ctx = require_ctx(ctx)
        query = query or BankQuery()
        where = self._visible(ctx, include_host) & t.bank_items.c.deleted_at.is_(None)
        if query.source == "lab":
            where &= t.bank_items.c.tenant_id == ctx.tenant_id
        elif query.source == "host":
            if not include_host:
                return []
            where &= t.bank_items.c.tenant_id != ctx.tenant_id
        elif query.source is not None:
            raise InvalidInput("source must be lab or host")
        if query.kind is not None:
            if query.kind not in BANK_KINDS:
                raise InvalidInput(f"kind must be one of {', '.join(BANK_KINDS)}")
            where &= t.bank_items.c.kind == query.kind
        if query.licence_class is not None:
            where &= t.bank_items.c.licence_class == _str(query.licence_class, "licence", 40)
        if query.q is not None:
            if not isinstance(query.q, str) or len(query.q) > 200:
                raise InvalidInput("q must be a string of at most 200 characters")
            for term in query.q.lower().split():
                where &= func.lower(t.bank_items.c.search_text).like(_like(term), escape="\\")
        tags = _strings(query.tags, "tags", 40)
        language = _str(query.language, "language", 40, optional=True)
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(t.bank_items).where(where).order_by(t.bank_items.c.title, t.bank_items.c.id)
            ).mappings()
            items = [self._stored_item(r) for r in rows]
        if language is not None:
            items = [i for i in items if language in i.languages]
        if tags:
            items = [i for i in items if set(tags) <= set(i.tags)]
        return items
