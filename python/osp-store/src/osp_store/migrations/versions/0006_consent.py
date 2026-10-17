"""consent before collection, and the anonymous decline count (M5)

Revision ID: 0006_consent
Revises: 0005_public_slug
Create Date: 2026-10-16

- ``participant_sessions.consent_version`` / ``consented_at``: the consent version a
  participant agreed to and when (server clock). The server refuses response data for a
  survey with a consent page until both are set (semantics.md §11).
- ``publications.declines``: anonymous count of consent declines, kept only when the
  survey sets ``consent.countDeclines``. A declined session is deleted.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_consent"
down_revision = "0005_public_slug"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("participant_sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("consent_version", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("publications", schema=None) as batch_op:
        batch_op.add_column(sa.Column("declines", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("publications", schema=None) as batch_op:
        batch_op.drop_column("declines")
    with op.batch_alter_table("participant_sessions", schema=None) as batch_op:
        batch_op.drop_column("consented_at")
        batch_op.drop_column("consent_version")
