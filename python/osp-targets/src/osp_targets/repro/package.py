"""Build the reproducibility package: one deterministic zip, in memory. Pure, no I/O.

Same inputs, same bytes: entries are sorted, every entry has a fixed timestamp
(2000-01-01) and mode, JSON is written with sorted keys where we choose the layout, and
nothing reads a clock. The kit files (``replay.py``, ``replay.mjs``, the vendored
``osp_engine/random.py`` and ``engine.js``) are passed in by the caller, which reads them.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..data import (
    CsvOptions,
    JsonOptions,
    StoredResponse,
    SurveyVersion,
    codebook,
    export_csv,
    export_json,
)
from ..diagnostics import ExportDiagnostic
from ..lss import export_lss
from ..xlsform import export_xlsform
from .text import license_md, readme_md

FORMAT = "osp-repro-package/1"
_ZIP_TIME = (2000, 1, 1, 0, 0, 0)

KIT_FILES = ("replay.py", "replay.mjs")
"""The kit sources in ``osp_targets/repro/kit/``, copied into ``replay/`` unchanged."""

VENDORED_INIT = (
    b'"""Vendored from the Open Survey Platform (MIT): only ``osp_engine.random``, which\n'
    b"``replay.py`` imports. The original is ``python/osp-engine/src/osp_engine/random.py``.\n"
    b'"""\n'
)


@dataclass(frozen=True)
class ReproKit:
    """The replay kit. ``engine_js`` is ``None`` when the engine bundle isn't built
    (``make engine-bundle``); the package then says so and ships no ``replay.mjs``."""

    replay_py: bytes
    replay_mjs: bytes
    random_py: bytes  # osp_engine/random.py, verbatim
    engine_js: bytes | None = None


@dataclass(frozen=True)
class ReproData:
    """Participant data (only with ``survey.export`` and an explicit request)."""

    responses: Sequence[StoredResponse]
    save_mode: str | None = None


@dataclass(frozen=True)
class ReproInputs:
    survey: Mapping[str, Any]  # the published version's survey JSON
    survey_id: str  # the platform's survey id (not the survey JSON's own id)
    version: int
    survey_checksum: str  # the store's version checksum: SHA-256 hex of canonical JSON
    plan: Mapping[str, Any]  # the runtime plan as served (with its own checksum)
    kit: ReproKit
    versions: Mapping[str, str] = field(default_factory=dict)  # tool -> exact version
    runtime_config: Mapping[str, Any] | None = None
    plan_source: str = "published"  # or "recompiled" (no stored publication)
    data: ReproData | None = None


@dataclass(frozen=True)
class ReproPackage:
    content: bytes
    filename: str
    files: list[str]  # paths inside the zip root, sorted
    diagnostics: list[ExportDiagnostic]


def _json(value: Any, *, sort: bool = True) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=sort) + "\n").encode()


def _diag_json(diags: Sequence[ExportDiagnostic]) -> bytes:
    return _json([d.model_dump(mode="json") for d in diags], sort=False)


def _canonical_sha256(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _zip(root: str, files: Mapping[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(files):
            info = zipfile.ZipInfo(f"{root}/{path}", date_time=_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if path.endswith((".py", ".mjs")) else 0o644) << 16
            info.create_system = 3  # unix, so the mode above is honoured
            z.writestr(info, files[path], compresslevel=9)
    return buf.getvalue()


def _title(survey: Mapping[str, Any]) -> str:
    meta = survey.get("metadata")
    title = meta.get("title") if isinstance(meta, Mapping) else None
    if isinstance(title, str):
        return title
    if isinstance(title, Mapping):
        langs = meta.get("languages") if isinstance(meta, Mapping) else None
        first = langs[0] if isinstance(langs, list) and langs else None
        text = title.get(first) if first is not None else None
        if isinstance(text, str):
            return text
        return next((v for v in title.values() if isinstance(v, str)), "")
    return ""


def _license(survey: Mapping[str, Any]) -> str | None:
    meta = survey.get("metadata")
    lic = meta.get("license") if isinstance(meta, Mapping) else None
    return lic if isinstance(lic, str) and lic.strip() else None


def build_repro_package(inp: ReproInputs) -> ReproPackage:
    """The package for one published version. Raises ``ExportError`` only if the
    participant data can't be exported (clashing names); exporters report diagnostics."""
    root = f"survey-{inp.survey_id[:8]}-v{inp.version}-repro"
    files: dict[str, bytes] = {}
    diags: list[ExportDiagnostic] = []

    survey = dict(inp.survey)
    files["survey/survey.json"] = _json(survey, sort=False)
    files["survey/plan.json"] = _json(dict(inp.plan), sort=False)
    if inp.runtime_config is not None:
        files["survey/runtime-config.json"] = _json(dict(inp.runtime_config))

    xlsx, x_diags = export_xlsform(survey)
    lss, l_diags = export_lss(survey)
    if xlsx:
        files["exports/survey.xlsx"] = xlsx
    if lss:
        files["exports/survey.lss"] = lss
    files["exports/xlsform-diagnostics.json"] = _diag_json(x_diags)
    files["exports/lss-diagnostics.json"] = _diag_json(l_diags)
    diags += x_diags + l_diags

    if inp.data is not None:
        sv = SurveyVersion(
            survey,
            number=inp.version,
            checksum=inp.survey_checksum,
            save_mode=inp.data.save_mode,  # type: ignore[arg-type]
        )
        rows = list(inp.data.responses)
        book = codebook(sv)
        files["data/codebook.md"] = book.markdown.encode("utf-8")
        files["data/codebook.json"] = _json(book.data, sort=False)
        files["data/responses.csv"] = export_csv(sv, rows, CsvOptions())
        files["data/responses.json"] = export_json(sv, rows, JsonOptions(events=True))

    files["replay/replay.py"] = inp.kit.replay_py
    files["replay/osp_engine/__init__.py"] = VENDORED_INIT
    files["replay/osp_engine/random.py"] = inp.kit.random_py
    if inp.kit.engine_js is not None:
        files["replay/engine.js"] = inp.kit.engine_js
        files["replay/replay.mjs"] = inp.kit.replay_mjs

    plan_checksum = inp.plan.get("checksum")
    manifest = {
        "format": FORMAT,
        "survey": {
            "id": inp.survey_id,
            "surveyJsonId": survey.get("id"),
            "title": _title(survey),
            "version": inp.version,
            "checksum": inp.survey_checksum,
            "checksumOk": _canonical_sha256(survey) == inp.survey_checksum,
            "license": _license(survey),
        },
        "plan": {
            "checksum": plan_checksum,
            "planVersion": inp.plan.get("planVersion"),
            "engineVersion": inp.plan.get("engineVersion"),
            "seedVersion": (inp.plan.get("survey") or {}).get("seedVersion"),
            "source": inp.plan_source,
        },
        "versions": dict(sorted(inp.versions.items())),
        "includesData": inp.data is not None,
        "responses": len(inp.data.responses) if inp.data is not None else 0,
        "engineBundle": inp.kit.engine_js is not None,
    }
    files["manifest.json"] = _json(manifest)
    files["LICENSE.md"] = license_md(_license(survey), engine=inp.kit.engine_js is not None)
    listed = sorted([*files, "README.md", "checksums.sha256"])
    files["README.md"] = readme_md(manifest, listed, x_diags, l_diags)
    files["checksums.sha256"] = "".join(
        f"{hashlib.sha256(files[p]).hexdigest()}  {p}\n" for p in sorted(files)
    ).encode("ascii")
    return ReproPackage(_zip(root, files), f"{root}.zip", sorted(files), diags)


__all__ = [
    "FORMAT",
    "KIT_FILES",
    "ReproData",
    "ReproInputs",
    "ReproKit",
    "ReproPackage",
    "build_repro_package",
]
