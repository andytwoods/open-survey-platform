# osp-engine

**Layer:** L2. Imports only packages in lower layers (enforced by `uv run lint-imports`). No I/O: no network, database, clock or global randomness.

**Job:** Pure, deterministic flow state machine plus trace: the oracle every runtime is tested against. Seeded PRNG only.

Internal package; not published.
