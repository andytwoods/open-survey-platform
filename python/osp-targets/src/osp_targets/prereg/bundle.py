"""Build the preregistration bundle: one deterministic zip, in memory. Pure, no I/O.

Same inputs, same bytes (sorted entries, fixed timestamps, no clock), like the
reproducibility package it can nest. Raises ``ExportError`` only when the survey is not a
valid document or its export names clash (the codebook's rule); nothing else can fail.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..data import ExportError, SurveyVersion, codebook
from .describe import prereg_data
from .text import exclusions_md, randomisation_md, readme_md, structure_md, summary_html

FORMAT = "osp-prereg-bundle/1"
_ZIP_TIME = (2000, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class PreregInputs:
    survey: Mapping[str, Any]  # the published version's survey JSON
    survey_id: str  # the platform's survey id
    version: int
    survey_checksum: str  # the store's version checksum: SHA-256 hex of canonical JSON
    plan_checksum: str | None = None  # the runtime plan participants ran, if known
    versions: Mapping[str, str] = field(default_factory=dict)  # tool -> exact version
    repro_package: bytes | None = None  # the reproducibility package (no data), nested


@dataclass(frozen=True)
class PreregBundle:
    content: bytes
    filename: str
    files: list[str]  # paths inside the zip root, sorted
    summary_html: bytes  # the same ``summary.html`` as inside the zip
    manifest: dict[str, Any]


def _json(value: Any, *, sort: bool = True) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=sort) + "\n").encode()


def canonical_sha256(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _zip(root: str, files: Mapping[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(files):
            info = zipfile.ZipInfo(f"{root}/{path}", date_time=_ZIP_TIME)
            # a nested zip is already compressed: store it as it is
            info.compress_type = (
                zipfile.ZIP_STORED if path.endswith(".zip") else zipfile.ZIP_DEFLATED
            )
            info.external_attr = 0o644 << 16
            info.create_system = 3
            z.writestr(info, files[path], compresslevel=9)
    return buf.getvalue()


def build_prereg_bundle(inp: PreregInputs) -> PreregBundle:
    """The bundle for one published version."""
    if not isinstance(inp.survey, Mapping):
        raise ExportError("The survey version is not an object.", [])
    survey = dict(inp.survey)
    sv = SurveyVersion(
        survey,
        number=inp.version,
        checksum=inp.survey_checksum,
        save_mode=_save_mode(survey),  # type: ignore[arg-type]
    )
    data = prereg_data(sv)
    book = codebook(sv)
    root = f"survey-{inp.survey_id[:8]}-v{inp.version}-prereg"
    files: dict[str, bytes] = {}
    files["survey/survey.json"] = _json(survey, sort=False)
    files["survey/checksum.txt"] = (
        f"{inp.survey_checksum}  survey.json\n"
        "SHA-256 of the canonical JSON (sorted keys, no whitespace, UTF-8) of this version's\n"
        "survey definition. Recompute: json.dumps(doc, sort_keys=True, separators=(',', ':'),\n"
        "ensure_ascii=False).encode('utf-8'), then sha256.\n"
    ).encode()
    files["codebook/codebook.md"] = book.markdown.encode("utf-8")
    files["codebook/codebook.json"] = _json(book.data, sort=False)
    files["design/design.json"] = _json(data, sort=False)
    files["design/structure.md"] = structure_md(data).encode("utf-8")
    files["design/randomisation.md"] = randomisation_md(data).encode("utf-8")
    files["design/exclusions.md"] = exclusions_md(data).encode("utf-8")
    if inp.repro_package is not None:
        files["reproducibility-package.zip"] = inp.repro_package

    s = data["survey"]
    listed = sorted([*files, "README.md", "manifest.json", "summary.html", "checksums.sha256"])
    manifest: dict[str, Any] = {
        "format": FORMAT,
        "survey": {
            "id": inp.survey_id,
            "surveyJsonId": survey.get("id"),
            "title": s["title"].get(s["defaultLanguage"], ""),
            "version": inp.version,
            "checksum": inp.survey_checksum,
            "checksumOk": canonical_sha256(survey) == inp.survey_checksum,
            "license": s["license"],
            "languages": s["languages"],
        },
        "plan": {"checksum": inp.plan_checksum},
        "versions": dict(sorted(inp.versions.items())),
        "includesReproPackage": inp.repro_package is not None,
        "includesData": False,
        "files": listed,
        "design": {
            "blocks": len(data["structure"]["blocks"]),
            "pages": data["structure"]["pages"],
            "questions": data["structure"]["questions"],
            "randomisers": len(data["randomisation"]["randomisers"]),
            "conditions": [c["name"] for c in data["randomisation"]["assignment"]["conditions"]],
            "quotas": len(data["randomisation"]["quotas"]),
            "consent": data["settings"]["consent"],
            "hooks": data["settings"]["hooks"],
            "saveMode": data["settings"]["saveMode"],
            "retention": data["settings"]["retention"],
        },
    }
    files["manifest.json"] = _json(manifest)
    html = summary_html(data, manifest, book.data)
    files["summary.html"] = html
    files["README.md"] = readme_md(manifest)
    files["checksums.sha256"] = "".join(
        f"{hashlib.sha256(files[p]).hexdigest()}  {p}\n" for p in sorted(files)
    ).encode("ascii")
    return PreregBundle(_zip(root, files), f"{root}.zip", sorted(files), html, manifest)


def _save_mode(survey: Mapping[str, Any]) -> str | None:
    settings = survey.get("settings")
    mode = settings.get("saveMode", "every-page") if isinstance(settings, Mapping) else "every-page"
    return mode if mode in ("every-page", "end-only") else None


__all__ = ["FORMAT", "PreregBundle", "PreregInputs", "build_prereg_bundle", "canonical_sha256"]
