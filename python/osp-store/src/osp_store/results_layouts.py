"""Saved results layouts (plan V, V-D9): a survey's named results-page layouts and its
default, shared by the lab.

Mixed into :class:`osp_store.Store`. Same rules as every other repository method: a
:class:`TenantContext` first, every query scoped to its tenant *and* the survey, a layout
of another tenant or another survey is :class:`NotFound`. ``settings`` is opaque JSON here
(an object of at most :data:`MAX_LAYOUT_BYTES`); ``osp_app.results_layouts`` validates it
against the layout schema and makes sure it never carries response data.
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

MAX_LAYOUT_BYTES = 64 * 1024
LAYOUT_NAME_MAX = 200


@dataclass(frozen=True, slots=True)
class StoredResultsLayout:
    id: str
    tenant_id: str
    survey_id: str
    name: str
    settings: Any  # opaque layout settings JSON (an object)
    is_default: bool
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime


def _layout_id(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 36:
        raise NotFound("no such results layout")
    return value


def _layout_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > LAYOUT_NAME_MAX:
        raise InvalidInput(f"layout name must be 1-{LAYOUT_NAME_MAX} characters")
    return value.strip()


def _layout_settings(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidInput("layout settings must be a JSON object")
    try:
        text = canonical_json(dict(value))
    except (TypeError, ValueError, RecursionError) as exc:
        raise InvalidInput(f"layout settings are not JSON-serialisable: {exc}") from exc
    if len(text.encode("utf-8")) > MAX_LAYOUT_BYTES:
        raise InvalidInput(f"layout settings are larger than {MAX_LAYOUT_BYTES} bytes")
    return json.loads(text)


class ResultsLayoutLibrary:
    """Results-layout methods; relies on Store's plumbing (engine, transactions, audit)."""

    _engine: Engine
    _tx: Callable[[], AbstractContextManager[Connection]]
    _now: Callable[[], datetime]
    _audit: Callable[..., None]
    _one: Callable[[Connection, Any], Any]

    # -- plumbing ------------------------------------------------------------------

    @staticmethod
    def _stored_layout(r: Mapping[str, Any], default_id: str | None) -> StoredResultsLayout:
        return StoredResultsLayout(
            r["id"],
            r["tenant_id"],
            r["survey_id"],
            r["name"],
            r["settings"],
            r["id"] == default_id,
            r["created_by"],
            r["created_at"],
            r["updated_by"],
            r["updated_at"],
        )

    def _layout_survey_where(self, ctx: TenantContext, survey_id: object) -> Any:
        if not isinstance(survey_id, str) or not survey_id or len(survey_id) > 36:
            raise NotFound("no such survey")
        return (t.results_layouts.c.tenant_id == ctx.tenant_id) & (
            t.results_layouts.c.survey_id == survey_id
        )

    def _layout_where(self, ctx: TenantContext, survey_id: object, layout_id: object) -> Any:
        return self._layout_survey_where(ctx, survey_id) & (
            t.results_layouts.c.id == _layout_id(layout_id)
        )

    def _default_where(self, ctx: TenantContext, survey_id: str) -> Any:
        return (t.results_layout_defaults.c.tenant_id == ctx.tenant_id) & (
            t.results_layout_defaults.c.survey_id == survey_id
        )

    def _require_survey(self, conn: Connection, ctx: TenantContext, survey_id: object) -> str:
        if not isinstance(survey_id, str) or not survey_id or len(survey_id) > 36:
            raise NotFound("no such survey")
        self._one(
            conn,
            select(t.surveys.c.id).where(
                (t.surveys.c.tenant_id == ctx.tenant_id) & (t.surveys.c.id == survey_id)
            ),
        )
        return survey_id

    def _default_layout_id(
        self, conn: Connection, ctx: TenantContext, survey_id: str
    ) -> str | None:
        stmt = select(t.results_layout_defaults.c.layout_id).where(
            self._default_where(ctx, survey_id)
        )
        return conn.execute(stmt).scalar_one_or_none()

    def _audit_layout(
        self,
        conn: Connection,
        ctx: TenantContext,
        action: str,
        survey_id: str,
        layout_id: str | None,
        **detail: Any,
    ) -> None:
        """Audit a layout change: ids and field names only, never the settings body."""
        target = ("results_layout", layout_id) if layout_id is not None else ("survey", survey_id)
        self._audit(
            conn, ctx.tenant_id, ctx.actor, action, *target, {"surveyId": survey_id, **detail}
        )

    def _load_layout(
        self, conn: Connection, ctx: TenantContext, survey_id: object, layout_id: object
    ) -> StoredResultsLayout:
        row = self._one(
            conn, select(t.results_layouts).where(self._layout_where(ctx, survey_id, layout_id))
        )
        return self._stored_layout(row, self._default_layout_id(conn, ctx, row["survey_id"]))

    def _set_default(
        self, conn: Connection, ctx: TenantContext, survey_id: str, layout_id: str
    ) -> None:
        values = {"layout_id": layout_id, "set_by": ctx.actor, "set_at": self._now()}
        where = self._default_where(ctx, survey_id)
        updated = conn.execute(update(t.results_layout_defaults).where(where).values(values))
        if updated.rowcount == 0:
            conn.execute(
                insert(t.results_layout_defaults).values(
                    survey_id=survey_id, tenant_id=ctx.tenant_id, **values
                )
            )
        self._audit_layout(conn, ctx, "results.layout.default.set", survey_id, layout_id)

    # -- public --------------------------------------------------------------------

    def create_results_layout(
        self,
        ctx: TenantContext,
        survey_id: str,
        name: str,
        settings: object,
        *,
        default: bool = False,
    ) -> StoredResultsLayout:
        """Save a layout for a survey. A duplicate name in the survey is a Conflict.
        ``default=True`` also makes it the survey's default layout."""
        ctx = require_ctx(ctx)
        name, settings = _layout_name(name), _layout_settings(settings)
        if not isinstance(default, bool):
            raise InvalidInput("default must be a boolean")
        row = {
            "id": str(uuid.uuid4()),
            "tenant_id": ctx.tenant_id,
            "name": name,
            "settings": settings,
            "created_by": ctx.actor,
            "created_at": self._now(),
            "updated_by": ctx.actor,
        }
        row["updated_at"] = row["created_at"]
        with self._tx() as conn:
            row["survey_id"] = self._require_survey(conn, ctx, survey_id)
            conn.execute(insert(t.results_layouts).values(**row))
            self._audit_layout(conn, ctx, "results.layout.create", survey_id, row["id"])
            if default:
                self._set_default(conn, ctx, survey_id, row["id"])
        return StoredResultsLayout(is_default=default, **row)

    def get_results_layout(
        self, ctx: TenantContext, survey_id: str, layout_id: str
    ) -> StoredResultsLayout:
        ctx = require_ctx(ctx)
        with self._engine.connect() as conn:
            return self._load_layout(conn, ctx, survey_id, layout_id)

    def list_results_layouts(self, ctx: TenantContext, survey_id: str) -> list[StoredResultsLayout]:
        """The survey's layouts by name. A survey the tenant doesn't have is NotFound."""
        ctx = require_ctx(ctx)
        with self._engine.connect() as conn:
            self._require_survey(conn, ctx, survey_id)
            default_id = self._default_layout_id(conn, ctx, survey_id)
            rows = conn.execute(
                select(t.results_layouts)
                .where(self._layout_survey_where(ctx, survey_id))
                .order_by(t.results_layouts.c.name, t.results_layouts.c.id)
            ).mappings()
            return [self._stored_layout(r, default_id) for r in rows]

    def get_default_results_layout_id(self, ctx: TenantContext, survey_id: str) -> str | None:
        ctx = require_ctx(ctx)
        with self._engine.connect() as conn:
            self._require_survey(conn, ctx, survey_id)
            return self._default_layout_id(conn, ctx, survey_id)

    def update_results_layout(
        self,
        ctx: TenantContext,
        survey_id: str,
        layout_id: str,
        *,
        name: str | None = None,
        settings: object | None = None,
    ) -> StoredResultsLayout:
        ctx = require_ctx(ctx)
        values: dict[str, Any] = {}
        if name is not None:
            values["name"] = _layout_name(name)
        if settings is not None:
            values["settings"] = _layout_settings(settings)
        with self._tx() as conn:
            self._load_layout(conn, ctx, survey_id, layout_id)
            if values:
                values |= {"updated_by": ctx.actor, "updated_at": self._now()}
                conn.execute(
                    update(t.results_layouts)
                    .where(self._layout_where(ctx, survey_id, layout_id))
                    .values(values)
                )
                fields = sorted(k for k in values if k in ("name", "settings"))
                self._audit_layout(
                    conn, ctx, "results.layout.update", survey_id, layout_id, fields=fields
                )
            return self._load_layout(conn, ctx, survey_id, layout_id)

    def delete_results_layout(self, ctx: TenantContext, survey_id: str, layout_id: str) -> None:
        """Delete a layout. If it was the survey's default, the survey has no default
        afterwards (the database clears it; this also deletes it explicitly)."""
        ctx = require_ctx(ctx)
        with self._tx() as conn:
            self._load_layout(conn, ctx, survey_id, layout_id)
            conn.execute(
                delete(t.results_layout_defaults).where(
                    self._default_where(ctx, survey_id)
                    & (t.results_layout_defaults.c.layout_id == layout_id)
                )
            )
            conn.execute(
                delete(t.results_layouts).where(self._layout_where(ctx, survey_id, layout_id))
            )
            self._audit_layout(conn, ctx, "results.layout.delete", survey_id, layout_id)

    def set_default_results_layout(
        self, ctx: TenantContext, survey_id: str, layout_id: str | None
    ) -> None:
        """Make one of the survey's layouts its default (None clears it)."""
        ctx = require_ctx(ctx)
        with self._tx() as conn:
            self._require_survey(conn, ctx, survey_id)
            if layout_id is None:
                conn.execute(
                    delete(t.results_layout_defaults).where(self._default_where(ctx, survey_id))
                )
                self._audit_layout(conn, ctx, "results.layout.default.clear", survey_id, None)
                return
            self._load_layout(conn, ctx, survey_id, layout_id)
            self._set_default(conn, ctx, survey_id, layout_id)
