"""Results viewer aggregation (task V1, planning/results-viewer.md). Thin: HTTP <-> the
``survey.results_query`` / ``survey.results_text`` app commands.

Permission ``survey.export`` (owner, editor). Viewers get 403, other labs 404. Every call
is audited as ``results.read`` (actor, query, versions; never answer values).

- ``POST /api/surveys/{id}/results/query``: aggregate tables for one or more question
  cards (counts, percentages, bins, statistics). The browser never gets response rows.
- ``GET /api/surveys/{id}/results/text/{question}``: the verbatim answers of one text
  question, paginated with an opaque cursor.

Semantics (V-D5) live in ``osp_app.results``; units are responses, never participants.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from .common import Auth, Services, errors

router = APIRouter(prefix="/api/surveys", tags=["results"])

Code = int | str
STATE_DOC = (
    "Response-state counts. answered + unanswered make up the 'shown' denominator; "
    "irrelevant, notReached and notInVersion are never in a denominator. unrecorded: the "
    "stored record has no state for the question; invalid: answered with a value that does "
    "not fit the question (e.g. a code it does not declare). Both are outside denominators."
)


# -- request ----------------------------------------------------------------------------


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AnswerFilter(_In):
    question: str = Field(
        max_length=200,
        description="Id of a single-choice, multiple-choice or matrix-row variable "
        "(<matrix id>_<row id>)",
    )
    in_: list[Code] = Field(
        alias="in",
        min_length=1,
        max_length=500,
        description="Keep responses that answered with one of these codes (multiple "
        "choice: chose at least one of them). Codes compare as text.",
    )


class ConditionFilter(_In):
    variable: str = Field(max_length=200, description="Id of an assigned variable")
    in_: list[Code] = Field(alias="in", min_length=1, max_length=500)


class SplitSpec(_In):
    """Exactly one of ``question`` (single choice or matrix row) or ``condition``."""

    question: str | None = Field(None, max_length=200)
    condition: str | None = Field(None, max_length=200, description="Assigned variable id")
    excludeMissing: bool = Field(
        False, description="Drop the 'no value' group instead of showing it"
    )


class BinSpec(_In):
    width: float | None = Field(None, gt=0, description="Numeric bin width")
    count: int | None = Field(None, ge=1, le=200, description="Number of numeric bins")
    unit: Literal["day", "week", "month", "year"] | None = Field(
        None, description="Date questions: period per bar (default month)"
    )


class CardRequest(_In):
    question: str = Field(max_length=200, description="Question id (a matrix: the matrix id)")
    bins: BinSpec | None = None


class ResultsQuery(_In):
    versions: list[Annotated[int, Field(ge=1)]] | None = Field(
        None,
        min_length=1,
        max_length=50,
        description="Published version numbers; omitted: the latest published version",
    )
    status: Literal["complete", "all"] = Field(
        "complete",
        description="complete: responses whose end outcome is 'complete' (or that carry "
        "no outcome at all); all: every submitted response",
    )
    submittedFrom: datetime | None = Field(None, description="Inclusive; naive is UTC")
    submittedTo: datetime | None = Field(None, description="Exclusive; naive is UTC")
    filters: list[AnswerFilter] = Field(default_factory=list, max_length=20)
    condition: ConditionFilter | None = None
    split: SplitSpec | None = None
    denominator: Literal["answered", "shown"] = Field(
        "answered", description="shown = answered + unanswered"
    )
    intervals: bool = Field(
        False, description="Add 95 % intervals: Wilson for proportions, t for means"
    )
    cards: list[CardRequest] | None = Field(
        None,
        max_length=500,
        description="Omitted: every question of the newest version used, in survey order",
    )
    language: str | None = Field(
        None, max_length=35, description="Label language; default the survey's main language"
    )


# -- response ---------------------------------------------------------------------------


class ResultWarning(BaseModel):
    code: str = Field(
        description="versions.incompatible | language.unknown | bins.coarsened | "
        "values.invalid | question.not_found | question.note"
    )
    message: str
    question: str | None = None


class StateCounts(BaseModel):
    answered: int
    unanswered: int
    irrelevant: int
    notReached: int
    notInVersion: int
    unrecorded: int
    invalid: int


class Category(BaseModel):
    key: str = Field(description="The choice code as text (cells refer to it)")
    code: Code
    label: str


class Cell(BaseModel):
    key: str = Field(
        description="Choice code as text, bin index ('0', '1', ...), slider "
        "value or date period ('2026-10', '2026-W42', '2026-10-17', '2026')"
    )
    label: str
    count: int
    pct: float | None = Field(
        description="100 * count / group n; null when n is 0. Multiple choice: % of "
        "respondents, can sum to more than 100"
    )
    lo: float | None = Field(None, description="Numeric bin lower edge (inclusive)")
    hi: float | None = Field(
        None, description="Numeric bin upper edge (exclusive; the last bin includes it)"
    )
    ci: list[float] | None = Field(None, description="Wilson 95 % interval of pct, if asked")


class Stats(BaseModel):
    """Statistics that apply to the card type. An applicable statistic that is undefined
    for the data (e.g. SD with n < 2) is null and listed in ``notAvailable``."""

    n: int = Field(description="The denominator: answered (or shown) responses")
    mode: list[str] | None = Field(None, description="Category key(s) with the top count")
    median: float | str | None = Field(
        None, description="Numbers: median; ordered choices: the median category key"
    )
    mean: float | None = None
    sd: float | None = Field(None, description="Sample SD (n - 1)")
    q1: float | None = Field(None, description="Quartiles: linear interpolation (type 7)")
    q3: float | None = None
    min: float | None = None
    max: float | None = None
    meanCi: list[float] | None = Field(None, description="t 95 % interval of the mean")
    top2: float | None = Field(None, description="Ordered choices (>= 4): % in the top two")
    bottom2: float | None = None
    meanOptions: float | None = Field(None, description="Multiple choice: options per answer")
    meanLength: float | None = Field(None, description="Text: characters per answer")
    earliest: str | None = Field(None, description="Date: earliest answer")
    latest: str | None = None
    notAvailable: list[str] = Field(default_factory=list)


class Group(BaseModel):
    key: str = Field(
        description="'all' without a split; else the split code, or "
        "'_missing' for responses with no split value"
    )
    label: str
    missing: bool = False
    responses: int = Field(description="Responses in the group (after filters)")
    n: int = Field(description="The group's denominator for this card")
    states: StateCounts
    cells: list[Cell]
    stats: Stats


class RowResult(BaseModel):
    """One matrix row: its own variable with its own n (V-D5)."""

    id: str = Field(description="Row variable id <matrix id>_<row id>")
    name: str
    label: str
    states: StateCounts
    groups: list[Group]


class CardData(BaseModel):
    states: StateCounts | None = Field(None, description=STATE_DOC)
    groups: list[Group] = Field(default_factory=list)
    rows: list[RowResult] | None = Field(None, description="Matrix questions only")
    categories: list[Category] | None = Field(
        None, description="Choices / matrix columns in declared order, shared by all groups"
    )
    binning: Literal["categories", "values", "bins", "periods"] | None = None
    binEdges: list[float] | None = Field(
        None, description="Shared numeric bin edges (len = bins + 1)"
    )
    binUnit: Literal["day", "week", "month", "year"] | None = None


class Facet(CardData):
    version: int


class Card(CardData):
    question: str
    name: str
    type: Literal[
        "single", "multi", "integer", "decimal", "slider", "date", "text", "matrix", "note"
    ]
    label: str
    ordered: bool | None = Field(
        None, description="Choices / columns are an ordered scale (numeric codes ascending)"
    )
    versionsUsed: list[int] = Field(description="Versions that contain the question")
    facets: list[Facet] | None = Field(
        None,
        description="Versions whose definitions differ: one facet per version, top-level "
        "groups empty (see warnings)",
    )
    warnings: list[ResultWarning] = Field(default_factory=list)


class SplitGroup(BaseModel):
    key: str
    label: str
    missing: bool = False
    responses: int


class SplitInfo(BaseModel):
    question: str | None = None
    condition: str | None = None
    label: str
    groups: list[SplitGroup]


class ResultsResponse(BaseModel):
    surveyId: str
    queryHash: str = Field(description="Hash of the normalised query (versions resolved)")
    watermark: str = Field(description="Changes whenever the versions' responses change")
    generatedAt: datetime
    cached: bool
    versionsUsed: list[int]
    language: str
    languages: list[str]
    denominator: Literal["answered", "shown"]
    responses: int = Field(description="Responses after status, date and answer filters")
    split: SplitInfo | None = None
    cards: list[Card]
    warnings: list[ResultWarning] = Field(default_factory=list)


class TextItem(BaseModel):
    responseId: str
    version: int
    submittedAt: datetime | None
    language: str | None
    value: str


class TextPage(BaseModel):
    question: str
    name: str
    label: str
    versionsUsed: list[int]
    states: StateCounts
    total: int = Field(description="Answered responses matching the filters")
    items: list[TextItem]
    nextCursor: str | None
    watermark: str


# -- routes -----------------------------------------------------------------------------


@router.post(
    "/{survey_id}/results/query",
    operation_id="queryResults",
    response_model=ResultsResponse,
    responses=errors(401, 403, 404, 422),
)
def query_results(
    survey_id: str, body: ResultsQuery, auth: Auth, services: Services
) -> dict[str, Any]:
    """Aggregate tables per question card (survey.export; audited, no answer values)."""
    raise HTTPException(501, "Not implemented yet (task V1).")
    return services.builder.run(
        "survey.results_query",
        auth.actor,
        survey_id=survey_id,
        query=body.model_dump(mode="json", by_alias=True),
    )


@router.get(
    "/{survey_id}/results/text/{question}",
    operation_id="resultsText",
    response_model=TextPage,
    responses=errors(401, 403, 404, 422),
)
def results_text(
    survey_id: str,
    question: Annotated[str, Path(max_length=200, description="Text question id")],
    auth: Auth,
    services: Services,
    versions: Annotated[
        list[int] | None, Query(description="Version numbers (repeat); default latest")
    ] = None,
    status: Literal["complete", "all"] = "complete",
    submitted_from: Annotated[datetime | None, Query(alias="submittedFrom")] = None,
    submitted_to: Annotated[datetime | None, Query(alias="submittedTo")] = None,
    filters: Annotated[
        list[str] | None,
        Query(
            alias="filter",
            description="Answer filter '<question>:<code>[,<code>...]' (repeat to AND)",
        ),
    ] = None,
    condition: Annotated[
        str | None, Query(description="Condition filter '<variable>:<level>[,<level>...]'")
    ] = None,
    cursor: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """Verbatim answers of one text question (survey.export; audited)."""
    raise HTTPException(501, "Not implemented yet (task V1).")
    return services.builder.run(
        "survey.results_text",
        auth.actor,
        survey_id=survey_id,
        question=question,
        versions=versions,
        status=status,
        submitted_from=submitted_from,
        submitted_to=submitted_to,
        filters=filters or [],
        condition=condition,
        cursor=cursor,
        limit=limit,
    )
