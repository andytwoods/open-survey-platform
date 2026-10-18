"""SurveyJS survey JSON export target (task XP1).

```python
from osp_targets.surveyjs import build_surveyjs, export_surveyjs

json_bytes, diagnostics = export_surveyjs(survey)  # Survey model or JSON dict; never raises
result, diagnostics = build_surveyjs(survey)        # result.json, .document, .name_map, .helpers
```

- **Capability table:** :data:`SURVEYJS` (``surveyjs/capabilities.py``), same keys and
  completeness guard as the XLSForm and LimeSurvey tables.
- **Structure:** each page is a SurveyJS page; blocks are consecutive pages. The flow tree
  becomes page ``visibleIf`` conditions; end nodes become ``completedHtmlOnCondition``
  entries (and ``navigateToUrlOnCondition`` for redirects). Types: integer/decimal → text
  ``inputType: "number"`` (integer with a whole-number regex validator), text → text or
  comment, single → radiogroup, multi → checkbox, date → text ``inputType: "date"``,
  matrix → matrix, slider → slider, note → html; computed variables → ``calculatedValues``.
- **Expressions** (``expr.py``): ``{name}`` references, guarded with ``notempty`` so a
  comparison with a missing value is false (§3). Constraints become ``expression``
  validators, checked only on answered values.
- **Names:** SurveyJS takes our variable names as they are; a matrix row is
  ``{matrix.row}``. Texts are localisable strings (``{"default": …, "de": …}``).
- **Not carried:** quotas, consent, assigned variables, hooks, external tasks, the theme;
  randomisers show every child in order. Each is a diagnostic.
- **Round trip:** ``import_surveyjs`` (``osp_targets.imports``) reads every export back;
  ``tests/test_surveyjs_export.py`` lists what changes on the way.
"""

from .capabilities import SURVEYJS
from .export import SurveyJsExport, build_surveyjs, export_surveyjs, feature_uses
from .expr import SjsContext, SjsWriter, Unmappable

__all__ = [
    "SURVEYJS",
    "SjsContext",
    "SjsWriter",
    "SurveyJsExport",
    "Unmappable",
    "build_surveyjs",
    "export_surveyjs",
    "feature_uses",
]
