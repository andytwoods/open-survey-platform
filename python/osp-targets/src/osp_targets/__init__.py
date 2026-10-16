"""osp-targets (layer L3): export targets and their capability tables. Pure, no I/O.

See README.md.
"""

from .capabilities import LEVELS, TABLES, XLSFORM, Capability, Level
from .diagnostics import ExportDiagnostic
from .xlsform import build_xlsform, export_xlsform

__all__ = [
    "LEVELS",
    "TABLES",
    "XLSFORM",
    "Capability",
    "ExportDiagnostic",
    "Level",
    "build_xlsform",
    "export_xlsform",
]
