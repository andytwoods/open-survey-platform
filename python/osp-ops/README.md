# osp-ops

**Layer:** L2. Imports only packages in lower layers (enforced by `uv run lint-imports`). No I/O: no network, database, clock or global randomness.

**Job:** Edit operation registry: `(survey, args) -> (survey', inverse)`, transactions, fuzz harness. Every survey edit is an op.

Internal package; not published.
