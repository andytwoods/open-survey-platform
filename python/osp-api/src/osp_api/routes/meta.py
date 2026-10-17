"""Schemas the builder renders from: the op catalogue, property schemas, the survey
and theme JSON Schemas. Static data, but behind sign-in like every builder route."""

from __future__ import annotations

from functools import cache
from typing import Any, Literal, get_args

from fastapi import APIRouter, Response
from osp_ops import op_catalogue
from osp_spec import json_schema
from osp_spec.model import Retention
from osp_spec.property_schema import property_schemas_json
from osp_spec.theme import theme_json_schema
from pydantic import BaseModel, Field

from ..static_files import media_sources
from .common import Auth, Services, errors


class OpCatalogueEntry(BaseModel):
    id: str
    label: str
    area: str
    description: str
    paramsSchema: dict[str, Any] = Field(description="JSON Schema (2020-12) of the params")


@cache
def _catalogue() -> list[OpCatalogueEntry]:
    return [OpCatalogueEntry.model_validate(e) for e in op_catalogue()]


router = APIRouter(prefix="/api/meta", tags=["meta"])

_CACHE = "private, max-age=300"


@router.get("/ops", operation_id="getOpCatalogue", responses=errors(401))
def ops(_auth: Auth, response: Response) -> list[OpCatalogueEntry]:
    response.headers["Cache-Control"] = _CACHE
    return _catalogue()


@router.get("/property-schemas", operation_id="getPropertySchemas", responses=errors(401))
def property_schemas(_auth: Auth, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = _CACHE
    return property_schemas_json()


@router.get("/survey-schema", operation_id="getSurveySchema", responses=errors(401))
def survey_schema(_auth: Auth, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = _CACHE
    return json_schema()


@router.get("/theme-schema", operation_id="getThemeSchema", responses=errors(401))
def theme_schema(_auth: Auth, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = _CACHE
    return theme_json_schema()


# -- retention (settings.retention, required at publish) ---------------------------------

_RETENTION_TEXT: dict[str, tuple[str, str, str | None]] = {
    "days-after-close": (
        "Delete a set number of days after the survey closes",
        "Responses are deleted `days` days after the survey is closed.",
        "days",
    ),
    "after-date": (
        "Delete after a date",
        "Responses are deleted after the calendar date `until` (YYYY-MM-DD).",
        "until",
    ),
    "indefinite": (
        "Keep until I delete it",
        "Responses are kept until a researcher deletes them. An explicit choice.",
        None,
    ),
}


class RetentionKind(BaseModel):
    kind: str
    label: str
    description: str
    field: Literal["days", "until"] | None = Field(
        description="The extra field this kind needs: `days` (integer >= 0), "
        "`until` (date) or none."
    )


class RetentionOptions(BaseModel):
    required: bool = Field(description="Publishing is refused without settings.retention.")
    pointer: str = Field(description="Where the policy lives in the survey document.")
    kinds: list[RetentionKind]


@cache
def _retention() -> RetentionOptions:
    kinds = get_args(Retention.model_fields["kind"].annotation)
    return RetentionOptions(
        required=True,
        pointer="/settings/retention",
        kinds=[
            RetentionKind(
                kind=k,
                label=_RETENTION_TEXT[k][0],
                description=_RETENTION_TEXT[k][1],
                field=_RETENTION_TEXT[k][2],  # type: ignore[arg-type]
            )
            for k in kinds
        ],
    )


@router.get("/retention", operation_id="getRetentionOptions", responses=errors(401))
def retention(_auth: Auth, response: Response) -> RetentionOptions:
    """The allowed `settings.retention` policies (the builder's retention control)."""
    response.headers["Cache-Control"] = _CACHE
    return _retention()


# -- media (planning/media.md §2.3) --------------------------------------------------------


class MediaCsp(BaseModel):
    imgSrc: str = Field(description="The `img-src` source list the participant page needs.")
    mediaSrc: str = Field(description="The `media-src` source list the participant page needs.")


class MediaPolicy(BaseModel):
    checked: bool = Field(
        description="Whether this deployment checks media origins at all. False: the "
        "in-process host configured none; any https URL validates."
    )
    allowedOrigins: list[str] = Field(
        description="Exact origins survey media may be loaded from, besides the page's own "
        "(OSP_MEDIA_ORIGINS). Same-origin paths (`/media/…`) are always allowed."
    )
    csp: MediaCsp = Field(
        description="What a host that serves the participant `index.html` or the preview "
        "frame itself writes into those pages' Content-Security-Policy."
    )


@router.get("/media-policy", operation_id="getMediaPolicy", responses=errors(401))
def media_policy(_auth: Auth, services: Services, response: Response) -> MediaPolicy:
    """Where survey media may come from in this deployment, and the CSP directives that
    allow it (planning/media.md §2.3)."""
    response.headers["Cache-Control"] = _CACHE
    origins = services.builder.media_origins
    sources = media_sources(origins or ())
    return MediaPolicy(
        checked=origins is not None,
        allowedOrigins=list(origins or ()),
        csp=MediaCsp(imgSrc=sources["img-src"], mediaSrc=sources["media-src"]),
    )
