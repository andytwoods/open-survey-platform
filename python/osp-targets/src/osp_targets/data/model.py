"""Inputs and options of the response data export. Plain data, no I/O.

The export never reads a store: the app layer (``osp_app``) loads one published version and
its responses and hands them over as ``SurveyVersion`` + ``StoredResponse``. Everything the
server knows about a response (row columns) wins over what the browser put in its record.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from osp_spec import Diagnostic

SaveMode = Literal["every-page", "end-only"]
MultiFormat = Literal["columns", "codes"]


@dataclass(frozen=True)
class Hook:
    """A researcher hook as the codebook lists it (runtime-design §7a). ``osp-survey/0.1``
    has no hook fields yet (task R7), so the app passes none for now."""

    id: str
    events: Sequence[str] = ()
    reads: Sequence[str] = ()
    # e.g. "network:https://lab.example", "redirect", "postToParent"
    data_exports: Sequence[str] = ()


@dataclass(frozen=True)
class SurveyVersion:
    """One published version: its survey JSON (or parsed ``osp_spec.Survey``) and checksum."""

    survey: Any
    number: int | None = None
    checksum: str | None = None
    save_mode: SaveMode | None = None  # from the publication; None: not known
    hooks: Sequence[Hook] = ()


@dataclass(frozen=True)
class StoredResponse:
    """One submitted response. ``record`` is the engine's ``osp-response/1`` ResponseRecord
    (``web/engine`` ``result()``); the other fields are the store's row and win over the
    record when both are given. A row without a record (``record_response``) exports from
    ``answers`` alone."""

    response_id: str
    record: Mapping[str, Any] | None = None
    answers: Mapping[str, Any] | None = None  # {questionId: {state, value}}
    session_id: str | None = None
    version: int | None = None
    version_checksum: str | None = None
    allocation_mode: str | None = None
    save_mode: str | None = None
    session_seed: int | None = None
    assigned: Mapping[str, Any] | None = None
    orders: Mapping[str, Any] | None = None
    engine_version: str | None = None
    started_at: datetime | None = None
    submitted_at: datetime | None = None
    late: bool | None = None  # the server's flag (stored record ``server.late``); None = false
    after_close: bool | None = None  # submitted after the survey closed; None = not known


@dataclass(frozen=True)
class CsvOptions:
    """CSV export options. The defaults suit any tool; ``CsvOptions.excel()`` adds a BOM.

    - ``state_columns``: add ``<var>__state`` after every question (semantics §1; on by
      default). Switched off, an empty cell no longer says *why* it is empty.
    - ``multi``: ``columns`` = one 0/1 column per choice (``<var>_<code>``); ``codes`` = one
      cell with the chosen codes, space-separated, in choice-list order.
    - ``bom``: start with a UTF-8 byte order mark so Excel reads the file as UTF-8.
    - ``escape_formulas``: prefix a cell that starts with ``=``, ``+``, ``-``, ``@``, tab or
      CR with ``'`` so a spreadsheet shows it as text instead of running it (plain numbers
      such as ``-3`` or ``-2.5`` are left alone).
    """

    state_columns: bool = True
    multi: MultiFormat = "columns"
    bom: bool = False
    escape_formulas: bool = True

    @classmethod
    def excel(cls, **overrides: Any) -> CsvOptions:
        return cls(**{"bom": True, "escape_formulas": True, **overrides})


@dataclass(frozen=True)
class JsonOptions:
    """JSON export options. ``events``: include each response's engine event log."""

    events: bool = False


@dataclass(frozen=True)
class Codebook:
    markdown: str
    data: dict[str, Any] = field(default_factory=dict)


class ExportError(Exception):
    """The export could not be built (an invalid survey, clashing column names). Carries
    diagnostics instead of a traceback (AGENTS.md rule 3)."""

    def __init__(self, message: str, diagnostics: Sequence[Diagnostic] = ()) -> None:
        super().__init__(message)
        self.diagnostics = list(diagnostics)
