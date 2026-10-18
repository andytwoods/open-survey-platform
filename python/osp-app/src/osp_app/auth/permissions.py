"""Permissions policy: one function, `can(actor, action, resource)`, fail closed.

Anything not explicitly granted is denied: unknown actions, unknown roles,
no membership, a resource in another tenant, a missing actor, an action on the
wrong kind of resource, or any unexpected input. `can` never raises.

Survey-level sharing (post-MVP) slots in at `_effective_role`: a per-survey
grant would be looked up there and combined with the tenant role.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .model import Role


class Action(StrEnum):
    SURVEY_READ = "survey.read"
    SURVEY_EDIT = "survey.edit"
    SURVEY_PUBLISH = "survey.publish"
    SURVEY_EXPORT = "survey.export"  # includes response data
    SURVEY_DELETE = "survey.delete"
    RESPONSE_DELETE = "response.delete"  # delete one participant's response (withdrawal)
    MEMBERS_VIEW = "members.view"
    MEMBERS_MANAGE = "members.manage"  # invite, remove, change roles
    THEMES_VIEW = "themes.view"  # the lab theme library (runtime-design §6a)
    THEMES_MANAGE = "themes.manage"  # save, change, delete themes; set the lab default
    PROFILE_VIEW = "profile.view"  # the lab's property panel profile (property-profiles.md)
    PROFILE_MANAGE = "profile.manage"  # set or clear it (owner only)
    BANK_VIEW = "bank.view"  # the question bank (question-bank.md §3): browse, search
    BANK_MANAGE = "bank.manage"  # save, new version, tag, delete, import, export
    BANK_SHARE = "bank.share"  # host visibility; a `licensed-to-lab` item (owner only)


class ResourceKind(StrEnum):
    SURVEY = "survey"
    TENANT = "tenant"  # member management targets the tenant itself


_ACTION_KIND: Mapping[Action, ResourceKind] = {
    Action.SURVEY_READ: ResourceKind.SURVEY,
    Action.SURVEY_EDIT: ResourceKind.SURVEY,
    Action.SURVEY_PUBLISH: ResourceKind.SURVEY,
    Action.SURVEY_EXPORT: ResourceKind.SURVEY,
    Action.SURVEY_DELETE: ResourceKind.SURVEY,
    Action.RESPONSE_DELETE: ResourceKind.SURVEY,
    Action.MEMBERS_VIEW: ResourceKind.TENANT,
    Action.MEMBERS_MANAGE: ResourceKind.TENANT,
    Action.THEMES_VIEW: ResourceKind.TENANT,
    Action.THEMES_MANAGE: ResourceKind.TENANT,
    Action.PROFILE_VIEW: ResourceKind.TENANT,
    Action.PROFILE_MANAGE: ResourceKind.TENANT,
    Action.BANK_VIEW: ResourceKind.TENANT,
    Action.BANK_MANAGE: ResourceKind.TENANT,
    Action.BANK_SHARE: ResourceKind.TENANT,
}

POLICY: Mapping[Role, frozenset[Action]] = {
    Role.VIEWER: frozenset(
        {Action.SURVEY_READ, Action.THEMES_VIEW, Action.PROFILE_VIEW, Action.BANK_VIEW}
    ),
    Role.EDITOR: frozenset(
        {
            Action.SURVEY_READ,
            Action.SURVEY_EDIT,
            Action.SURVEY_PUBLISH,
            Action.SURVEY_EXPORT,
            Action.RESPONSE_DELETE,
            Action.MEMBERS_VIEW,
            Action.THEMES_VIEW,
            Action.THEMES_MANAGE,
            Action.PROFILE_VIEW,
            Action.BANK_VIEW,
            Action.BANK_MANAGE,
        }
    ),
    Role.OWNER: frozenset(Action),
}


@dataclass(frozen=True)
class Actor:
    """Who is acting. Built fresh on every request from what the host says
    (``osp_app.identity``), so role changes apply immediately."""

    user_id: str
    roles: Mapping[str, Role | str] = field(default_factory=dict)  # tenant_id -> role


@dataclass(frozen=True)
class Resource:
    kind: ResourceKind
    tenant_id: str
    id: str | None = None

    @classmethod
    def survey(cls, tenant_id: str, survey_id: str) -> Resource:
        return cls(ResourceKind.SURVEY, tenant_id, survey_id)

    @classmethod
    def tenant(cls, tenant_id: str) -> Resource:
        return cls(ResourceKind.TENANT, tenant_id, tenant_id)


def _effective_role(actor: Actor, resource: Resource) -> Role | None:
    raw = actor.roles.get(resource.tenant_id)
    if raw is None:
        return None
    try:
        return Role(raw)
    except ValueError:
        return None


def can(actor: object, action: object, resource: object) -> bool:
    try:
        if not isinstance(actor, Actor) or not isinstance(resource, Resource):
            return False
        if not isinstance(action, Action) and not isinstance(action, str):
            return False
        try:
            act = Action(action)
        except ValueError:
            return False
        if not isinstance(resource.tenant_id, str) or not resource.tenant_id:
            return False
        if _ACTION_KIND.get(act) != resource.kind:
            return False
        role = _effective_role(actor, resource)
        if role is None:
            return False
        return act in POLICY.get(role, frozenset())
    except Exception:
        return False


class PermissionDenied(Exception):
    """Raised by `authorize` / `requires`. Deliberately carries no detail about
    *why*, so callers can't leak whether a resource exists."""

    def __init__(self) -> None:
        super().__init__("Not permitted.")


def authorize(actor: object, action: Action, resource: object) -> None:
    if not can(actor, action, resource):
        raise PermissionDenied()


def requires[**P, R](
    action: Action,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator for app commands whose first two arguments are
    `(actor: Actor, resource: Resource, ...)`. Checks before running."""

    def wrap(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def inner(*args: P.args, **kwargs: P.kwargs) -> R:
            actor: Any = kwargs.get("actor", args[0] if args else None)
            resource: Any = kwargs.get("resource", args[1] if len(args) > 1 else None)
            authorize(actor, action, resource)
            return fn(*args, **kwargs)

        inner.required_action = action  # type: ignore[attr-defined]
        return inner

    return wrap
