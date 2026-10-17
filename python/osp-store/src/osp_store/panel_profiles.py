"""Property panel profiles (task B21, planning/property-profiles.md §3): one profile per
lab, saying which properties researchers see, their order, group headings, defaults for
new questions and the lab's custom properties.

Mixed into :class:`osp_store.Store`. Same rules as every other repository method: a
:class:`TenantContext` first, every query scoped to its tenant. The body is opaque JSON
here (an object of at most :data:`MAX_PROFILE_BYTES`); ``osp_spec.panel_profile``
validates it (osp-app's job). No row means the stock panel.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, Engine, delete, insert, select, update

from . import schema as t
from .context import TenantContext, require_ctx
from .crypto import canonical_json
from .errors import InvalidInput

MAX_PROFILE_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class StoredPanelProfile:
    tenant_id: str
    body: Any  # opaque profile JSON (an object)
    updated_by: str
    updated_at: datetime


def _profile_body(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidInput("profile body must be a JSON object")
    try:
        text = canonical_json(dict(value))
    except (TypeError, ValueError, RecursionError) as exc:
        raise InvalidInput(f"profile body is not JSON-serialisable: {exc}") from exc
    if len(text.encode("utf-8")) > MAX_PROFILE_BYTES:
        raise InvalidInput(f"profile body is larger than {MAX_PROFILE_BYTES} bytes")
    return json.loads(text)


class PanelProfiles:
    """Panel-profile methods; relies on Store's plumbing (engine, transactions, audit)."""

    _engine: Engine
    _tx: Callable[[], AbstractContextManager[Connection]]
    _now: Callable[[], datetime]
    _audit: Callable[..., None]
    _one: Callable[[Connection, Any], Any]

    @staticmethod
    def _stored_profile(r: Mapping[str, Any]) -> StoredPanelProfile:
        return StoredPanelProfile(r["tenant_id"], r["body"], r["updated_by"], r["updated_at"])

    def get_panel_profile(self, ctx: TenantContext) -> StoredPanelProfile | None:
        """The lab's profile, or None when it uses the stock panel."""
        ctx = require_ctx(ctx)
        with self._engine.connect() as conn:
            row = (
                conn.execute(
                    select(t.panel_profiles).where(t.panel_profiles.c.tenant_id == ctx.tenant_id)
                )
                .mappings()
                .first()
            )
            return None if row is None else self._stored_profile(row)

    def set_panel_profile(self, ctx: TenantContext, body: object) -> StoredPanelProfile:
        """Replace the lab's profile (creating it the first time)."""
        ctx = require_ctx(ctx)
        checked = _profile_body(body)
        values = {"body": checked, "updated_by": ctx.actor, "updated_at": self._now()}
        where = t.panel_profiles.c.tenant_id == ctx.tenant_id
        with self._tx() as conn:
            self._one(conn, select(t.tenants.c.id).where(t.tenants.c.id == ctx.tenant_id))
            if conn.execute(update(t.panel_profiles).where(where).values(values)).rowcount == 0:
                conn.execute(insert(t.panel_profiles).values(tenant_id=ctx.tenant_id, **values))
            self._audit(conn, ctx.tenant_id, ctx.actor, "profile.set", "tenant", ctx.tenant_id)
        return StoredPanelProfile(ctx.tenant_id, checked, ctx.actor, values["updated_at"])

    def clear_panel_profile(self, ctx: TenantContext) -> bool:
        """Back to the stock panel. Returns whether there was a profile to remove."""
        ctx = require_ctx(ctx)
        with self._tx() as conn:
            gone = conn.execute(
                delete(t.panel_profiles).where(t.panel_profiles.c.tenant_id == ctx.tenant_id)
            ).rowcount
            if gone:
                self._audit(
                    conn, ctx.tenant_id, ctx.actor, "profile.clear", "tenant", ctx.tenant_id
                )
            return bool(gone)
