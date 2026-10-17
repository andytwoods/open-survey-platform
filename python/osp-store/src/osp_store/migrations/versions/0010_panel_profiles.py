"""property panel profiles: panel_profiles (task B21)

Revision ID: 0010_panel_profiles
Revises: 0009_results_layouts
Create Date: 2026-10-17

planning/property-profiles.md §3: one profile per lab saying which properties researchers
see in the builder's property panel, their order, group headings, defaults for new
questions and the lab's custom properties. ``body`` is opaque JSON validated by osp-spec's
profile model; no row means the stock panel. Additive only; the downgrade drops the table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Frozen copies of the column types (see 0001).
JSON_T = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)
ID = sa.String(length=36)

revision = "0010_panel_profiles"
down_revision = "0009_results_layouts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "panel_profiles",
        sa.Column("tenant_id", ID, nullable=False),
        sa.Column("body", JSON_T, nullable=False),
        sa.Column("updated_by", sa.String(length=80), nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_panel_profiles_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_panel_profiles")),
    )


def downgrade() -> None:
    op.drop_table("panel_profiles")
