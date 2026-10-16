"""builder accounts: user_mfa + auth_sessions (C10; additive)

Revision ID: 0004_accounts
Revises: 0003
Create Date: 2026-10-16

Additive only: two new tables, nothing existing changes. They back the store-backed
UserRepo/SessionRepo in osp-app (researcher sign-in, not participant sessions).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Frozen copies of the schema's column types (see 0001).
JSON_T = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)
ID = sa.String(length=36)

revision = "0004_accounts"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_mfa",
        sa.Column("id", ID, nullable=False),
        sa.Column("totp_pending_ct", sa.LargeBinary(), nullable=True),
        sa.Column("totp_pending_key_id", sa.String(length=32), nullable=True),
        sa.Column("totp_last_step", sa.BigInteger(), nullable=True),
        sa.Column("recovery_code_hashes", JSON_T, nullable=False),
        sa.ForeignKeyConstraint(
            ["id"], ["users.id"], name=op.f("fk_user_mfa_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_mfa")),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", ID, nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("last_seen_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.CheckConstraint("stage IN ('full', 'mfa_pending')", name=op.f("ck_auth_sessions_stage")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
    )
    with op.batch_alter_table("auth_sessions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_auth_sessions_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_table("auth_sessions")  # drops its index too
    op.drop_table("user_mfa")
