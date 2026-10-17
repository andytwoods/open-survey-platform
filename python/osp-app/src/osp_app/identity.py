"""Host-supplied identity, checked (plan P, planning/pages-split.md D2, D5, D6, D12).

A host (a university's web app, a reverse proxy with single sign-on, …) authenticates the
researcher and tells osp-api who they are: an opaque user id, ``{lab id: role}`` and an
optional display name. Everything here is pure: it validates those values and builds the
:class:`~osp_app.auth.Actor` the app commands check. The HTTP side (signed headers,
in-process callables, the dev identity) lives in ``osp_api.identity``.

Rules (fail closed: a bad value refuses the whole identity, it is never trimmed):
- user ids: 1-64 characters from ``ID_CHARS``; tenant (lab) ids: 1-36 (the store's
  ``tenant_id`` width). No ``:`` (actor tags such as ``system:`` use it), no ``,`` (the
  roles header separator), no whitespace or control characters.
- roles: exactly one of :class:`~osp_app.auth.Role`'s values; at most ``MAX_LABS`` labs.
- display names: printable text, at most 200 characters after trimming; empty means none.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .auth import Actor, Role

USER_ID_MAX = 64
TENANT_ID_MAX = 36
DISPLAY_NAME_MAX = 200
MAX_LABS = 64
ID_CHARS = "A-Z a-z 0-9 . _ ~ @ + -"
_ID = re.compile(r"[A-Za-z0-9._~@+\-]+")
ROLE_NAMES = frozenset(r.value for r in Role)

# The dev identity (D12): ``make dev`` and the e2e servers act as this researcher, owner
# of the dev lab. osp-api only allows it with OSP_ENV=dev on a loopback bind.
DEV_USER_ID = "dev-researcher"
DEV_DISPLAY_NAME = "Dev researcher"
DEV_LAB_ID = "dev-lab"


class InvalidIdentity(ValueError):
    """What the host sent is malformed. The message is safe to log; never echo values."""


@dataclass(frozen=True)
class Identity:
    """Who the host says is acting: the checked actor and an optional display name."""

    actor: Actor
    display_name: str | None = None


def check_user_id(value: object) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= USER_ID_MAX or not _ID.fullmatch(value):
        raise InvalidIdentity(f"user id must be 1-{USER_ID_MAX} characters from {ID_CHARS}")
    return value


def check_tenant_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or not 0 < len(value) <= TENANT_ID_MAX
        or not _ID.fullmatch(value)
    ):
        raise InvalidIdentity(f"lab id must be 1-{TENANT_ID_MAX} characters from {ID_CHARS}")
    return value


def check_role(value: object) -> Role:
    if not isinstance(value, str) or value not in ROLE_NAMES:
        raise InvalidIdentity(f"role must be one of {', '.join(sorted(ROLE_NAMES))}")
    return Role(value)


def check_display_name(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > DISPLAY_NAME_MAX * 4:
        raise InvalidIdentity("display name must be a short string")
    text = value.strip()
    if len(text) > DISPLAY_NAME_MAX or not all(c.isprintable() for c in text):
        raise InvalidIdentity(f"display name must be printable, at most {DISPLAY_NAME_MAX} chars")
    return text or None


def make_identity(
    user_id: object,
    roles: Mapping[str, object] | Iterable[tuple[str, object]],
    display_name: object = None,
) -> Identity:
    """Check everything and build the :class:`Identity`. Raises :class:`InvalidIdentity`."""
    pairs = list(roles.items() if isinstance(roles, Mapping) else roles)
    if len(pairs) > MAX_LABS:
        raise InvalidIdentity(f"at most {MAX_LABS} labs")
    out: dict[str, Role] = {}
    for tenant_id, role in pairs:
        tid = check_tenant_id(tenant_id)
        if tid in out:
            raise InvalidIdentity("a lab is listed twice")
        out[tid] = check_role(role)
    return Identity(Actor(check_user_id(user_id), out), check_display_name(display_name))


def format_roles(roles: Mapping[str, Role | str]) -> str:
    """``{lab: role}`` as the ``X-OSP-Roles`` value: ``lab:role,…`` sorted by lab id."""
    return ",".join(f"{t}:{Role(r).value}" for t, r in sorted(roles.items()))


def parse_roles(text: str) -> list[tuple[str, str]]:
    """``lab:role,…`` -> pairs (unchecked; :func:`make_identity` checks them). Empty: none."""
    if text == "":
        return []
    pairs = []
    for part in text.split(","):
        tenant, sep, role = part.partition(":")
        if not sep:
            raise InvalidIdentity("roles must be 'lab:role' pairs separated by ','")
        pairs.append((tenant, role))
    return pairs


def dev_identity() -> Identity:
    return make_identity(DEV_USER_ID, {DEV_LAB_ID: Role.OWNER}, DEV_DISPLAY_NAME)
