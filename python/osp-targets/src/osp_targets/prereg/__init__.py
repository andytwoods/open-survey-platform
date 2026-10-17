"""Preregistration bundle (task OS1): one deterministic zip per published version, ready
to upload to a registry such as OSF.

```python
from osp_targets.prereg import PreregInputs, build_prereg_bundle

b = build_prereg_bundle(PreregInputs(survey, survey_id, 3, checksum, plan_checksum))
b.content       # zip bytes; b.files lists what is inside
b.summary_html  # the readable summary on its own
```

Contents: README, manifest, ``checksums.sha256``, the survey JSON with its checksum, the
codebook (Markdown + JSON), the design documents (structure and flow, randomisation and
assignment, planned exclusions; as Markdown and as ``design.json``), ``summary.html`` and,
when passed in, the reproducibility package of the same version. No participant data,
ever. ``prereg_data`` gives the design description alone.
"""

from .bundle import FORMAT, PreregBundle, PreregInputs, build_prereg_bundle, canonical_sha256
from .describe import prereg_data

__all__ = [
    "FORMAT",
    "PreregBundle",
    "PreregInputs",
    "build_prereg_bundle",
    "canonical_sha256",
    "prereg_data",
]
