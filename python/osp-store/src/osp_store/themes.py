"""Theme library (runtime-design §6a "Reuse"): a lab's saved themes and its lab default.

Mixed into :class:`osp_store.Store`. Same rules as every other repository method: a
:class:`TenantContext` first, every query scoped to its tenant, another tenant's theme is
:class:`NotFound`. Theme JSON is opaque here; ``osp_spec.theme`` validates it (osp-app's job).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, Engine, delete, insert, select, update

from . import schema as t
from .context import TenantContext, require_ctx
from .crypto import canonical_json
from .errors import InvalidInput, NotFound

MAX_THEME_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class StoredTheme:
    id: str
    tenant_id: str
    name: str
    body: Any  # opaque theme JSON (an object)
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime


def _theme_id(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 36:
        raise NotFound("no such theme")
    return value


def _theme_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise InvalidInput("theme name must be 1-200 characters")
    return value.strip()


def _theme_body(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidInput("theme body must be a JSON object")
    try:
        text = canonical_json(dict(value))
    except (TypeError, ValueError, RecursionError) as exc:
        raise InvalidInput(f"theme body is not JSON-serialisable: {exc}") from exc
    if len(text.encode("utf-8")) > MAX_THEME_BYTES:
        raise InvalidInput(f"theme body is larger than {MAX_THEME_BYTES} bytes")
    return json.loads(text)


class ThemeLibrary:
    """Theme-library methods; relies on Store's plumbing (engine, transactions, audit)."""

    _engine: Engine
    _tx: Callable[[], AbstractContextManager[Connection]]
    _now: Callable[[], datetime]
    _audit: Callable[..., None]
    _one: Callable[[Connection, Any], Any]

    @staticmethod
    def _stored_theme(r: Mapping[str, Any]) -> StoredTheme:
        return StoredTheme(
            r["id"],
            r["tenant_id"],
            r["name"],
            r["body"],
            r["created_by"],
            r["created_at"],
            r["updated_by"],
            r["updated_at"],
        )

    def _theme_where(self, ctx: TenantContext, theme_id: object) -> Any:
        return (t.themes.c.tenant_id == ctx.tenant_id) & (t.themes.c.id == _theme_id(theme_id))

    def _load_theme(self, conn: Connection, ctx: TenantContext, theme_id: object) -> StoredTheme:
        return self._stored_theme(
            self._one(conn, select(t.themes).where(self._theme_where(ctx, theme_id)))
        )

    def create_theme(self, ctx: TenantContext, name: str, body: object) -> StoredTheme:
        """Save a theme to the lab library. A duplicate name in the lab is a Conflict."""
        ctx = require_ctx(ctx)
        name, body = _theme_name(name), _theme_body(body)
        row = {
            "id": str(uuid.uuid4()),
            "tenant_id": ctx.tenant_id,
            "name": name,
            "body": body,
            "created_by": ctx.actor,
            "created_at": self._now(),
            "updated_by": ctx.actor,
        }
        row["updated_at"] = row["created_at"]
        with self._tx() as conn:
            self._one(conn, select(t.tenants.c.id).where(t.tenants.c.id == ctx.tenant_id))
            conn.execute(insert(t.themes).values(**row))
            self._audit(conn, ctx.tenant_id, ctx.actor, "theme.create", "theme", row["id"])
        return StoredTheme(**row)

    def get_theme(self, ctx: TenantContext, theme_id: str) -> StoredTheme:
        ctx = require_ctx(ctx)
        with self._engine.connect() as conn:
            return self._load_theme(conn, ctx, theme_id)

    def list_themes(self, ctx: TenantContext) -> list[StoredTheme]:
        ctx = require_ctx(ctx)
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(t.themes)
                .where(t.themes.c.tenant_id == ctx.tenant_id)
                .order_by(t.themes.c.name, t.themes.c.id)
            ).mappings()
            return [self._stored_theme(r) for r in rows]

    def update_theme(
        self,
        ctx: TenantContext,
        theme_id: str,
        *,
        name: str | None = None,
        body: object | None = None,
    ) -> StoredTheme:
        ctx = require_ctx(ctx)
        values: dict[str, Any] = {}
        if name is not None:
            values["name"] = _theme_name(name)
        if body is not None:
            values["body"] = _theme_body(body)
        with self._tx() as conn:
            self._load_theme(conn, ctx, theme_id)
            if values:
                values |= {"updated_by": ctx.actor, "updated_at": self._now()}
                conn.execute(
                    update(t.themes).where(self._theme_where(ctx, theme_id)).values(values)
                )
                self._audit(
                    conn, ctx.tenant_id, ctx.actor, "theme.update", "theme", theme_id,
                    {"fields": sorted(k for k in values if k in ("name", "body"))},
                )  # fmt: skip
            return self._load_theme(conn, ctx, theme_id)

    def delete_theme(self, ctx: TenantContext, theme_id: str) -> None:
        """Delete a theme. If it was the lab default, the lab has no default afterwards.
        Surveys keep their own copy of a theme, so nothing else changes."""
        ctx = require_ctx(ctx)
        with self._tx() as conn:
            self._load_theme(conn, ctx, theme_id)
            conn.execute(
                delete(t.lab_theme_defaults).where(
                    (t.lab_theme_defaults.c.tenant_id == ctx.tenant_id)
                    & (t.lab_theme_defaults.c.theme_id == theme_id)
                )
            )
            conn.execute(delete(t.themes).where(self._theme_where(ctx, theme_id)))
            self._audit(conn, ctx.tenant_id, ctx.actor, "theme.delete", "theme", theme_id)

    def set_lab_default_theme(self, ctx: TenantContext, theme_id: str | None) -> None:
        """Make one of the lab's themes the default for new surveys (None clears it)."""
        ctx = require_ctx(ctx)
        where = t.lab_theme_defaults.c.tenant_id == ctx.tenant_id
        with self._tx() as conn:
            if theme_id is None:
                conn.execute(delete(t.lab_theme_defaults).where(where))
                self._audit(conn, ctx.tenant_id, ctx.actor, "theme.default.clear")
                return
            self._load_theme(conn, ctx, theme_id)
            values = {"theme_id": theme_id, "set_by": ctx.actor, "set_at": self._now()}
            if conn.execute(update(t.lab_theme_defaults).where(where).values(values)).rowcount == 0:
                conn.execute(insert(t.lab_theme_defaults).values(tenant_id=ctx.tenant_id, **values))
            self._audit(conn, ctx.tenant_id, ctx.actor, "theme.default.set", "theme", theme_id)

    def get_lab_default_theme(self, ctx: TenantContext) -> StoredTheme | None:
        ctx = require_ctx(ctx)
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t.themes)
                .join(
                    t.lab_theme_defaults,
                    (t.lab_theme_defaults.c.tenant_id == t.themes.c.tenant_id)
                    & (t.lab_theme_defaults.c.theme_id == t.themes.c.id),
                )
                .where(t.lab_theme_defaults.c.tenant_id == ctx.tenant_id)
            ).mappings().first()  # fmt: skip
            return None if row is None else self._stored_theme(row)
