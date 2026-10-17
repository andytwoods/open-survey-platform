"""Reproducibility package (task M3): one deterministic zip per published version.

```python
from osp_targets.repro import ReproInputs, ReproKit, build_repro_package

pkg = build_repro_package(ReproInputs(survey, survey_id, 3, checksum, plan, kit))
pkg.content  # zip bytes; pkg.files lists what is inside
```

Contents: README, LICENSE, manifest, ``checksums.sha256``, the survey JSON and runtime plan,
the XLSForm and LSS exports with their diagnostics, the replay kit (``replay.py`` with the
vendored ``osp_engine.random``; ``engine.js`` + ``replay.mjs``) and, only when ``data`` is
given, the codebook and the responses (CSV, and JSON with event logs). Pure: the caller
reads the kit files (``kit/`` beside this module, ``osp_engine/random.py`` and the engine
bundle) and passes their bytes.
"""

from .package import (
    FORMAT,
    KIT_FILES,
    ReproData,
    ReproInputs,
    ReproKit,
    ReproPackage,
    build_repro_package,
)

__all__ = [
    "FORMAT",
    "KIT_FILES",
    "ReproData",
    "ReproInputs",
    "ReproKit",
    "ReproPackage",
    "build_repro_package",
]
