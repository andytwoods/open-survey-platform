"""Lab property panel profile commands (task B21, planning/property-profiles.md §3).

A lab (tenant) has at most one profile: which properties researchers see in the builder's
property panel, their order, group headings, defaults for new questions and the lab's
custom properties. Reading needs ``profile.view`` (every member); setting and clearing
need ``profile.manage`` (owner only). The profile is a view of the stock property schema
plus annotations: it never changes how a survey runs, and a survey never depends on it.

A profile is checked on save: a structural error is ``Rejected`` with diagnostics; parts
that do not apply (a hidden required property, a default the model refuses) are saved
and returned as warnings, so a lab can fix them at its own pace while the stock schema
stands in for those parts.

Registered on import (``osp_app/__init__.py``); dispatched through ``Builder.run``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from osp_spec import Diagnostic
from osp_spec.panel_profile import (
    PanelProfile,
    apply_profile,
    check_custom_values,
    profile_schemas_json,
    validate_profile,
)
from osp_store import InvalidInput, NotFound, StoredPanelProfile, TenantContext

from .auth.permissions import Action, Actor, Resource, can
from .builder import Builder
from .commands import command
from .errors import Forbidden, InvalidRequest, NotFoundError, Rejected


@dataclass(frozen=True)
class PanelProfileView:
    tenant_id: str
    profile: dict[str, Any] | None  # None: the stock panel
    diagnostics: list[Diagnostic]  # what did not apply (warnings); empty for the stock panel
    can_manage: bool
    updated_by: str | None = None
    updated_at: datetime | None = None


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


def _parsed(stored: StoredPanelProfile | None) -> tuple[PanelProfile | None, list[Diagnostic]]:
    """The stored profile as a model. A stored body that no longer validates (an older
    format, say) counts as the stock panel, with its diagnostics."""
    if stored is None:
        return None, []
    profile, diags = validate_profile(stored.body)
    if profile is None:
        return None, diags
    return profile, apply_profile(profile)[1]


def _view(builder: Builder, actor: Actor, ctx: TenantContext) -> PanelProfileView:
    stored = builder.store.get_panel_profile(ctx)
    profile, diags = _parsed(stored)
    return PanelProfileView(
        ctx.tenant_id,
        None if profile is None else profile.model_dump(mode="json", exclude_none=True),
        diags,
        can(actor, Action.PROFILE_MANAGE, Resource.tenant(ctx.tenant_id)),
        None if stored is None else stored.updated_by,
        None if stored is None else stored.updated_at,
    )


def lab_profile(builder: Builder, ctx: TenantContext) -> PanelProfile | None:
    """The lab's profile as a model, for other commands (None: the stock panel)."""
    return _parsed(builder.store.get_panel_profile(ctx))[0]


@command("profile.get", label="Get lab panel profile", action=Action.PROFILE_VIEW)
def get_profile(
    builder: Builder, actor: Actor, *, tenant_id: str | None = None
) -> PanelProfileView:
    return _view(builder, actor, _ctx(actor, tenant_id, Action.PROFILE_VIEW))


@command("profile.set", label="Set lab panel profile", action=Action.PROFILE_MANAGE)
def set_profile(
    builder: Builder, actor: Actor, *, profile: Any, tenant_id: str | None = None
) -> PanelProfileView:
    ctx = _ctx(actor, tenant_id, Action.PROFILE_MANAGE)
    parsed, diags = validate_profile(profile)
    if parsed is None:
        raise Rejected("That is not a valid panel profile.", diags)
    body = parsed.model_dump(mode="json", exclude_none=True)
    try:
        builder.store.set_panel_profile(ctx, body)
    except NotFound as exc:
        raise NotFoundError("Lab not found.") from exc
    except InvalidInput as exc:
        raise InvalidRequest(str(exc)) from exc
    return _view(builder, actor, ctx)


@command("profile.clear", label="Clear lab panel profile", action=Action.PROFILE_MANAGE)
def clear_profile(builder: Builder, actor: Actor, *, tenant_id: str | None = None) -> None:
    builder.store.clear_panel_profile(_ctx(actor, tenant_id, Action.PROFILE_MANAGE))


@command("profile.schemas", label="Effective property schemas", action=Action.PROFILE_VIEW)
def profile_schemas(
    builder: Builder, actor: Actor, *, tenant_id: str | None = None
) -> dict[str, Any]:
    """The property schemas the builder renders for this lab: the stock ones with the
    lab's profile applied (``osp_spec.panel_profile.profile_schemas_json``)."""
    ctx = _ctx(actor, tenant_id, Action.PROFILE_VIEW)
    return profile_schemas_json(lab_profile(builder, ctx))


@command("profile.check", label="Check a survey's custom values", action=Action.SURVEY_READ)
def check_survey(builder: Builder, actor: Actor, *, survey_id: str) -> list[Diagnostic]:
    """Warnings about a survey draft's custom values judged by its lab's profile (a value
    of the wrong kind, an undefined key, a required key missing). Never errors."""
    ctx = builder._locate(actor, survey_id, Action.SURVEY_READ)
    profile = lab_profile(builder, ctx)
    if profile is None:
        return []
    draft = builder.store.get_draft(ctx, survey_id)
    return check_custom_values(draft.body, profile)
