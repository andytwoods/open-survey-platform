"""participant runtime: publications, runtime sessions, quotas, balanced assignment

Additive only (task R2): new tables, no change to the 0001 tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Frozen copies of the schema's column types (see 0001).
JSON_T = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)
ID = sa.String(length=36)

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SAVE_MODE = "save_mode IN ('every-page', 'end-only')"


def _index(table: str, *columns: str) -> None:
    with op.batch_alter_table(table, schema=None) as batch_op:
        for col in columns:
            batch_op.create_index(batch_op.f(f"ix_{table}_{col}"), [col], unique=False)


def upgrade() -> None:
    op.create_table(
        "publications",
        sa.Column("id", ID, nullable=False),
        sa.Column("tenant_id", ID, nullable=False),
        sa.Column("version_id", ID, nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("plan", sa.Text(), nullable=False),
        sa.Column("plan_checksum", sa.String(length=128), nullable=False),
        sa.Column("save_mode", sa.String(length=16), nullable=False),
        sa.Column("config", JSON_T, nullable=False),
        sa.Column("published_by", sa.String(length=80), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("closed_at", TS, nullable=True),
        sa.CheckConstraint(SAVE_MODE, name=op.f("ck_publications_save_mode")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "version_id"],
            ["versions.tenant_id", "versions.id"],
            name=op.f("fk_publications_tenant_id_version_id_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publications")),
        sa.UniqueConstraint("slug", name=op.f("uq_publications_slug")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_publications_tenant_id_id")),
    )
    _index("publications", "tenant_id", "version_id")

    op.create_table(
        "assignment_counters",
        sa.Column("publication_id", ID, nullable=False),
        sa.Column("variable", sa.String(length=200), nullable=False),
        sa.Column("level", sa.String(length=200), nullable=False),
        sa.Column("tenant_id", ID, nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.CheckConstraint("count >= 0", name=op.f("ck_assignment_counters_count_nonneg")),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.id"],
            name=op.f("fk_assignment_counters_publication_id_publications"),
        ),
        sa.PrimaryKeyConstraint(
            "publication_id", "variable", "level", name=op.f("pk_assignment_counters")
        ),
    )
    _index("assignment_counters", "tenant_id")

    op.create_table(
        "participant_sessions",
        sa.Column("id", ID, nullable=False),
        sa.Column("tenant_id", ID, nullable=False),
        sa.Column("publication_id", ID, nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("save_mode", sa.String(length=16), nullable=False),
        sa.Column("balanced", JSON_T, nullable=False),
        sa.Column("url_params_ct", sa.LargeBinary(), nullable=True),
        sa.Column("url_params_key_id", sa.String(length=32), nullable=True),
        sa.Column("submission_checksum", sa.String(length=64), nullable=True),
        sa.Column("response_id", ID, nullable=True),
        sa.Column("last_active_at", TS, nullable=False),
        sa.Column("submitted_at", TS, nullable=True),
        sa.Column("expired_at", TS, nullable=True),
        sa.CheckConstraint(SAVE_MODE, name=op.f("ck_participant_sessions_save_mode")),
        sa.CheckConstraint("revision >= 0", name=op.f("ck_participant_sessions_revision_nonneg")),
        sa.ForeignKeyConstraint(
            ["id"],
            ["sessions.id"],
            name=op.f("fk_participant_sessions_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "publication_id"],
            ["publications.tenant_id", "publications.id"],
            name=op.f("fk_participant_sessions_tenant_id_publication_id_publications"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_participant_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_participant_sessions_token_hash")),
    )
    _index("participant_sessions", "publication_id", "tenant_id")

    op.create_table(
        "quota_claims",
        sa.Column("session_id", ID, nullable=False),
        sa.Column("node_id", sa.String(length=200), nullable=False),
        sa.Column("tenant_id", ID, nullable=False),
        sa.Column("publication_id", ID, nullable=False),
        sa.Column("quota_id", sa.String(length=200), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("at", TS, nullable=False),
        sa.Column("released_at", TS, nullable=True),
        sa.CheckConstraint("result IN ('admitted', 'full')", name=op.f("ck_quota_claims_result")),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_quota_claims_session_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_id", "node_id", name=op.f("pk_quota_claims")),
    )
    _index("quota_claims", "tenant_id")

    op.create_table(
        "quota_counters",
        sa.Column("publication_id", ID, nullable=False),
        sa.Column("quota_id", sa.String(length=200), nullable=False),
        sa.Column("tenant_id", ID, nullable=False),
        sa.Column("cap", sa.Integer(), nullable=False),
        sa.Column("used", sa.Integer(), nullable=False),
        sa.CheckConstraint("cap >= 0", name=op.f("ck_quota_counters_cap_nonneg")),
        sa.CheckConstraint(
            "used >= 0 AND used <= cap", name=op.f("ck_quota_counters_used_in_range")
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.id"],
            name=op.f("fk_quota_counters_publication_id_publications"),
        ),
        sa.PrimaryKeyConstraint("publication_id", "quota_id", name=op.f("pk_quota_counters")),
    )
    _index("quota_counters", "tenant_id")

    op.create_table(
        "session_conflicts",
        sa.Column("id", ID, nullable=False),
        sa.Column("tenant_id", ID, nullable=False),
        sa.Column("session_id", ID, nullable=False),
        sa.Column("base_revision", sa.Integer(), nullable=False),
        sa.Column("server_revision", sa.Integer(), nullable=False),
        sa.Column("snapshot_ct", sa.LargeBinary(), nullable=False),
        sa.Column("snapshot_key_id", sa.String(length=32), nullable=False),
        sa.Column("at", TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_session_conflicts_session_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_session_conflicts")),
    )
    _index("session_conflicts", "session_id", "tenant_id")

    op.create_table(
        "response_records",
        sa.Column("id", ID, nullable=False),
        sa.Column("tenant_id", ID, nullable=False),
        sa.Column("record_ct", sa.LargeBinary(), nullable=False),
        sa.Column("record_key_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["id"],
            ["responses.id"],
            name=op.f("fk_response_records_id_responses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_response_records")),
    )
    _index("response_records", "tenant_id")


def downgrade() -> None:
    for table in (
        "response_records",
        "session_conflicts",
        "quota_counters",
        "quota_claims",
        "participant_sessions",
        "assignment_counters",
        "publications",
    ):
        op.drop_table(table)  # drops its indexes too
