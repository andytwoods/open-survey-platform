"""Reproducibility package (task M3). Thin: HTTP <-> the ``survey.repro_package`` command.

``survey.read`` gets the package without participant data; ``?data=true`` adds the
codebook and responses and needs ``survey.export`` (403 otherwise, never a silent
data-free answer). Other labs get 404.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response

from .common import Auth, Services, errors

router = APIRouter(prefix="/api/surveys", tags=["surveys"])


@router.get(
    "/{survey_id}/versions/{version}/repro-package",
    operation_id="reproPackage",
    response_class=Response,
    responses={
        200: {
            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
            "description": "The reproducibility package (deterministic zip)",
        },
        **errors(401, 403, 404, 422),
    },
)
def repro_package(
    survey_id: str,
    version: Annotated[int, Path(ge=1, description="Published version number")],
    auth: Auth,
    services: Services,
    data: Annotated[
        bool,
        Query(description="Include the codebook and responses (needs export permission)"),
    ] = False,
) -> Response:
    r = services.builder.run(
        "survey.repro_package", auth.actor, survey_id=survey_id, version=version, data=data
    )
    return Response(
        r.content,
        media_type=r.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{r.filename}"',
            "Cache-Control": "no-store",
        },
    )
