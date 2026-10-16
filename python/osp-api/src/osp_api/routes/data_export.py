"""Response data export (task M2). Thin: HTTP <-> ``osp_app.data_export`` commands.

Permission ``survey.export`` (owner, editor). Viewers get 403, other labs 404.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response

from .common import Auth, Services, errors

router = APIRouter(prefix="/api/surveys", tags=["surveys"])

VersionParam = Annotated[
    int | None,
    Query(ge=1, description="One published version; omitted: all versions combined"),
]
MultiParam = Annotated[
    Literal["columns", "codes"],
    Query(description="multi answers: one 0/1 column per choice, or codes in one cell"),
]
StateParam = Annotated[
    bool, Query(alias="stateColumns", description="Add <var>__state columns (default on)")
]


def _download(content: bytes, filename: str, media_type: str) -> Response:
    return Response(
        content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/{survey_id}/export/responses",
    operation_id="exportResponses",
    response_class=Response,
    responses={
        200: {
            "content": {
                "text/csv": {"schema": {"type": "string"}},
                "application/json": {"schema": {"type": "object"}},
            },
            "description": "Responses as CSV (empty cell + <var>__state) or JSON",
        },
        **errors(401, 403, 404, 422),
    },
)
def export_responses(
    survey_id: str,
    auth: Auth,
    services: Services,
    format: Literal["csv", "json"] = "csv",
    version: VersionParam = None,
    state_columns: StateParam = True,
    multi: MultiParam = "columns",
    excel: Annotated[
        bool, Query(description="CSV for Excel: UTF-8 byte order mark (formulas always escaped)")
    ] = False,
    events: Annotated[bool, Query(description="JSON: include each event log")] = False,
) -> Response:
    r = services.builder.run(
        "survey.export_responses",
        auth.actor,
        survey_id=survey_id,
        format=format,
        version=version,
        state_columns=state_columns,
        multi=multi,
        excel=excel,
        events=events,
    )
    return _download(r.content, r.filename, r.media_type)


@router.get(
    "/{survey_id}/export/codebook",
    operation_id="exportCodebook",
    response_class=Response,
    responses={
        200: {
            "content": {
                "text/markdown": {"schema": {"type": "string"}},
                "application/json": {"schema": {"type": "object"}},
            },
            "description": "Codebook as Markdown or JSON",
        },
        **errors(401, 403, 404, 422),
    },
)
def export_codebook(
    survey_id: str,
    auth: Auth,
    services: Services,
    format: Literal["md", "json"] = "md",
    version: VersionParam = None,
    state_columns: StateParam = True,
    multi: MultiParam = "columns",
) -> Response:
    r = services.builder.run(
        "survey.export_codebook",
        auth.actor,
        survey_id=survey_id,
        format=format,
        version=version,
        state_columns=state_columns,
        multi=multi,
    )
    return _download(r.content, r.filename, r.media_type)
