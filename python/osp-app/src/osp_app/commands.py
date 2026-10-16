"""App commands: the registry for app actions (AGENTS.md rule 2), alongside the survey
op registry in osp-ops. UI, CLI and MCP dispatch both by id.

A command is an id, a label, the permission it needs and a function
``fn(service, actor, **params)``. Every command checks ``can()`` itself (the resource
is only known once the survey is located), and ``dispatch`` refuses anything that is
not an authenticated ``Actor`` before the command runs: fail closed twice.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .auth.permissions import Action, Actor
from .errors import InvalidRequest, Unauthenticated


@dataclass(frozen=True)
class AppCommand:
    id: str
    label: str
    action: Action
    fn: Callable[..., Any]


COMMANDS: dict[str, AppCommand] = {}


def command(
    command_id: str, *, label: str, action: Action
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        if command_id in COMMANDS:
            raise RuntimeError(f"app command {command_id!r} registered twice")
        COMMANDS[command_id] = AppCommand(command_id, label, action, fn)
        return fn

    return deco


def dispatch(service: object, command_id: object, actor: object, **params: Any) -> Any:
    if not isinstance(actor, Actor):
        raise Unauthenticated("Sign in first.")
    spec = COMMANDS.get(command_id) if isinstance(command_id, str) else None
    if spec is None:
        raise InvalidRequest(f"no app command {str(command_id)[:60]!r}")
    return spec.fn(service, actor, **params)
