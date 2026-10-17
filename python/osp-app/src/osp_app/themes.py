"""Lab theme library commands (runtime-design §6a "Reuse"; task B12).

A lab (tenant) keeps named themes and at most one lab default. Reading needs
``themes.view`` (every member); saving, changing, deleting and choosing the default need
``themes.manage`` (owner, editor). A survey's own theme is not here: the builder copies a
library theme into the survey with the ``set_theme`` op, so a survey never depends on a
library row (``osp_spec.model.Settings.theme``).

Theme bodies are checked against the theme schema on save (a schema error is ``Rejected``
with diagnostics). Contrast problems don't stop a save, since a theme can be saved mid-fix,
but a theme that fails the guard can't become the lab default: every survey without its own
theme would then be unpublishable.

Registered on import (``osp_app/__init__.py``); dispatched through ``Builder.run`` like the
other commands, so ``builder`` is the first argument.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from osp_spec import Diagnostic
from osp_spec.theme import validate_theme
from osp_store import Conflict, InvalidInput, NotFound, StoredTheme, TenantContext

from .auth.permissions import Action, Actor, Resource, can
from .builder import Builder
from .commands import command
from .errors import ConflictError, Forbidden, InvalidRequest, NotFoundError, Rejected


@dataclass(frozen=True)
class LabTheme:
    theme: StoredTheme
    is_default: bool
    diagnostics: list[Diagnostic]  # the contrast guard's findings (empty: passes)


@dataclass(frozen=True)
class ThemeLibraryView:
    tenant_id: str
    themes: list[LabTheme]
    default_theme_id: str | None
    can_manage: bool


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


def _diagnostics(body: Any) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    theme, found = validate_theme(body)
    diags = [
        Diagnostic(
            severity=d.severity,
            code=d.code,
            message=d.message
            + (f" Nearest passing value: {d.suggestion}." if d.suggestion is not None else ""),
            pointer=d.pointer,
        )
        for d in found
    ]
    return (None if theme is None else theme.model_dump(mode="json", by_alias=True)), diags


def _checked_body(body: Any) -> tuple[dict[str, Any], list[Diagnostic]]:
    theme, diags = _diagnostics(body)
    if theme is None:
        raise Rejected("That is not a valid theme.", diags)
    return theme, diags


def _view(t: StoredTheme, default_id: str | None) -> LabTheme:
    return LabTheme(t, t.id == default_id, _diagnostics(t.body)[1])


def _store_call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except NotFound as exc:
        raise NotFoundError("Theme not found.") from exc
    except Conflict as exc:
        raise ConflictError("The lab already has a theme with that name.") from exc
    except InvalidInput as exc:
        raise InvalidRequest(str(exc)) from exc


def _default_id(builder: Builder, ctx: TenantContext) -> str | None:
    d = builder.store.get_lab_default_theme(ctx)
    return None if d is None else d.id


@command("theme.list", label="List lab themes", action=Action.THEMES_VIEW)
def list_themes(
    builder: Builder, actor: Actor, *, tenant_id: str | None = None
) -> ThemeLibraryView:
    ctx = _ctx(actor, tenant_id, Action.THEMES_VIEW)
    default_id = _default_id(builder, ctx)
    return ThemeLibraryView(
        ctx.tenant_id,
        [_view(t, default_id) for t in builder.store.list_themes(ctx)],
        default_id,
        can(actor, Action.THEMES_MANAGE, Resource.tenant(ctx.tenant_id)),
    )


@command("theme.get", label="Get lab theme", action=Action.THEMES_VIEW)
def get_theme(
    builder: Builder, actor: Actor, *, theme_id: str, tenant_id: str | None = None
) -> LabTheme:
    ctx = _ctx(actor, tenant_id, Action.THEMES_VIEW)
    return _view(_store_call(builder.store.get_theme, ctx, theme_id), _default_id(builder, ctx))


@command("theme.create", label="Save theme to lab library", action=Action.THEMES_MANAGE)
def create_theme(
    builder: Builder, actor: Actor, *, name: str, theme: Any, tenant_id: str | None = None
) -> LabTheme:
    ctx = _ctx(actor, tenant_id, Action.THEMES_MANAGE)
    body, diags = _checked_body(theme)
    saved = _store_call(builder.store.create_theme, ctx, name, body)
    return LabTheme(saved, False, diags)


@command("theme.update", label="Update lab theme", action=Action.THEMES_MANAGE)
def update_theme(
    builder: Builder,
    actor: Actor,
    *,
    theme_id: str,
    name: str | None = None,
    theme: Any = None,
    tenant_id: str | None = None,
) -> LabTheme:
    ctx = _ctx(actor, tenant_id, Action.THEMES_MANAGE)
    body = None if theme is None else _checked_body(theme)[0]
    saved = _store_call(builder.store.update_theme, ctx, theme_id, name=name, body=body)
    return _view(saved, _default_id(builder, ctx))


@command("theme.delete", label="Delete lab theme", action=Action.THEMES_MANAGE)
def delete_theme(
    builder: Builder, actor: Actor, *, theme_id: str, tenant_id: str | None = None
) -> None:
    ctx = _ctx(actor, tenant_id, Action.THEMES_MANAGE)
    _store_call(builder.store.delete_theme, ctx, theme_id)


@command("theme.set_default", label="Make lab default theme", action=Action.THEMES_MANAGE)
def set_default_theme(
    builder: Builder, actor: Actor, *, theme_id: str | None, tenant_id: str | None = None
) -> ThemeLibraryView:
    """Make a library theme the lab default (``None`` clears it). Refused when the theme
    fails the contrast guard, since every survey without its own theme would use it."""
    ctx = _ctx(actor, tenant_id, Action.THEMES_MANAGE)
    if theme_id is not None:
        stored = _store_call(builder.store.get_theme, ctx, theme_id)
        diags = _diagnostics(stored.body)[1]
        if any(d.severity == "error" for d in diags):
            raise Rejected("Fix the theme's accessibility problems first.", diags)
    _store_call(builder.store.set_lab_default_theme, ctx, theme_id)
    return list_themes(builder, actor, tenant_id=ctx.tenant_id)
