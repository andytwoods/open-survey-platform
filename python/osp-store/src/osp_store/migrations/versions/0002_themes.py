"""theme library: themes + lab_theme_defaults (R8; additive)

Revision ID: 0002_themes
Revises: 0001
Create Date: 2026-10-16

Additive only: two new tables, nothing existing changes. If another 0002 lands first,
re-point ``down_revision`` at it; the tables don't depend on anything after 0001.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Frozen copy of the schema's JSON type: a migration must not change when osp_store.schema does.
JSON_T = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

revision = "0002_themes"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "themes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("body", JSON_T, nullable=False),
        sa.Column("created_by", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=80), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("name <> ''", name=op.f("ck_themes_name_not_empty")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_themes_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_themes")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_themes_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "name", name=op.f("uq_themes_tenant_id_name")),
    )
    with op.batch_alter_table("themes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_themes_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "lab_theme_defaults",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("theme_id", sa.String(length=36), nullable=False),
        sa.Column("set_by", sa.String(length=80), nullable=False),
        sa.Column("set_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "theme_id"],
            ["themes.tenant_id", "themes.id"],
            name=op.f("fk_lab_theme_defaults_tenant_id_theme_id_themes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_lab_theme_defaults_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_lab_theme_defaults")),
    )


def downgrade() -> None:
    op.drop_table("lab_theme_defaults")
    with op.batch_alter_table("themes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_themes_tenant_id"))
    op.drop_table("themes")
