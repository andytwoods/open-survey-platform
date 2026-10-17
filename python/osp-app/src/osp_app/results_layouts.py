"""Saved results layouts (plan V, ``planning/results-viewer.md`` V-D9; task V5a).

A layout is how a lab wants a survey's Results page shown: the query (filters, split,
denominator, versions), one entry per question card in display order (chart choice,
hidden, bins, caption) and a few page switches. Layouts are stored per survey, shared by
the lab, and edited by owners and editors (``survey.export``, the results permission:
V-D3 gives viewers nothing of the results viewer yet). One layout per survey may be the
default.

**A layout never stores data.** :class:`LayoutSettings` is a closed schema (unknown fields
are refused, every string is bounded, every list is capped) and the query part must also
pass V1's :func:`osp_app.results.parse_query`, so a saved layout is always a query the
results endpoint accepts. The store adds a 64 KB cap on the canonical JSON.

Registered on import (``osp_app/__init__.py``); dispatched through ``Builder.run`` like the
other commands, so ``builder`` is the first argument.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal

from osp_spec import Diagnostic
from osp_spec.theme import PRESETS
from osp_store import Conflict, InvalidInput, NotFound, StoredResultsLayout
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, model_validator

from .auth.permissions import Action, Actor
from .builder import Builder
from .commands import command
from .errors import ConflictError, InvalidRequest, NotFoundError, Rejected
from .results import parse_query

SCHEMA_VERSION = "osp-results-layout/0.1"
Code = int | str
CHART_ID = r"^[a-z][a-z0-9-]{0,39}$"


class _Model(BaseModel):
    # Closed: unknown fields are refused; inf/nan never reach the stored JSON; switches are
    # real booleans (lax mode would read "yes" as true).
    model_config = ConfigDict(extra="forbid", populate_by_name=True, allow_inf_nan=False)


class LayoutFilter(_Model):
    question: str = Field(min_length=1, max_length=200)
    in_: list[Code] = Field(alias="in", min_length=1, max_length=500)


class LayoutCondition(_Model):
    variable: str = Field(min_length=1, max_length=200)
    in_: list[Code] = Field(alias="in", min_length=1, max_length=500)


class LayoutSplit(_Model):
    """Exactly one of ``question`` or ``condition`` (as the results query)."""

    question: str | None = Field(None, min_length=1, max_length=200)
    condition: str | None = Field(None, min_length=1, max_length=200)
    excludeMissing: StrictBool = False

    @model_validator(mode="after")
    def _one_of(self) -> LayoutSplit:
        if (self.question is None) == (self.condition is None):
            raise ValueError("split needs exactly one of question or condition")
        return self


class LayoutBins(_Model):
    width: float | None = Field(None, gt=0)
    count: int | None = Field(None, ge=1, le=200)
    unit: Literal["day", "week", "month", "year"] | None = None


class LayoutQuery(_Model):
    """The results query the layout opens with (the fields of ``ResultsQuery`` except
    ``cards``, which the layout's card list supplies)."""

    versions: list[Annotated[int, Field(ge=1)]] | None = Field(
        None, min_length=1, max_length=50, description="Omitted: the latest published version"
    )
    status: Literal["complete", "all"] = "complete"
    submittedFrom: datetime | None = None
    submittedTo: datetime | None = None
    filters: list[LayoutFilter] = Field(default_factory=list, max_length=20)
    condition: LayoutCondition | None = None
    split: LayoutSplit | None = None
    denominator: Literal["answered", "shown"] = "answered"
    intervals: StrictBool = False
    language: str | None = Field(None, min_length=1, max_length=35)


class CardLayout(_Model):
    """One question card. The list order of ``cards`` is the display order."""

    question: str = Field(min_length=1, max_length=200, description="Question id")
    chart: str | None = Field(
        None,
        pattern=CHART_ID,
        description="Chart menu id (e.g. bars, donut, histogram, likert, table). The page "
        "falls back to the type's default when the id does not suit the question.",
    )
    splitLayout: Literal["grouped", "stacked", "multiples"] | None = None
    hidden: StrictBool = False
    bins: LayoutBins | None = None
    caption: str | None = Field(None, max_length=2000, description="Edited caption (V-D8)")


class LayoutTheme(_Model):
    """The colours the Results page draws its cards and figures in (task V6): the app's own
    colours, the survey's theme, a built-in preset or a lab library theme. A theme id is a
    reference only; the theme document itself is never stored in a layout."""

    kind: Literal["app", "survey", "preset", "library"] = "app"
    id: str | None = Field(
        None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="The preset id or lab library theme id (presets and library themes only)",
    )

    @model_validator(mode="after")
    def _id_matches_kind(self) -> LayoutTheme:
        if self.kind in ("app", "survey"):
            if self.id is not None:
                raise ValueError(f"theme kind {self.kind!r} takes no id")
        elif self.id is None:
            raise ValueError(f"theme kind {self.kind!r} needs an id")
        elif self.kind == "preset" and self.id not in PRESETS:
            raise ValueError(f"unknown theme preset {self.id!r}")
        return self


class LayoutExport(_Model):
    """V4's figure export settings and the "Export all" bundle (task V6)."""

    widthMm: int = Field(85, ge=30, le=500, description="Final figure width")
    dpi: Literal[150, 300, 600] = 300
    hideCountsBelow: int | None = Field(
        None, ge=2, le=1000, description='k for "Hide counts below k"; null: off'
    )
    bundle: Literal["svg", "png", "all"] = Field(
        "all", description='What "Export all" puts in the ZIP'
    )


class LayoutSettings(_Model):
    """What a saved layout holds: settings only, never response data."""

    schemaVersion: Literal["osp-results-layout/0.1"] = SCHEMA_VERSION
    query: LayoutQuery = Field(default_factory=LayoutQuery)
    cards: list[CardLayout] = Field(
        default_factory=list,
        max_length=500,
        description="Cards in display order; questions not listed follow in survey order",
    )
    showNotes: StrictBool = Field(False, description="Show note items as headings")
    theme: LayoutTheme = Field(default_factory=LayoutTheme)
    export: LayoutExport = Field(default_factory=LayoutExport)

    @model_validator(mode="after")
    def _unique_questions(self) -> LayoutSettings:
        seen: set[str] = set()
        for card in self.cards:
            if card.question in seen:
                raise ValueError(f"cards: question {card.question!r} is listed twice")
            seen.add(card.question)
        return self


def _pointer(loc: tuple[Any, ...]) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in loc)


def validate_settings(raw: object) -> dict[str, Any]:
    """The normalised JSON form of ``raw``, or ``Rejected`` with ``layout.schema``
    diagnostics. Then the query part must pass V1's parser (``InvalidRequest`` if not)."""
    try:
        settings = LayoutSettings.model_validate(raw)
    except ValidationError as exc:
        raise Rejected(
            "That is not a valid results layout.",
            [
                Diagnostic(
                    severity="error",
                    code="layout.schema",
                    message=err["msg"],
                    pointer=_pointer(err["loc"]),
                )
                for err in exc.errors()
            ],
        ) from None
    out = settings.model_dump(mode="json", by_alias=True)
    parse_query(
        {
            **out["query"],
            "cards": [{"question": c["question"], "bins": c["bins"]} for c in out["cards"]],
        }
    )
    return out


@dataclass(frozen=True)
class ResultsLayoutsView:
    survey_id: str
    layouts: list[StoredResultsLayout]
    default_layout_id: str | None


def _store_call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except NotFound as exc:
        raise NotFoundError("Layout not found.") from exc
    except Conflict as exc:
        raise ConflictError("The survey already has a layout with that name.") from exc
    except InvalidInput as exc:
        raise InvalidRequest(str(exc)) from exc


def _name(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise InvalidRequest("name must be 1-200 characters")
    return value.strip()


@command("survey.results_layouts", label="List results layouts", action=Action.SURVEY_EXPORT)
def list_layouts(builder: Builder, actor: Actor, *, survey_id: str) -> ResultsLayoutsView:
    ctx = builder._locate(actor, survey_id, Action.SURVEY_EXPORT)
    layouts = _store_call(builder.store.list_results_layouts, ctx, survey_id)
    default = next((lay.id for lay in layouts if lay.is_default), None)
    return ResultsLayoutsView(survey_id, layouts, default)


@command("survey.results_layout_get", label="Get results layout", action=Action.SURVEY_EXPORT)
def get_layout(
    builder: Builder, actor: Actor, *, survey_id: str, layout_id: str = ""
) -> StoredResultsLayout:
    ctx = builder._locate(actor, survey_id, Action.SURVEY_EXPORT)
    return _store_call(builder.store.get_results_layout, ctx, survey_id, layout_id)


@command("survey.results_layout_create", label="Save results layout", action=Action.SURVEY_EXPORT)
def create_layout(
    builder: Builder,
    actor: Actor,
    *,
    survey_id: str,
    name: str = "",
    settings: Any = None,
    default: bool = False,
) -> StoredResultsLayout:
    ctx = builder._locate(actor, survey_id, Action.SURVEY_EXPORT)
    name = _name(name)
    body = validate_settings(settings if settings is not None else {})
    if not isinstance(default, bool):
        raise InvalidRequest("default must be true or false")
    return _store_call(
        builder.store.create_results_layout, ctx, survey_id, name, body, default=default
    )


@command("survey.results_layout_update", label="Update results layout", action=Action.SURVEY_EXPORT)
def update_layout(
    builder: Builder,
    actor: Actor,
    *,
    survey_id: str,
    layout_id: str = "",
    name: str | None = None,
    settings: Any = None,
) -> StoredResultsLayout:
    ctx = builder._locate(actor, survey_id, Action.SURVEY_EXPORT)
    new_name = None if name is None else _name(name)
    body = None if settings is None else validate_settings(settings)
    return _store_call(
        builder.store.update_results_layout,
        ctx,
        survey_id,
        layout_id,
        name=new_name,
        settings=body,
    )


@command("survey.results_layout_delete", label="Delete results layout", action=Action.SURVEY_EXPORT)
def delete_layout(builder: Builder, actor: Actor, *, survey_id: str, layout_id: str = "") -> None:
    ctx = builder._locate(actor, survey_id, Action.SURVEY_EXPORT)
    _store_call(builder.store.delete_results_layout, ctx, survey_id, layout_id)


@command(
    "survey.results_layout_set_default",
    label="Make default results layout",
    action=Action.SURVEY_EXPORT,
)
def set_default_layout(
    builder: Builder, actor: Actor, *, survey_id: str, layout_id: str | None = None
) -> ResultsLayoutsView:
    """Make one of the survey's layouts its default (``None`` clears it)."""
    ctx = builder._locate(actor, survey_id, Action.SURVEY_EXPORT)
    if layout_id is not None and not isinstance(layout_id, str):
        raise NotFoundError("Layout not found.")
    _store_call(builder.store.set_default_results_layout, ctx, survey_id, layout_id)
    return list_layouts(builder, actor, survey_id=survey_id)
