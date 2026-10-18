"""question bank: bank_items + bank_item_versions (task QB4)

Revision ID: 0012_question_bank
Revises: 0011_response_outcome
Create Date: 2026-10-18

planning/question-bank.md §3 (the plan called this 0011; EN4 took that number for
``responses.outcome``). A lab's saved bank items (a question, page or block with its
metadata: title, abbreviation, kind, tags, languages, licence class, visibility) and every
version of each: ``bank_item_versions.body`` is the whole ``osp-bank-item/0.1`` document,
validated by osp-spec in osp-app, immutable once written (its metadata keys follow the
item's). ``visibility = 'host'`` makes an item readable by every lab on the host; a delete
is soft (``deleted_at``), so surveys that inserted the item keep pointing at it.
``search_text`` is a lower-cased bag of title, abbreviation, tags and item labels for the
LIKE search. Additive only; the downgrade drops both tables.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Frozen copies of the column types (see 0001).
JSON_T = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)
ID = sa.String(length=36)

revision = "0012_question_bank"
down_revision = "0011_response_outcome"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bank_items",
        sa.Column("id", ID, nullable=False),
        sa.Column("tenant_id", ID, nullable=False),
        sa.Column("visibility", sa.String(length=16), server_default="lab", nullable=False),
        sa.Column("licence_class", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("abbreviation", sa.String(length=40), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("tags", JSON_T, nullable=False),
        sa.Column("languages", JSON_T, nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=80), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_by", sa.String(length=80), nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("deleted_at", TS, nullable=True),
        sa.CheckConstraint(
            "current_version >= 1", name=op.f("ck_bank_items_current_version_positive")
        ),
        sa.CheckConstraint(
            "kind IN ('question', 'page', 'block')", name=op.f("ck_bank_items_kind")
        ),
        sa.CheckConstraint("title <> ''", name=op.f("ck_bank_items_title_not_empty")),
        sa.CheckConstraint("visibility IN ('lab', 'host')", name=op.f("ck_bank_items_visibility")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_bank_items_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bank_items")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_bank_items_tenant_id_id")),
    )
    with op.batch_alter_table("bank_items", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_bank_items_tenant_id"), ["tenant_id"], unique=False)
        batch_op.create_index("ix_bank_items_visibility", ["visibility"], unique=False)

    op.create_table(
        "bank_item_versions",
        sa.Column("item_id", ID, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("tenant_id", ID, nullable=False),
        sa.Column("body", JSON_T, nullable=False),
        sa.Column("checksum", sa.String(length=80), nullable=False),
        sa.Column("created_by", sa.String(length=80), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.CheckConstraint("version >= 1", name=op.f("ck_bank_item_versions_version_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "item_id"],
            ["bank_items.tenant_id", "bank_items.id"],
            name=op.f("fk_bank_item_versions_tenant_id_item_id_bank_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("item_id", "version", name=op.f("pk_bank_item_versions")),
    )
    with op.batch_alter_table("bank_item_versions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_bank_item_versions_tenant_id"), ["tenant_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("bank_item_versions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_bank_item_versions_tenant_id"))
    op.drop_table("bank_item_versions")
    with op.batch_alter_table("bank_items", schema=None) as batch_op:
        batch_op.drop_index("ix_bank_items_visibility")
        batch_op.drop_index(batch_op.f("ix_bank_items_tenant_id"))
    op.drop_table("bank_items")
