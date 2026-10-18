"""Qualtrics ``.qsf`` export target (the JSON survey file Qualtrics imports).

```python
from osp_targets.qsf import build_qsf, export_qsf

qsf_bytes, diagnostics = export_qsf(survey)  # Survey model or JSON dict; never raises
result, diagnostics = build_qsf(survey)      # result.qsf, .name_map, .renamed, .choice_codes, .qids
```

- **Capability table:** :data:`QSF` (``qsf/capabilities.py``), same keys and completeness
  guard as the XLSForm and LimeSurvey tables.
- **Structure:** each block is a Qualtrics block (`BL`), its pages separated by page
  breaks; the flow tree is the survey flow (`FL`): blocks, branches (an else arm is a
  second branch on the negated condition), randomizers (`BlockRandomizer` with `SubSet`)
  and End of Survey elements. Types: single → MC/SAVR, multi → MC/MAVR, text → TE/SL or
  TE/ML, integer/decimal → TE with `ValidNumber`, date → TE with `ValidDate`, matrix →
  Matrix/Likert/SingleAnswer, slider → Slider/HSLIDER, note → DB/TB.
- **Logic:** `showIf` and branch conditions become display / branch logic, rewritten as
  Or-ed sets of And-ed conditions, each guarded so a missing value behaves as in §3. A
  condition Qualtrics logic cannot say is reported (`$logic.unmappable`).
- **Variables:** embedded variables are embedded data fields named after their URL
  parameter (defaults set by a branch when the URL left them empty); assigned variables
  are randomizers over embedded data elements; computed variables and quotas are not
  exported.
- **Names:** export tags start with a letter and hold letters, digits and `_`, never a
  Qualtrics response column (`ResponseId`, `StartDate` ...). Every rename is a diagnostic
  and is listed in ``name_map`` / ``renamed``. Text choice values get numeric recodes,
  listed in ``choice_codes``.
- **Determinism:** ids (`SV_`, `BL_`, `QIDn`, `FL_n`) are derived from the survey, so the
  same survey always gives the same bytes.
"""

from .capabilities import QSF
from .export import (
    RESERVED_NAMES,
    QsfExport,
    build_qsf,
    export_qsf,
    feature_uses,
    logic_document,
    sanitise_name,
)

__all__ = [
    "QSF",
    "RESERVED_NAMES",
    "QsfExport",
    "build_qsf",
    "export_qsf",
    "feature_uses",
    "logic_document",
    "sanitise_name",
]
