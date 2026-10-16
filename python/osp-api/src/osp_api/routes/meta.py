"""Schemas the builder renders from: the op catalogue, property schemas, the survey
and theme JSON Schemas. Static data, but behind sign-in like every builder route."""

from __future__ import annotations

from functools import cache
from typing import Any

from fastapi import APIRouter, Response
from osp_ops import op_catalogue
from osp_spec import json_schema
from osp_spec.property_schema import property_schemas_json
from osp_spec.theme import theme_json_schema
from pydantic import BaseModel, Field

from .common import Auth, errors


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
