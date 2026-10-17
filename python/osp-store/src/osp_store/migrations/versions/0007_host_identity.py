"""host-owned sign-in: drop our accounts, add principals (plan P)

Revision ID: 0007_host_identity
Revises: 0006_consent
Create Date: 2026-10-17

planning/pages-split.md D5: a host owns researcher accounts, passwords, two-factor and
sessions. This drops ``auth_sessions``, ``user_mfa`` and ``users`` (which held the
passwords, TOTP secrets, lockout counters and the one-lab membership role), and adds:

- ``principals``: one row per host user id (last display name, first/last seen), for
  display and audit only;
- ``audit_log.actor_name``: the actor's display name when the row was written.

No production data exists yet, so nothing is carried over. The downgrade recreates the
three tables empty (as 0001 and 0004 made them) and drops the additions.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Frozen copies of the column types (see 0001).
JSON_T = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)
ID = sa.String(length=36)

revision = "0007_host_identity"
down_revision = "0006_consent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("auth_sessions")  # its index goes with it
    op.drop_table("user_mfa")
    op.drop_table("users")
    op.create_table(
        "principals",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("first_seen_at", TS, nullable=False),
        sa.Column("last_seen_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_principals")),
    )
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.add_column(sa.Column("actor_name", sa.String(length=200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.drop_column("actor_name")
    op.drop_table("principals")
    op.create_table(
        "users",
        sa.Column("id", ID, nullable=False),
        sa.Column("tenant_id", ID, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("totp_secret_ct", sa.LargeBinary(), nullable=True),
        sa.Column("totp_secret_key_id", sa.String(length=32), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("failed_logins", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
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
