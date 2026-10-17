"""README.md and LICENSE.md of the reproducibility package. Pure text, deterministic."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from ..diagnostics import ExportDiagnostic

MIT = """MIT License

Copyright (c) 2026 Open Survey Platform contributors

Permission is hereby granted, free of charge, to any person obtaining a copy of this
software and associated documentation files (the "Software"), to deal in the Software
without restriction, including without limitation the rights to use, copy, modify, merge,
publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons
to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
"""

_DESCRIBE = {
    "README.md": "this file",
    "LICENSE.md": "licences: platform code (MIT) and survey content",
    "manifest.json": "machine-readable summary: versions, checksums, contents",
    "checksums.sha256": "SHA-256 of every other file in the package",
    "survey/survey.json": "the survey definition (`osp-survey`) of this published version",
    "survey/plan.json": "the runtime plan participants' browsers ran (ids resolved, ASTs)",
    "survey/runtime-config.json": "the server's session config: assignment methods, quotas",
    "exports/survey.xlsx": "XLSForm export (ODK / Enketo / KoboToolbox)",
    "exports/survey.lss": "LimeSurvey export (`.lss`)",
    "exports/xlsform-diagnostics.json": "what the XLSForm export lowered, approximated or lost",
    "exports/lss-diagnostics.json": "what the LimeSurvey export lowered, approximated or lost",
    "data/codebook.md": "codebook: variables, labels, conditions, missing-value states",
    "data/codebook.json": "the same codebook as JSON",
    "data/responses.csv": "responses, one row each (empty cell + `<var>__state`)",
    "data/responses.json": "responses with `{state, value}` answers and each event log",
    "replay/replay.py": "recomputes realised orders and assignments from seeds (Python)",
    "replay/osp_engine/__init__.py": "vendored package marker",
    "replay/osp_engine/random.py": "the platform's seeded PRNG, verbatim (`osp_engine.random`)",
    "replay/engine.js": "the exact participant engine bundle (`@osp/engine`)",
    "replay/replay.mjs": "replays every event log through `engine.js` (Node)",
}


def _counts(diags: Sequence[ExportDiagnostic]) -> str:
    c = Counter(d.severity for d in diags)
    parts = [f"{c[s]} {s}" for s in ("error", "loss", "warning", "info") if c[s]]
    return ", ".join(parts) if parts else "none"


def readme_md(
    manifest: Mapping[str, Any],
    files: Sequence[str],
    xlsform: Sequence[ExportDiagnostic],
    lss: Sequence[ExportDiagnostic],
) -> bytes:
    s, p, v = manifest["survey"], manifest["plan"], manifest["versions"]
    data = manifest["includesData"]
    lines = [
        f"# Reproducibility package: {s['title'] or s['surveyJsonId']} (version {s['version']})",
        "",
        "Made by the Open Survey Platform. It shows exactly what participants saw (the",
        "survey definition and the runtime plan their browsers ran) and lets anyone re-run",
        "the randomisation and, with data, replay every response.",
        "",
        "## Versions",
        "",
        "| What | Version |",
        "|---|---|",
    ]
    rows = {
        "survey version": str(s["version"]),
        "survey spec": str(v.get("spec", "")),
        "plan schema": str(p.get("planVersion")),
        "engine API (plan target)": str(p.get("engineVersion")),
        "seed version (`surveyVersion` in seeds)": str(p.get("seedVersion")),
        **{k: val for k, val in v.items() if k != "spec"},
    }
    lines += [f"| {k} | `{val}` |" for k, val in rows.items()]
    lines += [
        "",
        "## Checksums",
        "",
        f"- Survey version checksum: `{s['checksum']}` (SHA-256 of the canonical JSON of",
        "  `survey/survey.json`: sorted keys, no whitespace, UTF-8).",
        f"- Runtime plan checksum: `{p['checksum']}` (SHA-256 of the canonical JSON of",
        "  `survey/plan.json` without its `checksum` field). Every stored response names the",
        "  plan checksum it ran on.",
    ]
    if p.get("source") != "published":
        lines += [
            "- The plan was **recompiled** from the survey: no stored publication was found for",
            "  this version, so it may differ from the plan participants ran (theme only).",
        ]
    lines += [
        "",
        "## Contents",
        "",
    ]
    lines += [f"- `{f}`: {_DESCRIBE.get(f, '')}".rstrip(": ") for f in files]
    if not data:
        lines += [
            "",
            "This package has **no participant data**. A researcher with export permission",
            "can download one with data (`?data=true`).",
        ]
    lines += [
        "",
        "Export diagnostics: XLSForm " + _counts(xlsform) + "; LimeSurvey " + _counts(lss) + ".",
        "An exported copy only approximates the original where a diagnostic says so; the",
        "survey definition and plan are what participants actually ran.",
        "",
        "## Verify",
        "",
        "From the folder that holds this README:",
        "",
        "```sh",
        "sha256sum -c checksums.sha256        # Linux",
        "shasum -a 256 -c checksums.sha256    # macOS",
        "```",
        "",
        "`replay.py` and `replay.mjs` also recompute the plan checksum.",
        "",
        "## Replay",
        "",
        "```sh",
        "python3 replay/replay.py      # Python 3.12+, standard library only",
    ]
    if manifest["engineBundle"]:
        lines.append("node replay/replay.mjs        # Node 18+, no npm install")
    lines += [
        "```",
        "",
        "- `replay.py` recomputes, for every response, each realised order (randomiser block",
        "  order, shuffled page items, shuffled choices) and each assigned condition from the",
        "  response's `seed` and the plan, with the vendored `osp_engine/random.py`. Each",
        "  decision has its own stream: `randomize(items, node_seed(seedVersion, seed, nodeId))`.",
        "  Orders never reached (`null`) are not checked.",
    ]
    if manifest["engineBundle"]:
        lines += [
            "- `replay.mjs` replays each stored event log through `engine.js`, the exact engine",
            "  participants ran, checks that every recorded step comes out the same, and",
            "  compares the final seed, end, conditions, orders and answers with the stored",
            "  response.",
        ]
    else:
        lines += [
            "- The engine bundle was not available when this package was built, so there is",
            "  no `replay.mjs`: event logs can be replayed with `@osp/engine` from the",
            "  platform's source at the versions above.",
        ]
    lines += [
        "",
        "Both print one line per response (`match`, `MISMATCH`, `skipped`) and exit 1 on any",
        "mismatch; add `--json` for a machine-readable report.",
        "",
        "## Methods text",
        "",
        "> The survey was built and run with the Open Survey Platform (versions above).",
        "> Each session was given a random positive integer seed; every random decision",
        "> (block, item and choice orders and condition assignment) was drawn from its own",
        "> seeded stream (Park–Miller generator, inside-out Fisher–Yates shuffle), fixed",
        "> when the participant first reached it and recorded with the response. The",
        "> survey definition, runtime plan, seeds and replay scripts are in the",
        "> reproducibility package.",
        "",
        "Allocation modes: `server` and `seeded` assignments are seed-determined and",
        "replayable; `limesurvey-native` (LimeSurvey exports) used LimeSurvey's own RNG and",
        "can be recorded but not reproduced.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def license_md(survey_license: str | None, *, engine: bool) -> bytes:
    content = (
        f"The survey content (questions, texts, `survey/`, `exports/`) is licensed by the "
        f"researcher under: **{survey_license}** (from `metadata.license`)."
        if survey_license
        else "The researcher has not set a licence for the survey content (questions, texts, "
        "`survey/`, `exports/`; `metadata.license` is empty). All rights are reserved by "
        "its authors unless they say otherwise: ask them before reusing it."
    )
    bundled = (
        "\n`replay/engine.js` also bundles big.js 7 (MIT, Copyright (c) 2025 Michael Mclaughlin).\n"
        if engine
        else ""
    )
    text = f"""# Licences

## Survey content

{content}

Participant data in `data/` (if present) is governed by the study's ethics approval and
consent, not by either licence here.

## Platform code

`replay/` (`replay.py`, `replay.mjs`, `engine.js`, `osp_engine/`) is part of the Open
Survey Platform and is licensed under the MIT License:
{bundled}
{MIT}"""
    return text.encode("utf-8")
