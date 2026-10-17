"""Reproducibility package command (task M3): one zip per published version.

- Default: the survey JSON, the runtime plan as served, both checksums, the XLSForm and
  LSS exports with diagnostics, the replay kit, README and LICENSE. No participant data,
  so ``survey.read`` is enough (a viewer can download it for review).
- ``data=True``: also the codebook and the responses (CSV, JSON with event logs). Needs
  ``survey.export``, like the data export (M2); without it the request is refused (403),
  never silently answered without data.

This module does the I/O the pure builder (``osp_targets.repro``) may not: it reads the
kit files, the vendored ``osp_engine/random.py`` and the engine bundle. The bundle is
``web/engine/dist/engine.js`` in this repository (``make engine-bundle``), or
``OSP_ENGINE_BUNDLE``; without one the package ships no ``replay.mjs`` and says so.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as dist_version
from pathlib import Path
from typing import Any

import osp_engine.random
import osp_targets.repro
from osp_runtime.plan import ENGINE_VERSION, PLAN_VERSION, compile_survey, runtime_config
from osp_spec import SPEC_VERSION
from osp_store import ParticipantStore, SystemContext, TenantContext, Version
from osp_targets.data import ExportError
from osp_targets.repro import ReproData, ReproInputs, ReproKit, ReproPackage, build_repro_package

from .auth.permissions import Action, Actor, Resource, can
from .builder import Builder, ExportResult
from .commands import command
from .data_export import _save_mode, _stored
from .errors import Forbidden, InvalidRequest, NotFoundError, Rejected

ZIP_MEDIA = "application/zip"
REPO = Path(__file__).resolve().parents[4]
DEFAULT_BUNDLE = REPO / "web" / "engine" / "dist" / "engine.js"
KIT_DIR = Path(osp_targets.repro.__file__).resolve().parent / "kit"
SYSTEM = SystemContext("system:repro")


@dataclass(frozen=True)
class ReproDownload(ExportResult):
    media_type: str = ZIP_MEDIA


def engine_bundle() -> Path:
    return Path(os.environ.get("OSP_ENGINE_BUNDLE") or DEFAULT_BUNDLE)


def load_kit(bundle: Path | None = None) -> ReproKit:
    """Read the replay kit from disk (the builder itself is pure)."""
    path = bundle or engine_bundle()
    return ReproKit(
        replay_py=(KIT_DIR / "replay.py").read_bytes(),
        replay_mjs=(KIT_DIR / "replay.mjs").read_bytes(),
        random_py=Path(osp_engine.random.__file__).read_bytes(),
        engine_js=path.read_bytes() if path.is_file() else None,
    )


def _engine_package_version(bundle: Path) -> str:
    """``@osp/engine``'s version: the bundle's banner, else its package.json."""
    try:
        first = bundle.read_text(encoding="utf-8").split("\n", 1)[0]
        if first.startswith("/*! @osp/engine "):
            return first.split()[2]
    except OSError:
        pass
    try:
        pkg = json.loads((REPO / "web" / "engine" / "package.json").read_text("utf-8"))
        return str(pkg["version"])
    except OSError, ValueError, KeyError:
        return "unknown"


def _dist(name: str) -> str:
    try:
        return dist_version(name)
    except PackageNotFoundError:
        return "unknown"


def tool_versions(bundle: Path | None = None) -> dict[str, str]:
    return {
        "spec": SPEC_VERSION,
        "platform (osp-app)": _dist("osp-app"),
        "osp-targets": _dist("osp-targets"),
        "osp-runtime": _dist("osp-runtime"),
        "osp-engine (Python PRNG)": _dist("osp-engine"),
        "@osp/engine (engine.js)": _engine_package_version(bundle or engine_bundle()),
        "runtime plan (compiler)": PLAN_VERSION,
        "engine API (compiler)": ENGINE_VERSION,
    }


def _plan(builder: Builder, tenant_id: str, v: Version) -> tuple[Mapping[str, Any], str]:
    """The plan participants ran (the stored publication), else a recompiled one."""
    meta = v.meta if isinstance(v.meta, Mapping) else {}
    slug, checksum = meta.get("slug"), meta.get("planChecksum")
    if isinstance(slug, str) and isinstance(checksum, str):
        pub = ParticipantStore(builder.store).find_publication(SYSTEM, slug, checksum)
        if (
            pub is not None
            and pub.tenant_id == tenant_id
            and pub.version_id == v.id
            and isinstance(pub.plan, Mapping)
        ):
            return pub.plan, "published"
    plan, diags = compile_survey(v.body)
    if plan is None:
        raise Rejected("The runtime plan can't be built for this version.", diags)
    return plan, "recompiled"


def published_version(
    builder: Builder, ctx: TenantContext, survey_id: str, version: object
) -> Version:
    """The stored version ``version`` of ``survey_id`` (already located), or an error."""
    if type(version) is not int or version < 1:
        raise InvalidRequest("version must be a positive integer")
    v = next((x for x in builder.store.list_versions(ctx, survey_id) if x.number == version), None)
    if v is None:
        raise NotFoundError("No such published version.")
    if not isinstance(v.body, Mapping):
        raise Rejected("The stored survey version is not an object.", [])
    return v


def build_for_version(
    builder: Builder,
    ctx: TenantContext,
    survey_id: str,
    v: Version,
    *,
    data: ReproData | None = None,
) -> ReproPackage:
    """The reproducibility package of one stored version (shared with the preregistration
    bundle, which nests the data-free package)."""
    plan, source = _plan(builder, ctx.tenant_id, v)
    meta = v.meta if isinstance(v.meta, Mapping) else {}
    config = meta.get("runtimeConfig")
    if not isinstance(config, Mapping):
        config = runtime_config(plan)
    bundle = engine_bundle()
    try:
        return build_repro_package(
            ReproInputs(
                survey=v.body,
                survey_id=survey_id,
                version=v.number,
                survey_checksum=v.checksum,
                plan=plan,
                kit=load_kit(bundle),
                versions=tool_versions(bundle),
                runtime_config=config,
                plan_source=source,
                data=data,
            )
        )
    except ExportError as exc:
        raise Rejected(str(exc), exc.diagnostics) from exc


@command("survey.repro_package", label="Reproducibility package", action=Action.SURVEY_READ)
def repro_package(
    builder: Builder,
    actor: Actor,
    *,
    survey_id: str,
    version: int,
    data: bool = False,
) -> ReproDownload:
    ctx = builder._locate(actor, survey_id, Action.SURVEY_READ)
    resource = Resource.survey(ctx.tenant_id, survey_id)
    if data is True and not can(actor, Action.SURVEY_EXPORT, resource):
        raise Forbidden("Participant data needs export permission.")
    v = published_version(builder, ctx, survey_id, version)

    repro_data = None
    if data is True:
        survey = builder.store.get_survey(ctx, survey_id)
        rows = _stored(builder, ctx, survey, v)
        repro_data = ReproData(rows, _save_mode(rows))

    pkg = build_for_version(builder, ctx, survey_id, v, data=repro_data)
    return ReproDownload(pkg.content, pkg.filename, pkg.diagnostics)
