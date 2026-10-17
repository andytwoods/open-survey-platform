"""Lab theme library (task B12, runtime-design §6a). Thin: HTTP <-> ``osp_app.themes``.

Every route is tenant-scoped: the lab is ``tenantId`` (query or body), or the caller's only
lab. Members may list and read; owners and editors may save, change, delete and pick the lab
default. A survey's own theme is set with the ``set_theme`` op (``/api/surveys/{id}/ops``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter
from osp_app import LabTheme, ThemeLibraryView
from osp_spec import Diagnostic
from pydantic import BaseModel, ConfigDict, Field

from .common import Auth, Services, errors

router = APIRouter(prefix="/api/themes", tags=["themes"])

_TENANT = Field(None, description="The lab; needed only if you belong to several labs")


class LabThemeOut(BaseModel):
    id: str
    tenantId: str
    name: str
    theme: dict[str, Any] = Field(description="The theme document (osp-theme/0.1)")
    isDefault: bool = Field(description="This is the lab default theme")
    diagnostics: list[Diagnostic] = Field(
        description="Contrast guard findings; errors block publishing with this theme"
    )
    createdBy: str
    createdAt: datetime
    updatedBy: str
    updatedAt: datetime


class ThemeLibrary(BaseModel):
    tenantId: str
    themes: list[LabThemeOut]
    defaultThemeId: str | None = Field(
        description="The lab default: surveys without their own theme publish with it"
    )
    canManage: bool = Field(description="The caller may save, change and delete themes")


class CreateThemeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    theme: dict[str, Any]
    tenantId: str | None = _TENANT


class UpdateThemeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, min_length=1, max_length=200)
    theme: dict[str, Any] | None = None
    tenantId: str | None = _TENANT


class SetDefaultThemeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    themeId: str | None = Field(description="A library theme id, or null for no lab default")
    tenantId: str | None = _TENANT


def _out(t: LabTheme) -> LabThemeOut:
    s = t.theme
    return LabThemeOut(
        id=s.id,
        tenantId=s.tenant_id,
        name=s.name,
        theme=s.body,
        isDefault=t.is_default,
        diagnostics=t.diagnostics,
        createdBy=s.created_by,
        createdAt=s.created_at,
        updatedBy=s.updated_by,
        updatedAt=s.updated_at,
    )


def _library(v: ThemeLibraryView) -> ThemeLibrary:
    return ThemeLibrary(
        tenantId=v.tenant_id,
        themes=[_out(t) for t in v.themes],
        defaultThemeId=v.default_theme_id,
        canManage=v.can_manage,
    )


@router.get("", operation_id="listThemes", responses=errors(401, 403, 422))
def list_themes(auth: Auth, services: Services, tenantId: str | None = None) -> ThemeLibrary:
    return _library(services.builder.run("theme.list", auth.actor, tenant_id=tenantId))


@router.post("", operation_id="createTheme", status_code=201, responses=errors(401, 403, 409, 422))
def create_theme(body: CreateThemeRequest, auth: Auth, services: Services) -> LabThemeOut:
    return _out(
        services.builder.run(
            "theme.create", auth.actor, name=body.name, theme=body.theme, tenant_id=body.tenantId
        )
    )


@router.put("/default", operation_id="setDefaultTheme", responses=errors(401, 403, 404, 422))
def set_default(body: SetDefaultThemeRequest, auth: Auth, services: Services) -> ThemeLibrary:
    return _library(
        services.builder.run(
            "theme.set_default", auth.actor, theme_id=body.themeId, tenant_id=body.tenantId
        )
    )


@router.get("/{theme_id}", operation_id="getTheme", responses=errors(401, 403, 404, 422))
def get_theme(
    theme_id: str, auth: Auth, services: Services, tenantId: str | None = None
) -> LabThemeOut:
    return _out(
        services.builder.run("theme.get", auth.actor, theme_id=theme_id, tenant_id=tenantId)
    )


@router.patch("/{theme_id}", operation_id="updateTheme", responses=errors(401, 403, 404, 409, 422))
def update_theme(
    theme_id: str, body: UpdateThemeRequest, auth: Auth, services: Services
) -> LabThemeOut:
    return _out(
        services.builder.run(
            "theme.update",
            auth.actor,
            theme_id=theme_id,
            name=body.name,
            theme=body.theme,
            tenant_id=body.tenantId,
        )
    )


@router.delete(
    "/{theme_id}",
    operation_id="deleteTheme",
    status_code=204,
    responses=errors(401, 403, 404, 422),
)
def delete_theme(
    theme_id: str, auth: Auth, services: Services, tenantId: str | None = None
) -> None:
    services.builder.run("theme.delete", auth.actor, theme_id=theme_id, tenant_id=tenantId)
