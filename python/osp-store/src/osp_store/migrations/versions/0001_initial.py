"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Frozen copies of the schema's column types: a migration must not change when
# osp_store.schema does.
JSON_T = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
SERIAL_T = sa.BigInteger().with_variant(sa.Integer(), "sqlite")

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", SERIAL_T, autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=True),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=True),
        sa.Column("target_id", sa.String(length=80), nullable=True),
        sa.Column("detail", JSON_T, nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_audit_log_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.create_index("ix_audit_log_tenant_at", ["tenant_id", "at"], unique=False)

    op.create_table(
        "surveys",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("created_by", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retention_kind", sa.String(length=20), server_default="none", nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(retention_kind <> 'after_date') OR (retention_until IS NOT NULL)",
            name=op.f("ck_surveys_retention_until"),
        ),
        sa.CheckConstraint(
            "(retention_kind <> 'days_after_close') OR "
            "(retention_days IS NOT NULL AND retention_days >= 0)",
            name=op.f("ck_surveys_retention_days"),
        ),
        sa.CheckConstraint(
            "retention_kind IN ('none', 'days_after_close', 'after_date')",
            name=op.f("ck_surveys_retention_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_surveys_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_surveys")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_surveys_tenant_id_id")),
    )
    with op.batch_alter_table("surveys", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_surveys_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("totp_secret_ct", sa.LargeBinary(), nullable=True),
        sa.Column("totp_secret_key_id", sa.String(length=32), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("failed_logins", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role <> ''", name=op.f("ck_users_role_not_empty")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_users_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_users_tenant_id_id")),
    )
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_users_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "drafts",
        sa.Column("survey_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("body", JSON_T, nullable=False),
        sa.Column("updated_by", sa.String(length=80), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision >= 0", name=op.f("ck_drafts_revision_nonneg")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "survey_id"],
            ["surveys.tenant_id", "surveys.id"],
            name=op.f("fk_drafts_tenant_id_survey_id_surveys"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("survey_id", name=op.f("pk_drafts")),
    )
    with op.batch_alter_table("drafts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_drafts_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "op_log",
        sa.Column("id", SERIAL_T, autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("survey_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("txn_id", sa.String(length=36), nullable=False),
        sa.Column("op_id", sa.String(length=200), nullable=False),
        sa.Column("params", JSON_T, nullable=False),
        sa.Column("inverse", JSON_T, nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "survey_id"],
            ["surveys.tenant_id", "surveys.id"],
            name=op.f("fk_op_log_tenant_id_survey_id_surveys"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_op_log")),
        sa.UniqueConstraint(
            "survey_id", "revision", "seq", name=op.f("uq_op_log_survey_id_revision_seq")
        ),
    )
    with op.batch_alter_table("op_log", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_op_log_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("survey_id", sa.String(length=36), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("xform", sa.LargeBinary(), nullable=False),
        sa.Column("meta", JSON_T, nullable=False),
        sa.Column("published_by", sa.String(length=80), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("number >= 1", name=op.f("ck_versions_number_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "survey_id"],
            ["surveys.tenant_id", "surveys.id"],
            name=op.f("fk_versions_tenant_id_survey_id_surveys"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_versions")),
        sa.UniqueConstraint("survey_id", "number", name=op.f("uq_versions_survey_id_number")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_versions_tenant_id_id")),
    )
    with op.batch_alter_table("versions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_versions_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("version_id", sa.String(length=36), nullable=False),
        sa.Column("session_seed", sa.BigInteger(), nullable=False),
        sa.Column("assigned_conditions", JSON_T, nullable=False),
        sa.Column("realised_orders", JSON_T, nullable=False),
        sa.Column("current_page", sa.String(length=200), nullable=True),
        sa.Column("instance_ct", sa.LargeBinary(), nullable=True),
        sa.Column("instance_key_id", sa.String(length=32), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("session_seed > 0", name=op.f("ck_sessions_seed_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "version_id"],
            ["versions.tenant_id", "versions.id"],
            name=op.f("fk_sessions_tenant_id_version_id_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
    )
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_sessions_tenant_id"), ["tenant_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_sessions_version_id"), ["version_id"], unique=False)

    op.create_table(
        "responses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("version_id", sa.String(length=36), nullable=False),
        sa.Column("version_checksum", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("allocation_mode", sa.String(length=32), nullable=False),
        sa.Column("session_seed", sa.BigInteger(), nullable=True),
        sa.Column("assigned_conditions", JSON_T, nullable=False),
        sa.Column("realised_orders", JSON_T, nullable=False),
        sa.Column("engine_version", sa.String(length=64), nullable=True),
        sa.Column("answers_ct", sa.LargeBinary(), nullable=False),
        sa.Column("answers_key_id", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "allocation_mode IN ('server', 'limesurvey-native')",
            name=op.f("ck_responses_allocation_mode"),
        ),
        sa.CheckConstraint(
            "session_seed IS NULL OR session_seed > 0", name=op.f("ck_responses_seed_positive")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_responses_session_id_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "version_id"],
            ["versions.tenant_id", "versions.id"],
            name=op.f("fk_responses_tenant_id_version_id_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_responses")),
    )
    with op.batch_alter_table("responses", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_responses_tenant_id"), ["tenant_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_responses_version_id"), ["version_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("responses", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_responses_version_id"))
        batch_op.drop_index(batch_op.f("ix_responses_tenant_id"))

    op.drop_table("responses")
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_sessions_version_id"))
        batch_op.drop_index(batch_op.f("ix_sessions_tenant_id"))

    op.drop_table("sessions")
    with op.batch_alter_table("versions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_versions_tenant_id"))

    op.drop_table("versions")
    with op.batch_alter_table("op_log", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_op_log_tenant_id"))

    op.drop_table("op_log")
    with op.batch_alter_table("drafts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_drafts_tenant_id"))

    op.drop_table("drafts")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_tenant_id"))

    op.drop_table("users")
    with op.batch_alter_table("surveys", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_surveys_tenant_id"))

    op.drop_table("surveys")
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.drop_index("ix_audit_log_tenant_at")

    op.drop_table("audit_log")
    op.drop_table("tenants")
