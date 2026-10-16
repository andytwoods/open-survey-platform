"""Repo-wide pytest config: Hypothesis profiles.

- `dev` (local default): the example database is kept in `.hypothesis/` at the checkout
  root (gitignored), so a failure Hypothesis found replays on the next run. Each git
  worktree has its own. Set `HYPOTHESIS_STORAGE_DIRECTORY` to put it somewhere else.
- `ci` (default when `CI` is set, as on GitHub Actions): no database; nothing is written.
- `nightly`: as `ci`. Tests marked `nightly` (deselected by default) use bigger example
  counts: `uv run pytest -m nightly` (add `--hypothesis-profile=...` to override).

Pick one with `HYPOTHESIS_PROFILE=<name>` or `--hypothesis-profile=<name>`. A test's own
`@settings(max_examples=...)` wins over the profile.
"""

from __future__ import annotations

import os

try:
    from hypothesis import settings
except ImportError:  # pragma: no cover - hypothesis is a dev dependency
    pass
else:
    settings.register_profile("dev")
    settings.register_profile("ci", database=None, print_blob=True)
    settings.register_profile("nightly", database=None, print_blob=True)
    settings.load_profile(
        os.environ.get("HYPOTHESIS_PROFILE") or ("ci" if os.environ.get("CI") else "dev")
    )
