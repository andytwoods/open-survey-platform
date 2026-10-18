"""Plain, immutable records returned by the store (no SQLAlchemy objects leak out)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from .retention import RetentionPolicy

AllocationMode = Literal["server", "limesurvey-native"]
ANSWER_STATES = frozenset({"answered", "unanswered", "irrelevant", "not-reached"})  # semantics §1


@dataclass(frozen=True, slots=True)
class Tenant:
    id: str
    name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Principal:
    """A researcher as the host names them (plan P: the host owns accounts). Only for
    display and audit: roles come from the host on every request, never from here."""

    id: str  # the host's opaque user id
    display_name: str | None
    first_seen_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True, slots=True)
class Survey:
    id: str
    tenant_id: str
    title: str
    created_by: str
    created_at: datetime
    closed_at: datetime | None
    retention: RetentionPolicy
    public_slug: str | None = None  # the participant link id, /s/<public_slug>


@dataclass(frozen=True, slots=True)
class Draft:
    survey_id: str
    revision: int
    body: Any  # opaque survey JSON (osp-spec validates it, not us)
    updated_by: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class OpRecord:
    """One op as the op log stores it. All three fields are opaque JSON to the store."""

    op_id: str
    params: Any
    inverse: Any


@dataclass(frozen=True, slots=True)
class OpLogEntry:
    survey_id: str
    revision: int
    seq: int
    txn_id: str
    op_id: str
    params: Any
    inverse: Any
    actor: str
    at: datetime


@dataclass(frozen=True, slots=True)
class Version:
    id: str
    survey_id: str
    number: int
    checksum: str
    body: Any
    xform: bytes
    meta: Any
    published_by: str
    published_at: datetime


@dataclass(frozen=True, slots=True)
class Session:
    id: str
    version_id: str
    session_seed: int
    assigned_conditions: Any
    realised_orders: dict[str, Any]
    current_page: str | None
    instance: Any  # decrypted autosaved instance, or None
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class Response:
    id: str
    version_id: str
    version_checksum: str
    session_id: str | None
    allocation_mode: AllocationMode
    session_seed: int | None
    assigned_conditions: Any
    realised_orders: Any
    engine_version: str | None
    answers: dict[str, dict[str, Any]]  # {var: {"state": ..., "value": ...}}
    started_at: datetime | None
    submitted_at: datetime
    # The end outcome copied out of the record at submit (migration 0011); None when the
    # response has no record or was stored before the column existed (not backfilled).
    outcome: str | None = None


@dataclass(frozen=True, slots=True)
class AuditEntry:
    id: int
    tenant_id: str | None
    actor: str
    action: str
    target_type: str | None
    target_id: str | None
    detail: Any
    at: datetime
    actor_name: str | None = None  # display name snapshot when written (migration 0007)
