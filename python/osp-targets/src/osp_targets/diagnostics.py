"""Export diagnostics (planning/review.md §2.4).

Severity follows the capability level: ``lowered`` → ``info``, ``approximated`` →
``warning``, ``unsupported`` → ``loss``. ``error`` means nothing was exported (bad input or
an exporter failure). ``pointer`` is an RFC 6901 JSON pointer into the survey document.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from .capabilities import Level

Severity = Literal["info", "warning", "loss", "error"]

SEVERITY_FOR_LEVEL: dict[Level, Severity] = {
    "native": "info",
    "lowered": "info",
    "approximated": "warning",
    "unsupported": "loss",
}


class ExportDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True)

    target: str
    severity: Severity
    code: str  # "<target>.<level>" or "<target>.error.<what>"
    feature: str  # capability-table key, "" for errors
    level: Level | None
    pointer: str
    message: str


def pointer(*parts: str | int) -> str:
    """Build an RFC 6901 pointer from path parts."""
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)
