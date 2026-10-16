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

# --- Participant runtime (task R2, planning/runtime-design.md §5) -------------------
# Additions only: the tables above are unchanged. Every row below that holds
# participant data hangs off `sessions` / `responses` with ON DELETE CASCADE, so
# withdrawal (`delete_session`, `delete_response`) and retention remove it too.

# A published survey link: slug -> one version + its runtime plan (opaque JSON).
publications = Table(
    "publications",
    metadata,
    Column("id", ID, primary_key=True),
    Column("tenant_id", ID, nullable=False, index=True),
    Column("version_id", ID, nullable=False, index=True),
    Column("slug", String(80), nullable=False, unique=True),
    Column("plan", Text, nullable=False),  # canonical JSON text of the runtime plan
    Column("plan_checksum", String(128), nullable=False),
    Column("save_mode", String(16), nullable=False),
    Column("config", JsonType, nullable=False),  # assignment + quota config, no participant data
    Column("published_by", String(80), nullable=False),
    _ts("created_at"),
    _ts("closed_at", nullable=True),
    ForeignKeyConstraint(["tenant_id", "version_id"], ["versions.tenant_id", "versions.id"]),
    UniqueConstraint("tenant_id", "id"),
    CheckConstraint("save_mode IN ('every-page', 'end-only')", name="save_mode"),
)

# 1:1 extension of `sessions` for runtime sessions (id = sessions.id). The resume
# token is stored only as its SHA-256; the snapshot lives in sessions.instance_ct.
participant_sessions = Table(
    "participant_sessions",
    metadata,
    Column("id", ID, ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True),
    Column("tenant_id", ID, nullable=False, index=True),
    Column("publication_id", ID, nullable=False, index=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("revision", Integer, nullable=False),
    Column("save_mode", String(16), nullable=False),
    Column("balanced", JsonType, nullable=False),  # {variable: level key} counted at start
    Column("url_params_ct", LargeBinary, nullable=True),
    Column("url_params_key_id", String(32), nullable=True),
    Column("submission_checksum", String(64), nullable=True),
    Column("response_id", ID, nullable=True),
    _ts("last_active_at"),
    _ts("submitted_at", nullable=True),
    _ts("expired_at", nullable=True),
    ForeignKeyConstraint(
        ["tenant_id", "publication_id"], ["publications.tenant_id", "publications.id"]
    ),
    CheckConstraint("revision >= 0", name="revision_nonneg"),
    CheckConstraint("save_mode IN ('every-page', 'end-only')", name="save_mode"),
)

# Atomic quota counters, one per (publication, quota). `used` never exceeds `cap`.
quota_counters = Table(
    "quota_counters",
    metadata,
    Column("publication_id", ID, ForeignKey("publications.id"), primary_key=True),
    Column("quota_id", String(200), primary_key=True),
    Column("tenant_id", ID, nullable=False, index=True),
    Column("cap", Integer, nullable=False),
    Column("used", Integer, nullable=False),
    CheckConstraint("cap >= 0", name="cap_nonneg"),
    CheckConstraint("used >= 0 AND used <= cap", name="used_in_range"),
)

# One recorded quota result per (session, quotaCheck node): repeat calls return it.
quota_claims = Table(
    "quota_claims",
    metadata,
    Column("session_id", ID, ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True),
    Column("node_id", String(200), primary_key=True),
    Column("tenant_id", ID, nullable=False, index=True),
    Column("publication_id", ID, nullable=False),
    Column("quota_id", String(200), nullable=False),
    Column("result", String(16), nullable=False),
    _ts("at"),
    _ts("released_at", nullable=True),
    CheckConstraint("result IN ('admitted', 'full')", name="result"),
)

# Balanced-assignment counters, one per (publication, variable, level).
assignment_counters = Table(
    "assignment_counters",
    metadata,
    Column("publication_id", ID, ForeignKey("publications.id"), primary_key=True),
    Column("variable", String(200), primary_key=True),
    Column("level", String(200), primary_key=True),  # canonical JSON of the level
    Column("tenant_id", ID, nullable=False, index=True),
    Column("count", Integer, nullable=False),
    CheckConstraint("count >= 0", name="count_nonneg"),
)

# Decision R-2: on a two-device conflict the server copy wins; the losing snapshot is
# kept here (encrypted), and the audit log records only that it happened.
session_conflicts = Table(
    "session_conflicts",
    metadata,
    Column("id", ID, primary_key=True),
    Column("tenant_id", ID, nullable=False, index=True),
    Column(
        "session_id", ID, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    ),
    Column("base_revision", Integer, nullable=False),
    Column("server_revision", Integer, nullable=False),
    Column("snapshot_ct", LargeBinary, nullable=False),
    Column("snapshot_key_id", String(32), nullable=False),
    _ts("at"),
)

# The full submitted ResponseRecord (event log, paradata, URL parameters, ...), beside
# the `responses` row that holds the answers (id = responses.id).
response_records = Table(
    "response_records",
    metadata,
    Column("id", ID, ForeignKey("responses.id", ondelete="CASCADE"), primary_key=True),
    Column("tenant_id", ID, nullable=False, index=True),
    Column("record_ct", LargeBinary, nullable=False),
    Column("record_key_id", String(32), nullable=False),
)

# --- Theme library (R8, migration 0002_themes) ----------------------------------------
# A lab's saved survey themes. ``body`` is opaque theme JSON (osp_spec.theme validates it).

themes = Table(
    "themes",
    metadata,
    Column("id", ID, primary_key=True),
    Column("tenant_id", ID, ForeignKey("tenants.id"), nullable=False, index=True),
    Column("name", String(200), nullable=False),
    Column("body", JsonType, nullable=False),
    Column("created_by", String(80), nullable=False),
    _ts("created_at"),
    Column("updated_by", String(80), nullable=False),
    _ts("updated_at"),
    UniqueConstraint("tenant_id", "id"),
    UniqueConstraint("tenant_id", "name"),
    CheckConstraint("name <> ''", name="name_not_empty"),
)

# At most one lab default per tenant (the primary key); it must be one of the tenant's
# own themes (composite foreign key), and deleting that theme clears the default.
lab_theme_defaults = Table(
    "lab_theme_defaults",
    metadata,
    Column("tenant_id", ID, ForeignKey("tenants.id"), primary_key=True),
    Column("theme_id", ID, nullable=False),
    Column("set_by", String(80), nullable=False),
    _ts("set_at"),
    ForeignKeyConstraint(
        ["tenant_id", "theme_id"], ["themes.tenant_id", "themes.id"], ondelete="CASCADE"
    ),
)

#: (table, ciphertext column, key-id column) for every encrypted field. The AEAD field
#: name is the ciphertext column without ``_ct``; the row id is the table's ``id``.
ENCRYPTED_FIELDS: tuple[tuple[Table, str, str], ...] = (
    (users, "totp_secret_ct", "totp_secret_key_id"),
    (sessions, "instance_ct", "instance_key_id"),
    (responses, "answers_ct", "answers_key_id"),
    (participant_sessions, "url_params_ct", "url_params_key_id"),
    (session_conflicts, "snapshot_ct", "snapshot_key_id"),
    (response_records, "record_ct", "record_key_id"),
)
