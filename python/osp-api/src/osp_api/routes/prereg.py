"""Preregistration export (task OS1). Thin: HTTP <-> the ``survey.prereg_*`` commands.

- ``GET …/prereg-bundle``: the bundle (zip), ``survey.read``; ``?repro=false`` leaves the
  nested reproducibility package out.
- ``GET …/prereg-summary``: the readable summary page alone (HTML), ``survey.read``.
- ``POST …/prereg-bundle/osf``: build and upload to an OSF project with the token in the
  request body (never stored; 502 when OSF refuses or is unreachable), ``survey.publish``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from .common import Auth, Services, errors

router = APIRouter(prefix="/api/surveys", tags=["surveys"])


class OsfUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(
        min_length=8,
        max_length=512,
        description="An OSF personal access token with the osf.full_write scope. Used for "
        "this request only, never stored.",
        repr=False,
    )
    node: str = Field(
        min_length=3, max_length=200, description="The OSF project id (e.g. ab3de) or its URL"
    )


class OsfUploadedFile(BaseModel):
    name: str
    size: int | None = None
    url: str | None = None


class OsfUploadResponse(BaseModel):
    nodeId: str
    nodeTitle: str
    nodeUrl: str
    nodePublic: bool
    user: str = Field(description="The OSF user the token belongs to")
    files: list[OsfUploadedFile]
    checksum: str = Field(description="The survey version checksum, for the registration form")


def _attachment(r, media_type: str) -> Response:
    return Response(
        r.content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{r.filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/{survey_id}/versions/{version}/prereg-bundle",
    operation_id="preregBundle",
    response_class=Response,
    responses={
        200: {
            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
            "description": "The preregistration bundle (deterministic zip, no participant data)",
        },
        **errors(401, 403, 404, 422),
    },
)
def prereg_bundle(
    survey_id: str,
    version: Annotated[int, Path(ge=1, description="Published version number")],
    auth: Auth,
    services: Services,
    repro: Annotated[
        bool, Query(description="Nest the version's reproducibility package (no data)")
    ] = True,
) -> Response:
    r = services.builder.run(
        "survey.prereg_bundle", auth.actor, survey_id=survey_id, version=version, repro=repro
    )
    return _attachment(r, r.media_type)


@router.get(
    "/{survey_id}/versions/{version}/prereg-summary",
    operation_id="preregSummary",
    response_class=Response,
    responses={
        200: {
            "content": {"text/html": {"schema": {"type": "string"}}},
            "description": "The human-readable preregistration summary (self-contained HTML)",
        },
        **errors(401, 403, 404, 422),
    },
)
def prereg_summary(
    survey_id: str,
    version: Annotated[int, Path(ge=1, description="Published version number")],
    auth: Auth,
    services: Services,
) -> Response:
    r = services.builder.run(
        "survey.prereg_bundle", auth.actor, survey_id=survey_id, version=version, format="html"
    )
    return Response(
        r.content,
        media_type=r.media_type,
        headers={
            "Content-Disposition": f'inline; filename="{r.filename}"',
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        },
    )


@router.post(
    "/{survey_id}/versions/{version}/prereg-bundle/osf",
    operation_id="preregUploadOsf",
    response_model=OsfUploadResponse,
    responses=errors(401, 403, 404, 422, 502),
)
def prereg_upload_osf(
    survey_id: str,
    version: Annotated[int, Path(ge=1, description="Published version number")],
    body: OsfUploadRequest,
    auth: Auth,
    services: Services,
) -> OsfUploadResponse:
    r = services.builder.run(
        "survey.prereg_osf_upload",
        auth.actor,
        survey_id=survey_id,
        version=version,
        token=body.token,
        node=body.node,
        transport=services.osf_transport,
    )
    return OsfUploadResponse(
        nodeId=r.node_id,
        nodeTitle=r.node_title,
        nodeUrl=r.node_url,
        nodePublic=r.node_public,
        user=r.user,
        files=[OsfUploadedFile(**f) for f in r.files],
        checksum=r.checksum,
    )
