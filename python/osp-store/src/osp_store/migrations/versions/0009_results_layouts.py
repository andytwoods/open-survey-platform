"""saved results layouts: results_layouts + results_layout_defaults (plan V, V-D9)

Revision ID: 0009_results_layouts
Revises: 0008_identity_nonces
Create Date: 2026-10-17

planning/results-viewer.md V-D9: a survey's saved results-page layouts (chart choice per
question, filters, split, denominator, order, hidden cards, bins, captions), shared by the
lab and edited by owners and editors. ``settings`` is opaque JSON validated by osp-app's
layout schema; it never holds response data. ``results_layout_defaults`` keeps at most one
default per survey, pointing (composite foreign key) at one of that survey's own layouts.
Additive only; the downgrade drops both tables.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Frozen copies of the column types (see 0001).
JSON_T = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)
ID = sa.String(length=36)

revision = "0009_results_layouts"
down_revision = "0008_identity_nonces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "results_layouts",
        sa.Column("id", ID, nullable=False),
        sa.Column("tenant_id", ID, nullable=False),
        sa.Column("survey_id", ID, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("settings", JSON_T, nullable=False),
        sa.Column("created_by", sa.String(length=80), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_by", sa.String(length=80), nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.CheckConstraint("name <> ''", name=op.f("ck_results_layouts_name_not_empty")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "survey_id"],
            ["surveys.tenant_id", "surveys.id"],
            name=op.f("fk_results_layouts_tenant_id_survey_id_surveys"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_results_layouts")),
        sa.UniqueConstraint("survey_id", "id", name=op.f("uq_results_layouts_survey_id_id")),
        sa.UniqueConstraint("survey_id", "name", name=op.f("uq_results_layouts_survey_id_name")),
    )
    with op.batch_alter_table("results_layouts", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_results_layouts_tenant_id"), ["tenant_id"], unique=False
        )

    op.create_table(
        "results_layout_defaults",
        sa.Column("survey_id", ID, nullable=False),
        sa.Column("tenant_id", ID, nullable=False),
        sa.Column("layout_id", ID, nullable=False),
        sa.Column("set_by", sa.String(length=80), nullable=False),
        sa.Column("set_at", TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "survey_id"],
            ["surveys.tenant_id", "surveys.id"],
            name=op.f("fk_results_layout_defaults_tenant_id_survey_id_surveys"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["survey_id", "layout_id"],
            ["results_layouts.survey_id", "results_layouts.id"],
            name=op.f("fk_results_layout_defaults_survey_id_layout_id_results_layouts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("survey_id", name=op.f("pk_results_layout_defaults")),
    )
    with op.batch_alter_table("results_layout_defaults", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_results_layout_defaults_tenant_id"), ["tenant_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("results_layout_defaults", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_results_layout_defaults_tenant_id"))
    op.drop_table("results_layout_defaults")
    with op.batch_alter_table("results_layouts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_results_layouts_tenant_id"))
    op.drop_table("results_layouts")
