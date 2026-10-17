"""Saved results layouts (task V5a, planning/results-viewer.md V-D9). Thin: HTTP <-> the
``survey.results_layout*`` app commands in ``osp_app.results_layouts``.

A layout is the Results page's settings for one survey (query, chart per card, order,
hidden cards, bins, captions): never response data. Layouts are shared by the lab and
need ``survey.export`` (owner, editor; viewers 403, other labs 404), the same as the
results query. One layout per survey may be the default. Every change is audited.

- ``GET    /api/surveys/{id}/results/layouts``              list + the default
- ``POST   /api/surveys/{id}/results/layouts``              save one (201; ``isDefault``)
- ``PUT    /api/surveys/{id}/results/layouts/default``      pick the default (or null)
- ``GET    /api/surveys/{id}/results/layouts/{layout_id}``
- ``PATCH  /api/surveys/{id}/results/layouts/{layout_id}``  rename and/or replace settings
- ``DELETE /api/surveys/{id}/results/layouts/{layout_id}``  204
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from osp_app import LayoutSettings, ResultsLayoutsView
from osp_store import StoredResultsLayout
from pydantic import BaseModel, ConfigDict, Field

from .common import Auth, Services, errors

router = APIRouter(prefix="/api/surveys", tags=["results"])


class ResultsLayoutOut(BaseModel):
    id: str
    surveyId: str
    name: str
    settings: LayoutSettings
    isDefault: bool = Field(description="The survey's default layout (at most one)")
    createdBy: str
    createdAt: datetime
    updatedBy: str
    updatedAt: datetime


class ResultsLayoutList(BaseModel):
    surveyId: str
    layouts: list[ResultsLayoutOut] = Field(description="By name")
    defaultLayoutId: str | None


class CreateResultsLayoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200, description="Unique within the survey")
    settings: LayoutSettings
    isDefault: bool = Field(False, description="Also make it the survey's default")


class UpdateResultsLayoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, min_length=1, max_length=200)
    settings: LayoutSettings | None = Field(None, description="Replaces the whole settings")


class SetDefaultResultsLayoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layoutId: str | None = Field(description="A layout of this survey, or null for no default")


def _out(lay: StoredResultsLayout) -> ResultsLayoutOut:
    return ResultsLayoutOut(
        id=lay.id,
        surveyId=lay.survey_id,
        name=lay.name,
        settings=lay.settings,
        isDefault=lay.is_default,
        createdBy=lay.created_by,
        createdAt=lay.created_at,
        updatedBy=lay.updated_by,
        updatedAt=lay.updated_at,
    )


def _list(v: ResultsLayoutsView) -> ResultsLayoutList:
    return ResultsLayoutList(
        surveyId=v.survey_id,
        layouts=[_out(lay) for lay in v.layouts],
        defaultLayoutId=v.default_layout_id,
    )


def _settings(s: LayoutSettings | None) -> dict | None:
    return None if s is None else s.model_dump(mode="json", by_alias=True)


@router.get(
    "/{survey_id}/results/layouts",
    operation_id="listResultsLayouts",
    responses=errors(401, 403, 404, 422),
)
def list_layouts(survey_id: str, auth: Auth, services: Services) -> ResultsLayoutList:
    """The survey's saved layouts and which one is the default (survey.export)."""
    return _list(services.builder.run("survey.results_layouts", auth.actor, survey_id=survey_id))


@router.post(
    "/{survey_id}/results/layouts",
    operation_id="createResultsLayout",
    status_code=201,
    responses=errors(401, 403, 404, 409, 422),
)
def create_layout(
    survey_id: str, body: CreateResultsLayoutRequest, auth: Auth, services: Services
) -> ResultsLayoutOut:
    """Save a layout (survey.export; audited). A duplicate name in the survey is 409."""
    return _out(
        services.builder.run(
            "survey.results_layout_create",
            auth.actor,
            survey_id=survey_id,
            name=body.name,
            settings=_settings(body.settings),
            default=body.isDefault,
        )
    )


@router.put(
    "/{survey_id}/results/layouts/default",
    operation_id="setDefaultResultsLayout",
    responses=errors(401, 403, 404, 422),
)
def set_default_layout(
    survey_id: str, body: SetDefaultResultsLayoutRequest, auth: Auth, services: Services
) -> ResultsLayoutList:
    """Make one of the survey's layouts the default, or clear it (survey.export; audited)."""
    return _list(
        services.builder.run(
            "survey.results_layout_set_default",
            auth.actor,
            survey_id=survey_id,
            layout_id=body.layoutId,
        )
    )


@router.get(
    "/{survey_id}/results/layouts/{layout_id}",
    operation_id="getResultsLayout",
    responses=errors(401, 403, 404, 422),
)
def get_layout(survey_id: str, layout_id: str, auth: Auth, services: Services) -> ResultsLayoutOut:
    return _out(
        services.builder.run(
            "survey.results_layout_get", auth.actor, survey_id=survey_id, layout_id=layout_id
        )
    )


@router.patch(
    "/{survey_id}/results/layouts/{layout_id}",
    operation_id="updateResultsLayout",
    responses=errors(401, 403, 404, 409, 422),
)
def update_layout(
    survey_id: str,
    layout_id: str,
    body: UpdateResultsLayoutRequest,
    auth: Auth,
    services: Services,
) -> ResultsLayoutOut:
    """Rename a layout and/or replace its settings (survey.export; audited)."""
    return _out(
        services.builder.run(
            "survey.results_layout_update",
            auth.actor,
            survey_id=survey_id,
            layout_id=layout_id,
            name=body.name,
            settings=_settings(body.settings),
        )
    )


@router.delete(
    "/{survey_id}/results/layouts/{layout_id}",
    operation_id="deleteResultsLayout",
    status_code=204,
    responses=errors(401, 403, 404, 422),
)
def delete_layout(survey_id: str, layout_id: str, auth: Auth, services: Services) -> None:
    """Delete a layout; if it was the default, the survey has none (survey.export; audited)."""
    services.builder.run(
        "survey.results_layout_delete", auth.actor, survey_id=survey_id, layout_id=layout_id
    )
