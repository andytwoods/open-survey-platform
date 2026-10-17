"""Preregistration export commands (task OS1).

- ``survey.prereg_bundle``: the bundle (zip) of one published version, or its summary
  page alone (``format="html"``). It holds the survey definition and checksum, the
  codebook, the design documents and (by default) the data-free reproducibility package.
  No participant data, so ``survey.read`` is enough: a viewer can download it.
- ``survey.prereg_osf_upload``: build the bundle and put its files into an OSF project
  with a personal access token the researcher supplies for this one call. Needs
  ``survey.publish`` (owner, editor): it discloses the design outside the lab. The token
  is never stored, never logged and never echoed; the audit entry names the project and
  the files, nothing else.

The builder is pure (``osp_targets.prereg``); this module reads the store and the kit,
and talks to OSF through ``osp_app.osf``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from osp_targets.data import ExportError
from osp_targets.prereg import PreregBundle, PreregInputs, build_prereg_bundle

from .auth.permissions import Action, Actor
from .builder import Builder, ExportResult
from .commands import command
from .errors import InvalidRequest, Rejected
from .osf import OsfClient, Transport, check_token, node_id_of
from .repro import build_for_version, published_version, tool_versions

ZIP_MEDIA = "application/zip"
HTML_MEDIA = "text/html; charset=utf-8"


@dataclass(frozen=True)
class PreregDownload(ExportResult):
    media_type: str = ZIP_MEDIA


@dataclass(frozen=True)
class OsfUploadResult:
    node_id: str
    node_title: str
    node_url: str
    node_public: bool
    user: str
    files: list[dict[str, Any]]  # {name, size, url}
    checksum: str  # the survey version checksum, for the registration form


def _bundle(
    builder: Builder, actor: Actor, survey_id: str, version: object, repro: bool
) -> PreregBundle:
    ctx = builder._locate(actor, survey_id, Action.SURVEY_READ)
    v = published_version(builder, ctx, survey_id, version)
    plan_checksum = None
    package = None
    if repro:
        pkg = build_for_version(builder, ctx, survey_id, v)
        package = pkg.content
    meta = v.meta if isinstance(v.meta, dict) else {}
    if isinstance(meta.get("planChecksum"), str):
        plan_checksum = meta["planChecksum"]
    try:
        return build_prereg_bundle(
            PreregInputs(
                survey=v.body,
                survey_id=survey_id,
                version=v.number,
                survey_checksum=v.checksum,
                plan_checksum=plan_checksum,
                versions=tool_versions(),
                repro_package=package,
            )
        )
    except ExportError as exc:
        raise Rejected(str(exc), exc.diagnostics) from exc


@command("survey.prereg_bundle", label="Preregistration bundle", action=Action.SURVEY_READ)
def prereg_bundle(
    builder: Builder,
    actor: Actor,
    *,
    survey_id: str,
    version: int,
    repro: bool = True,
    format: Literal["zip", "html"] = "zip",
) -> PreregDownload:
    if format not in ("zip", "html"):
        raise InvalidRequest("format must be zip or html")
    b = _bundle(builder, actor, survey_id, version, repro is True and format == "zip")
    if format == "html":
        name = b.filename.removesuffix(".zip") + "-summary.html"
        return PreregDownload(b.summary_html, name, media_type=HTML_MEDIA)
    return PreregDownload(b.content, b.filename)


@command(
    "survey.prereg_osf_upload", label="Upload preregistration to OSF", action=Action.SURVEY_PUBLISH
)
def prereg_osf_upload(
    builder: Builder,
    actor: Actor,
    *,
    survey_id: str,
    version: int,
    token: str,
    node: str,
    transport: Transport | None = None,
) -> OsfUploadResult:
    """Validate the inputs first (so a bad id never costs a network call), then: who the
    token is, the project, build the bundle, upload the zip and the summary page."""
    token = check_token(token)
    node_id = node_id_of(node)
    ctx = builder._locate(actor, survey_id, Action.SURVEY_PUBLISH)
    published_version(builder, ctx, survey_id, version)  # 404 before any network call
    b = _bundle(builder, actor, survey_id, version, True)
    client = OsfClient(token, transport=transport)
    user = client.me()
    project = client.node(node_id)
    summary_name = b.filename.removesuffix(".zip") + "-summary.html"
    uploaded = [
        client.upload(project.id, b.filename, b.content),
        client.upload(project.id, summary_name, b.summary_html),
    ]
    files = [{"name": f.name, "size": f.size, "url": f.url} for f in uploaded]
    builder.store.audit(
        ctx,
        "prereg.osf_upload",
        "survey",
        survey_id,
        {
            "version": version,
            "node": project.id,
            "files": [f.name for f in uploaded],
            "osfUser": user.id,
            "checksum": b.manifest["survey"]["checksum"],
        },
    )
    return OsfUploadResult(
        node_id=project.id,
        node_title=project.title,
        node_url=project.url,
        node_public=project.public,
        user=user.name or user.id,
        files=files,
        checksum=b.manifest["survey"]["checksum"],
    )


__all__ = ["OsfUploadResult", "PreregDownload", "prereg_bundle", "prereg_osf_upload"]
