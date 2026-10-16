"""Tenant/actor context. Every repository method takes one; there is no default."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import AccessDenied


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Who is acting, and inside which tenant.

    ``actor`` is a user id, or a ``system:<job>`` / ``participant:<session>`` tag.
    Role checks are the caller's job (osp-app); the store only scopes by tenant.
    """

    tenant_id: str
    actor: str


@dataclass(frozen=True, slots=True)
class SystemContext:
    """Cross-tenant maintenance (retention, key rotation, tenant creation, login lookup).

    Deliberately a different type: tenant-scoped methods reject it, and
    system methods reject a TenantContext.
    """

    actor: str  # e.g. "system:retention"


def require_ctx(ctx: object) -> TenantContext:
    """Fail closed on a missing or malformed context."""
    if type(ctx) is not TenantContext:
        raise AccessDenied("a TenantContext is required")
    if not isinstance(ctx.tenant_id, str) or not ctx.tenant_id:
        raise AccessDenied("tenant_id must be a non-empty string")
    if not isinstance(ctx.actor, str) or not ctx.actor or len(ctx.actor) > 80:
        raise AccessDenied("actor must be a non-empty string of at most 80 characters")
    return ctx


def require_system(ctx: object) -> SystemContext:
    if type(ctx) is not SystemContext:
        raise AccessDenied("a SystemContext is required")
    if not isinstance(ctx.actor, str) or not ctx.actor.startswith("system:"):
        raise AccessDenied("system actor must be 'system:<job>'")
    return ctx
