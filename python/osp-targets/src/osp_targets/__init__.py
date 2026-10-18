"""osp-targets (layer L3): export targets and their capability tables. Pure, no I/O.

See README.md.
"""

from .capabilities import LEVELS, TABLES, XLSFORM, Capability, Level
from .diagnostics import ExportDiagnostic
from .lss import LSS, build_lss, export_lss
from .qsf import QSF, build_qsf, export_qsf
from .surveyjs import SURVEYJS, build_surveyjs, export_surveyjs
from .xlsform import build_xlsform, export_xlsform

TABLES.setdefault("lss", LSS)
TABLES.setdefault("qsf", QSF)
TABLES.setdefault("surveyjs", SURVEYJS)

__all__ = [
    "LEVELS",
    "TABLES",
    "XLSFORM",
    "Capability",
    "ExportDiagnostic",
    "Level",
    "build_lss",
    "build_qsf",
    "build_surveyjs",
    "build_xlsform",
    "export_lss",
    "export_qsf",
    "export_surveyjs",
    "export_xlsform",
]
