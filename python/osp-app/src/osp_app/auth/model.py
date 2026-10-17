"""Auth domain model. Accounts, passwords and sessions belong to the host (plan P,
planning/pages-split.md D5); all that is left here is the role vocabulary."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """Tenant-level roles (MVP). Survey-level sharing can add per-survey grants
    later without changing these: `permissions.can` resolves an effective role.
    A host must name one of these exactly; anything else is refused."""

    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"
