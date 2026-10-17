"""``GET /api/me``: who the request acts as, and in which labs (planning/pages-split.md).

The builder pages use it to pick a lab and show a name. Everything comes from the host's
identity (the provider), with the display name falling back to the last one the host sent
(``principals``). It carries no session or CSRF details: sign-in belongs to the host.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from .common import Auth, Services, errors


class LabMembership(BaseModel):
    tenantId: str
    role: str


class Identity(BaseModel):
    userId: str
    displayName: str | None = None
    memberships: list[LabMembership]


router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me", operation_id="getIdentity", responses=errors(401))
def get_me(authed: Auth, services: Services) -> Identity:
    name = authed.display_name or services.display_name(authed.actor.user_id)
    return Identity(
        userId=authed.actor.user_id,
        displayName=name,
        memberships=[
            LabMembership(tenantId=t, role=str(r)) for t, r in sorted(authed.actor.roles.items())
        ],
    )
