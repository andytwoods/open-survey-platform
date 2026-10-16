"""Database schema (SQLAlchemy Core). Alembic migrations must match this exactly
(``tests/test_migrations.py`` compares them).

Conventions
- Ids are app-generated UUID strings, so encrypted columns can bind their row id
  into the AEAD associated data before the row is inserted.
- Every tenant-owned table carries ``tenant_id``. Child rows reference parents by
  the composite ``(tenant_id, id)``, so the database itself refuses a row that
  points at another tenant's parent.
- Survey JSON is opaque: drafts hold it as JSON, published versions as canonical
  text (so the checksum stays verifiable byte for byte on every backend).
- Encrypted columns are ``<name>_ct`` (ciphertext) + ``<name>_key_id``.
- No IP address, user agent or other network identifier is stored
  (``tests/test_privacy.py`` asserts this).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING)

ID = String(36)
JsonType = JSON().with_variant(JSONB(), "postgresql")
SerialId = BigInteger().with_variant(Integer(), "sqlite")


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC on the way in and out, on every backend."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime; the store only accepts timezone-aware values")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _ts(name: str, nullable: bool = False) -> Column:
    return Column(name, UTCDateTime(), nullable=nullable)


tenants = Table(
    "tenants",
    metadata,
    Column("id", ID, primary_key=True),
    Column("name", String(200), nullable=False),
    _ts("created_at"),
)

users = Table(
    "users",
    metadata,
    Column("id", ID, primary_key=True),
    Column("tenant_id", ID, ForeignKey("tenants.id"), nullable=False, index=True),
    Column("email", String(320), nullable=False, unique=True),  # stored lower-cased
    Column("password_hash", Text, nullable=True),  # opaque to the store (C10a hashes)
    Column("totp_secret_ct", LargeBinary, nullable=True),
    Column("totp_secret_key_id", String(32), nullable=True),
    Column("role", String(32), nullable=False),
    Column("failed_logins", Integer, nullable=False, server_default="0"),
    _ts("locked_until", nullable=True),
    _ts("created_at"),
    UniqueConstraint("tenant_id", "id"),
    CheckConstraint("role <> ''", name="role_not_empty"),
)

surveys = Table(
    "surveys",
    metadata,
    Column("id", ID, primary_key=True),
    Column("tenant_id", ID, ForeignKey("tenants.id"), nullable=False, index=True),
    Column("title", String(500), nullable=False),
    Column("created_by", String(80), nullable=False),
    _ts("created_at"),
    _ts("closed_at", nullable=True),
    # Retention policy: none | days_after_close (retention_days) | after_date (retention_until)
    Column("retention_kind", String(20), nullable=False, server_default="none"),
    Column("retention_days", Integer, nullable=True),
    _ts("retention_until", nullable=True),
    UniqueConstraint("tenant_id", "id"),
    CheckConstraint(
        "retention_kind IN ('none', 'days_after_close', 'after_date')", name="retention_kind"
    ),
    CheckConstraint(
        "(retention_kind <> 'days_after_close') OR "
        "(retention_days IS NOT NULL AND retention_days >= 0)",
        name="retention_days",
    ),
    CheckConstraint(
        "(retention_kind <> 'after_date') OR (retention_until IS NOT NULL)",
        name="retention_until",
    ),
)

drafts = Table(
    "drafts",
    metadata,
    Column("survey_id", ID, primary_key=True),
    Column("tenant_id", ID, nullable=False, index=True),
    Column("revision", Integer, nullable=False),
    Column("body", JsonType, nullable=False),
    Column("updated_by", String(80), nullable=False),
    _ts("updated_at"),
    ForeignKeyConstraint(
        ["tenant_id", "survey_id"], ["surveys.tenant_id", "surveys.id"], ondelete="CASCADE"
    ),
    CheckConstraint("revision >= 0", name="revision_nonneg"),
)

# Op log: one row per op. A transaction (one user gesture, the undo unit) is the
# set of rows sharing txn_id; they all land at the same resulting revision.
op_log = Table(
    "op_log",
    metadata,
    Column("id", SerialId, primary_key=True, autoincrement=True),
    Column("tenant_id", ID, nullable=False, index=True),
    Column("survey_id", ID, nullable=False),
    Column("revision", Integer, nullable=False),  # draft revision this op produced
    Column("seq", Integer, nullable=False),  # order within the transaction
    Column("txn_id", ID, nullable=False),
    Column("op_id", String(200), nullable=False),
    Column("params", JsonType, nullable=False),
    Column("inverse", JsonType, nullable=False),
    Column("actor", String(80), nullable=False),
    _ts("at"),
    ForeignKeyConstraint(
        ["tenant_id", "survey_id"], ["surveys.tenant_id", "surveys.id"], ondelete="CASCADE"
    ),
    UniqueConstraint("survey_id", "revision", "seq"),
)

versions = Table(
    "versions",
    metadata,
    Column("id", ID, primary_key=True),
    Column("tenant_id", ID, nullable=False, index=True),
    Column("survey_id", ID, nullable=False),
    Column("number", Integer, nullable=False),
    Column("checksum", String(64), nullable=False),  # sha256 hex of `body`
    Column("body", Text, nullable=False),  # canonical JSON text
    Column("xform", LargeBinary, nullable=False),
    Column("meta", JsonType, nullable=False),  # tool versions (pyxform, Enketo, ...)
    Column("published_by", String(80), nullable=False),
    _ts("published_at"),
    ForeignKeyConstraint(["tenant_id", "survey_id"], ["surveys.tenant_id", "surveys.id"]),
    UniqueConstraint("survey_id", "number"),
    UniqueConstraint("tenant_id", "id"),
    CheckConstraint("number >= 1", name="number_positive"),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id", ID, primary_key=True),
    Column("tenant_id", ID, nullable=False, index=True),
    Column("version_id", ID, nullable=False, index=True),
    Column("session_seed", BigInteger, nullable=False),
    Column("assigned_conditions", JsonType, nullable=False),
    Column("realised_orders", JsonType, nullable=False),
    Column("current_page", String(200), nullable=True),
    Column("instance_ct", LargeBinary, nullable=True),  # autosaved XForm instance
    Column("instance_key_id", String(32), nullable=True),
    _ts("started_at"),
    _ts("updated_at"),
    _ts("completed_at", nullable=True),
    ForeignKeyConstraint(["tenant_id", "version_id"], ["versions.tenant_id", "versions.id"]),
    CheckConstraint("session_seed > 0", name="seed_positive"),
)

responses = Table(
    "responses",
    metadata,
    Column("id", ID, primary_key=True),
    Column("tenant_id", ID, nullable=False, index=True),
    Column("version_id", ID, nullable=False, index=True),
    Column("version_checksum", String(64), nullable=False),
    Column("session_id", ID, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True),
    Column("allocation_mode", String(32), nullable=False),
    Column("session_seed", BigInteger, nullable=True),
    Column("assigned_conditions", JsonType, nullable=False),
    Column("realised_orders", JsonType, nullable=False),
    Column("engine_version", String(64), nullable=True),
    Column("answers_ct", LargeBinary, nullable=False),  # {var: {"state", "value"}}
    Column("answers_key_id", String(32), nullable=False),
    _ts("started_at", nullable=True),
    _ts("submitted_at"),
    ForeignKeyConstraint(["tenant_id", "version_id"], ["versions.tenant_id", "versions.id"]),
    CheckConstraint("allocation_mode IN ('server', 'limesurvey-native')", name="allocation_mode"),
    CheckConstraint("session_seed IS NULL OR session_seed > 0", name="seed_positive"),
)

audit_log = Table(
    "audit_log",
    metadata,
    Column("id", SerialId, primary_key=True, autoincrement=True),
    Column("tenant_id", ID, ForeignKey("tenants.id"), nullable=True),  # NULL: system-wide
    Column("actor", String(80), nullable=False),
    Column("action", String(80), nullable=False),
    Column("target_type", String(40), nullable=True),
    Column("target_id", String(80), nullable=True),
    Column("detail", JsonType, nullable=False),  # never participant data
    _ts("at"),
    Index("ix_audit_log_tenant_at", "tenant_id", "at"),
)

#: (table, ciphertext column, key-id column) for every encrypted field.
ENCRYPTED_FIELDS: tuple[tuple[Table, str, str], ...] = (
    (users, "totp_secret_ct", "totp_secret_key_id"),
    (sessions, "instance_ct", "instance_key_id"),
    (responses, "answers_ct", "answers_key_id"),
)
