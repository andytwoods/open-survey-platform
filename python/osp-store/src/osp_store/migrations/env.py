"""Alembic environment. Driven programmatically by ``osp_store.migrate``.

The caller passes a live connection in ``config.attributes["connection"]``; there
is no alembic.ini and no URL in config.
"""

from __future__ import annotations

from alembic import context
from osp_store.schema import metadata

config = context.config
connection = config.attributes.get("connection")
if connection is None:  # pragma: no cover - misuse guard
    raise RuntimeError("use osp_store.migrate(engine); offline mode is not supported")

context.configure(
    connection=connection,
    target_metadata=metadata,
    render_as_batch=True,  # SQLite ALTER support for future migrations
    compare_type=True,
)
with context.begin_transaction():
    context.run_migrations()
