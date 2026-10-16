"""LimeSurvey ``.lss`` export target (LimeSurvey 6.x; checked against 6.17.18).

```python
from osp_targets.lss import build_lss, export_lss

xml_bytes, diagnostics = export_lss(survey)  # Survey model or JSON dict; never raises
result, diagnostics = build_lss(survey)      # result.xml, .name_map, .renamed, .choice_codes
```

- **Capability table:** :data:`LSS` (``lss/capabilities.py``), same keys and completeness
  guard as the XLSForm table.
- **Structure:** each page is a question group (survey format G); blocks are consecutive
  groups. The flow tree becomes ``grelevance`` equations. Types: integer/decimal → N,
  text → S, single → L, multi → M (one subquestion per choice), date → D, note → X;
  computed, assigned and random-draw helpers are hidden equations (``*``).
- **Expressions** (``em.py``): Expression Manager with ``.NAOK`` reads and
  ``!is_empty()`` guards, so null comparisons are false (§3). Constraints become
  ``em_validation_q``; piping becomes ``{q.shown}`` (single choice) or ``{q}``.
- **Names:** question codes are letters and digits, start with a letter, at most 20
  characters, and never a LimeSurvey built-in column (``id``, ``token``, ``seed``,
  ``submitdate`` ...). Every rename is a diagnostic and is listed in ``name_map`` /
  ``renamed`` (and in a comment at the top of the XML). Invalid answer codes are
  replaced and listed in ``choice_codes``.
- **Randomness** uses LimeSurvey's own (``random_order``, ``random_group``,
  ``randomization_group``, latched ``rand()``): approximated, because our seed is not
  reproduced and the realised order is not stored.
- **Quotas** whose condition is an AND of (ORs of) answer codes become LimeSurvey quotas.
- **Import check:** ``make lss-import-check`` imports and activates every fixture in a
  real LimeSurvey 6.17 (``spikes/spike-1`` docker compose); skips without Docker.
"""

from .capabilities import LSS
from .em import EMContext, EMWriter
from .export import RESERVED_CODES, LssExport, build_lss, export_lss, feature_uses, sanitise_code

__all__ = [
    "LSS",
    "RESERVED_CODES",
    "EMContext",
    "EMWriter",
    "LssExport",
    "build_lss",
    "export_lss",
    "feature_uses",
    "sanitise_code",
]
