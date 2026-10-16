"""osp-spec (layer L1): the `osp-survey` model, JSON Schema export and semantic validator.

Pure data, no I/O. See README.md.
"""

from .diagnostics import CODES, Diagnostic, has_errors
from .expr import Expression
from .model import SPEC_VERSION, Survey
from .reserved import RESERVED_NAMES
from .schema import json_schema
from .validate import parse, validate

__all__ = [
    "CODES",
    "RESERVED_NAMES",
    "SPEC_VERSION",
    "Diagnostic",
    "Expression",
    "Survey",
    "has_errors",
    "json_schema",
    "parse",
    "validate",
]
