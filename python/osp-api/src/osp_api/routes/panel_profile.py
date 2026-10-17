"""Lab property panel profile (task B21, planning/property-profiles.md §3). Thin:
HTTP <-> ``osp_app.panel_profile``.

Every route is tenant-scoped: the lab is ``tenantId`` (query or body), or the caller's
only lab. Members may read the profile and the effective schemas; owners may set and clear
it. The builder renders its property panel from ``GET /api/panel-profile/schemas`` (the
stock ``/api/meta/property-schemas`` with the lab's profile applied).

- ``GET    /api/panel-profile``            the profile (null: the stock panel)
- ``PUT    /api/panel-profile``            replace it (422 with diagnostics when invalid)
- ``DELETE /api/panel-profile``            back to the stock panel (204)
- ``GET    /api/panel-profile/schemas``    the effective property schemas
- ``GET    /api/panel-profile/check/{id}`` a survey's custom values judged by the profile
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter
from osp_app import PanelProfileView
from osp_spec import Diagnostic
from pydantic import BaseModel, ConfigDict, Field

from .common import Auth, Services, errors

router = APIRouter(prefix="/api/panel-profile", tags=["panel-profile"])

_TENANT = Field(None, description="The lab; needed only if you belong to several labs")


class PanelProfileOut(BaseModel):
    tenantId: str
    profile: dict[str, Any] | None = Field(
        description="The profile document (osp-panel-profile/0.1); null means the stock panel"
    )
    diagnostics: list[Diagnostic] = Field(
        description="Parts of the profile that do not apply (warnings); the stock schema "
        "stands in for them"
    )
    canManage: bool = Field(description="The caller may set and clear the profile (owner)")
    updatedBy: str | None = None
    updatedAt: datetime | None = None


class SetPanelProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: dict[str, Any] = Field(description="The whole profile document; replaces it")
    tenantId: str | None = _TENANT


def _out(v: PanelProfileView) -> PanelProfileOut:
    return PanelProfileOut(
        tenantId=v.tenant_id,
        profile=v.profile,
        diagnostics=v.diagnostics,
        canManage=v.can_manage,
        updatedBy=v.updated_by,
        updatedAt=v.updated_at,
    )


@router.get("", operation_id="getPanelProfile", responses=errors(401, 403, 422))
def get_profile(auth: Auth, services: Services, tenantId: str | None = None) -> PanelProfileOut:
    return _out(services.builder.run("profile.get", auth.actor, tenant_id=tenantId))


@router.put("", operation_id="setPanelProfile", responses=errors(401, 403, 404, 422))
def set_profile(body: SetPanelProfileRequest, auth: Auth, services: Services) -> PanelProfileOut:
    return _out(
        services.builder.run(
            "profile.set", auth.actor, profile=body.profile, tenant_id=body.tenantId
        )
    )


@router.delete(
    "", operation_id="clearPanelProfile", status_code=204, responses=errors(401, 403, 422)
)
def clear_profile(auth: Auth, services: Services, tenantId: str | None = None) -> None:
    services.builder.run("profile.clear", auth.actor, tenant_id=tenantId)


@router.get("/schemas", operation_id="getEffectivePropertySchemas", responses=errors(401, 403, 422))
def effective_schemas(
    auth: Auth, services: Services, tenantId: str | None = None
) -> dict[str, Any]:
    """The property schemas with the lab's profile applied: the shape of
    ``GET /api/meta/property-schemas`` plus ``groupLabels``, ``defaults`` (per question
    type, for new questions), ``profileApplied`` and the profile's ``diagnostics``."""
    return services.builder.run("profile.schemas", auth.actor, tenant_id=tenantId)


@router.get("/check/{survey_id}", operation_id="checkCustomValues", responses=errors(401, 403, 404))
def check_survey(survey_id: str, auth: Auth, services: Services) -> list[Diagnostic]:
    """Warnings about a survey draft's custom values judged by its lab's profile."""
    return services.builder.run("profile.check", auth.actor, survey_id=survey_id)
