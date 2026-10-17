"""shared replay ledger for signed host requests (D16)

Revision ID: 0008_identity_nonces
Revises: 0007_host_identity
Create Date: 2026-10-17

planning/pages-split.md D16: osp-api's TrustedHeaders provider refuses a reused
``X-OSP-Nonce``. In memory that only holds per process; ``identity_nonces`` lets every
worker on one database share it (``osp_store.NonceLedger``). Rows live 120 s and are
purged; nothing here is tenant or participant data. The downgrade drops the table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

TS = sa.DateTime(timezone=True)  # frozen copy (see 0001)

revision = "0008_identity_nonces"
down_revision = "0007_host_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_nonces",
        sa.Column("nonce", sa.String(length=64), nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("nonce", name=op.f("pk_identity_nonces")),
    )
    with op.batch_alter_table("identity_nonces", schema=None) as batch_op:
        batch_op.create_index("ix_identity_nonces_expires_at", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_table("identity_nonces")  # its index goes with it
