"""Survey importers (task IM1): Qualtrics ``.qsf``, LimeSurvey ``.lss`` and SurveyJS JSON
→ an ``osp-survey`` draft, with a diagnostic for every feature that did not carry over.

```python
from osp_targets.imports import detect_format, import_survey

result = import_survey("study.qsf", content)   # never raises
result.format, result.survey, result.diagnostics, result.summary, result.validation
```

Clean-room: written from each platform's public documentation and the shape of exported
files (our own invented samples in ``tests/data/imports``), never from their code.
"""

from __future__ import annotations

import json
from typing import Any

from .common import (
    FORMAT_LABELS,
    FORMATS,
    Format,
    ImportDiagnostic,
    ImportResult,
    ImportSummary,
)
from .lss import import_lss
from .qsf import import_qsf
from .surveyjs import import_surveyjs

_EXTENSIONS: dict[str, Format] = {"qsf": "qsf", "lss": "lss", "json": "surveyjs"}


def detect_format(filename: str | None, content: str | bytes) -> Format | None:
    """The format of ``content``, from what it looks like first and the extension second.
    None when it is neither XML nor JSON."""
    text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
    head = text.lstrip("﻿ \t\r\n")[:200]
    if head.startswith("<"):
        return "lss"
    ext = (filename or "").rsplit(".", 1)[-1].lower() if filename and "." in filename else ""
    if head.startswith("{"):
        if '"SurveyEntry"' in text[:20000] or '"SurveyElements"' in text[:20000]:
            return "qsf"
        if ext == "qsf":
            return "qsf"
        return "surveyjs"
    if head.startswith("["):
        return "surveyjs"
    return _EXTENSIONS.get(ext)


def import_survey(
    filename: str | None, content: str | bytes, fmt: Format | None = None
) -> ImportResult:
    """Import ``content``; ``fmt`` overrides detection. Never raises."""
    kind = fmt or detect_format(filename, content)
    if kind == "qsf":
        return import_qsf(content)
    if kind == "lss":
        return import_lss(content)
    if kind == "surveyjs":
        return import_surveyjs(content)
    return ImportResult(
        "surveyjs",
        None,
        [
            ImportDiagnostic(
                format="surveyjs",
                severity="error",
                code="import.unknown_format",
                feature="",
                pointer="",
                message="the file is neither a .qsf, a .lss nor a SurveyJS JSON document",
            )
        ],
        [],
        None,
    )


def result_to_json(result: ImportResult) -> dict[str, Any]:
    """A plain-JSON view of a result (for the CLI and tests)."""
    return json.loads(
        json.dumps(
            {
                "format": result.format,
                "ok": result.ok,
                "survey": result.survey,
                "diagnostics": [d.model_dump(mode="json") for d in result.diagnostics],
                "validation": [d.model_dump(mode="json") for d in result.validation],
                "summary": None
                if result.summary is None
                else result.summary.model_dump(mode="json"),
            }
        )
    )


__all__ = [
    "FORMATS",
    "FORMAT_LABELS",
    "Format",
    "ImportDiagnostic",
    "ImportResult",
    "ImportSummary",
    "detect_format",
    "import_lss",
    "import_qsf",
    "import_survey",
    "import_surveyjs",
    "result_to_json",
]
