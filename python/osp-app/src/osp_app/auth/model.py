"""Auth domain model: User, Tenant, Membership, Session.

All records are frozen; repositories store and return copies, and changes go
through `dataclasses.replace` + `repo.update`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Role(StrEnum):
    """Tenant-level roles (MVP). Survey-level sharing can add per-survey grants
    later without changing these: `permissions.can` resolves an effective role."""

    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class SessionStage(StrEnum):
    FULL = "full"  # authenticated
    MFA_PENDING = "mfa_pending"  # password ok, waiting for TOTP / recovery code


@dataclass(frozen=True, slots=True)
class User:
    id: str
    email: str  # normalised (see `normalise_email`)
    password_hash: str
    created_at: datetime
    # TOTP. `totp_secret` is set once enrolment is confirmed.
    totp_secret: str | None = None
    totp_pending_secret: str | None = None
    totp_last_step: int | None = None  # replay guard: highest accepted time step
    recovery_code_hashes: tuple[str, ...] = ()
    # Lockout / backoff.
    failed_logins: int = 0
    locked_until: datetime | None = None

    @property
    def totp_enrolled(self) -> bool:
        return self.totp_secret is not None


@dataclass(frozen=True, slots=True)
class Tenant:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Membership:
    user_id: str
    tenant_id: str
    role: Role | str  # str allowed so unknown roles from storage fail closed, not crash


@dataclass(frozen=True, slots=True)
class Session:
    """A server-side session. `id` is the SHA-256 of the opaque token; the token
    itself is never stored."""

    id: str
    user_id: str
    stage: SessionStage
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime  # absolute expiry


def normalise_email(email: str) -> str:
    return email.strip().lower()
