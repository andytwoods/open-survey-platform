"""responses.outcome: the end outcome as a plain column (task EN4)

Revision ID: 0011_response_outcome
Revises: 0010_panel_profiles
Create Date: 2026-10-18

planning/end-of-survey.md §4.5: the outcome a session ended with (`complete`,
`screened_out`, `quota_full`, ...) is copied out of the encrypted record at submit, so the
results page can count responses per outcome and filter on it without decrypting. Indexed
with ``version_id``. Existing rows stay NULL until ``osp-cli backfill-outcomes`` reads their
records once; a row without a record (no engine record stored) stays NULL for good.
Additive only; the downgrade drops the index and the column.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_response_outcome"
down_revision = "0010_panel_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("responses", schema=None) as batch_op:
        batch_op.add_column(sa.Column("outcome", sa.String(length=80), nullable=True))
        batch_op.create_index(
            "ix_responses_version_outcome", ["version_id", "outcome"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("responses", schema=None) as batch_op:
        batch_op.drop_index("ix_responses_version_outcome")
        batch_op.drop_column("outcome")
