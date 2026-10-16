"""Response data export (task M2): CSV, JSON and the codebook. Pure functions, no I/O.

```python
from osp_targets.data import CsvOptions, StoredResponse, SurveyVersion, codebook, export_csv

v = SurveyVersion(survey_json, number=3, checksum="…", save_mode="every-page")
csv_bytes = export_csv(v, [StoredResponse("r1", record=engine_record)], CsvOptions.excel())
book = codebook(v)  # book.markdown, book.data
```

Missing values follow semantics §1: CSV = empty cell + ``<var>__state``; JSON = ``null`` +
``state``. Numeric missing codes (``-99``) are never written.
"""

from .codebook import codebook, codebook_combined, codebook_data
from .csv_export import escape_formula, export_csv, export_csv_combined
from .json_export import export_json, export_json_combined
from .model import (
    Codebook,
    CsvOptions,
    ExportError,
    Hook,
    JsonOptions,
    StoredResponse,
    SurveyVersion,
)

__all__ = [
    "Codebook",
    "CsvOptions",
    "ExportError",
    "Hook",
    "JsonOptions",
    "StoredResponse",
    "SurveyVersion",
    "codebook",
    "codebook_combined",
    "codebook_data",
    "escape_formula",
    "export_csv",
    "export_csv_combined",
    "export_json",
    "export_json_combined",
]
