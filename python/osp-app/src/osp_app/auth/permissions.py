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

from .model import Membership, Role


class Action(StrEnum):
    SURVEY_READ = "survey.read"
    SURVEY_EDIT = "survey.edit"
    SURVEY_PUBLISH = "survey.publish"
    SURVEY_EXPORT = "survey.export"  # includes response data
    SURVEY_DELETE = "survey.delete"
    RESPONSE_DELETE = "response.delete"  # delete one participant's response (withdrawal)
    MEMBERS_VIEW = "members.view"
    MEMBERS_MANAGE = "members.manage"  # invite, remove, change roles


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
}

POLICY: Mapping[Role, frozenset[Action]] = {
    Role.VIEWER: frozenset({Action.SURVEY_READ}),
    Role.EDITOR: frozenset(
        {
            Action.SURVEY_READ,
            Action.SURVEY_EDIT,
            Action.SURVEY_PUBLISH,
            Action.SURVEY_EXPORT,
            Action.RESPONSE_DELETE,
            Action.MEMBERS_VIEW,
        }
    ),
    Role.OWNER: frozenset(Action),
}


@dataclass(frozen=True)
class Actor:
    """Who is acting. Build it fresh per request from the repos
    (`AuthService.actor`), so role changes apply immediately."""

    user_id: str
    roles: Mapping[str, Role | str] = field(default_factory=dict)  # tenant_id -> role

    @classmethod
    def from_memberships(cls, user_id: str, memberships: list[Membership]) -> Actor:
        return cls(
            user_id=user_id,
            roles={m.tenant_id: m.role for m in memberships if m.user_id == user_id},
        )


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
