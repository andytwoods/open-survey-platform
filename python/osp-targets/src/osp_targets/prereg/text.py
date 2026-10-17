"""The human-readable files of the preregistration bundle. Pure text, deterministic.

- ``structure_md`` / ``randomisation_md`` / ``exclusions_md``: the design documents, in
  Markdown, written so they can be pasted into a preregistration form.
- ``summary_html``: one self-contained, printable HTML page with everything (browsers
  print it to PDF; the bundle ships no PDF of its own).
- ``readme_md``: what is in the bundle and how to verify it.

Every participant-facing text is escaped where it lands (Markdown cells, HTML).
"""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from typing import Any

_WHAT = {
    "blocks": "flow children of randomiser",
    "items": "items on page",
    "choices": "choices of question",
}


def _md(text: Any) -> str:
    """Text safe inside a Markdown table cell or line."""
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("<", "&lt;")
    )


def _code(text: Any) -> str:
    s = str(text).replace("\n", " ")
    fence = "``" if "`" in s else "`"
    pad = " " if s.startswith("`") or s.endswith("`") else ""
    return f"{fence}{pad}{s}{pad}{fence}"


def _lang(texts: Mapping[str, str] | None, languages: Sequence[str]) -> str:
    if not texts:
        return ""
    values = [texts.get(lang, "") for lang in languages]
    if len(set(values)) == 1:
        return _md(values[0])
    return "; ".join(f"[{lang}] {_md(texts.get(lang, ''))}" for lang in languages)


def _title(data: Mapping[str, Any]) -> str:
    s = data["survey"]
    return s["title"].get(s["defaultLanguage"]) or next(iter(s["title"].values()), "") or s["id"]


def _head(data: Mapping[str, Any], what: str) -> list[str]:
    s = data["survey"]
    return [
        f"# {what}: {_md(_title(data))}",
        "",
        f"- Survey id: {_code(s['id'])}",
        f"- Version: {s['version'] if s['version'] is not None else 'draft'}",
        *([f"- Version checksum: {_code(s['checksum'])}"] if s["checksum"] else []),
        "",
    ]


# -- structure and flow ----------------------------------------------------------------------


def structure_md(data: Mapping[str, Any]) -> str:
    st, langs = data["structure"], data["survey"]["languages"]
    out = _head(data, "Structure and flow")
    out += [
        "## Size",
        "",
        f"- Blocks: {len(st['blocks'])}; pages: {st['pages']}; questions: {st['questions']}"
        f"; notes (text-only items): {st['notes']}",
        f"- Languages: {', '.join(langs)} (default {data['survey']['defaultLanguage']})",
        "",
        "## Blocks and pages",
        "",
    ]
    for b in st["blocks"]:
        title = f" ({_md(b['title'])})" if b.get("title") else ""
        out.append(f"### Block {_code(b['id'])}{title}")
        out.append("")
        if b["id"] in st["unplacedBlocks"]:
            out.append("Not placed in the flow (participants never see it).")
            out.append("")
        out.append("| Page | Title | Shown if | Items | Item order |")
        out.append("|---|---|---|---|---|")
        for p in b["pages"]:
            items = ", ".join(_code(q) for q in p["questions"])
            if p["notes"]:
                items = (items + "; " if items else "") + f"{p['notes']} note(s)"
            out.append(
                f"| {_code(p['id'])} | {_lang(p.get('title'), langs)} | "
                f"{_code(p['showIf']) if p.get('showIf') else 'always'} | {items or '-'} | "
                f"{'shuffled' if p['itemOrder'] == 'shuffle' else 'fixed'} |"
            )
        out.append("")
    out += [
        "## Flow",
        "",
        "What a participant goes through, in order (nested parts are indented):",
        "",
    ]
    out += [f"{'    ' * n['depth']}- {_md_keep_code(n['text'])}" for n in data["flow"]]
    out.append("- Reaching the end of the flow ends the session with outcome `complete`.")
    out += ["", "## Endings", "", "| Outcome (`_end`) | Reached by |", "|---|---|"]
    for o in data["outcomes"]:
        src = "; ".join(f"{x['kind']} {_code(x['id'])}" for x in o["sources"])
        out.append(f"| {_code(o['outcome'])} | {src} |")
    out.append("")
    return "\n".join(out)


def _md_keep_code(text: str) -> str:
    """Flow lines carry their own backticks; escape only what breaks a list item."""
    return text.replace("\r", " ").replace("\n", " ")


# -- randomisation ---------------------------------------------------------------------------


def randomisation_md(data: Mapping[str, Any]) -> str:
    r = data["randomisation"]
    out = _head(data, "Randomisation and assignment")
    out += ["## How random decisions are made", "", r["seedScheme"], ""]
    out += ["## Randomisers (block order)", ""]
    if r["randomisers"]:
        out += [
            "| Randomiser | Children (flow node ids) | Shown | Recorded in |",
            "|---|---|---|---|",
        ]
        for x in r["randomisers"]:
            shown = (
                f"{x['pick']} of {len(x['children'])}" if x["pick"] else f"all {len(x['children'])}"
            )
            out.append(
                f"| {_code(x['id'])} | {', '.join(_code(c) for c in x['children'])} | "
                f"{shown} | {_code(x['column'])} |"
            )
    else:
        out.append("None: blocks run in a fixed order.")
    out += ["", "## Shuffled pages and choices", ""]
    others = [o for o in r["orders"] if o["kind"] != "blocks"]
    if others:
        out += ["| Recorded in | What is shuffled | Of |", "|---|---|---|"]
        for o in others:
            of = ", ".join(_code(x) for x in o["of"])
            out.append(f"| {_code(o['column'])} | {_WHAT[o['kind']]} {_code(o['node'])} | {of} |")
    else:
        out.append(
            "None: every page shows its items, and every question its choices, in a fixed order."
        )
    a = r["assignment"]
    out += ["", "## Assignment to conditions", ""]
    if a["conditions"]:
        out += [a["method"], ""]
        out += ["| Condition | Levels | Assigned at |", "|---|---|---|"]
        where = {v: n["id"] for n in a["nodes"] for v in n["variables"]}
        for c in a["conditions"]:
            levels = ", ".join(_code(v) for v in c["levels"])
            node = where.get(c["name"]) or where.get(c["id"])
            out.append(
                f"| {_code(c['name'])} | {levels} | {_code(node) if node else 'not in the flow'} |"
            )
        out += [
            "",
            "Each response records the level in force in a column named after the condition, "
            "and where the draw was made (server or the participant's engine) in its "
            "`conditionSources`.",
        ]
    else:
        out.append("None: this design assigns no between-subjects conditions.")
    out += ["", "## Quotas", ""]
    if r["quotas"]:
        out += [
            "| Quota | Counts a completed response when | Limit | When full |",
            "|---|---|---|---|",
        ]
        for q in r["quotas"]:
            full = f"outcome {_code(q['onFull']['outcome'])}"
            if q["onFull"]["block"]:
                full = f"show {_code(q['onFull']['block'])}, then {full}"
            out.append(f"| {_code(q['id'])} | {_code(q['when'])} | {q['limit']} | {full} |")
        out += [
            "",
            "A place is held when the quota is checked and used up on completion; a held "
            "place is released after the resume-link expiry (see the exclusions), so a late "
            "resume may complete beyond the limit and is flagged `_late`.",
        ]
    else:
        out.append("None.")
    out += [
        "",
        "## Allocation modes",
        "",
        "`server` (our runtime) and `seeded` assignments are determined by the seed and can be "
        "replayed; a copy run in LimeSurvey (`limesurvey-native`) uses LimeSurvey's own "
        "randomiser, which is recorded but not reproducible.",
        "",
    ]
    return "\n".join(out)


# -- exclusions --------------------------------------------------------------------------------


def exclusions_md(data: Mapping[str, Any]) -> str:
    st = data["settings"]
    out = _head(data, "Planned exclusions and data handling")
    out += [
        "What the platform records about every response that an exclusion rule can rest on, "
        "read off this version's settings and flow. State the rules you will apply in the "
        "preregistration; the platform flags, it never drops a submitted response on its own "
        "(except the two-device case below).",
        "",
        "## Settings this rests on",
        "",
        f"- Saving: {st['saveMode']}"
        + (f" (device copy: {st['localCopy']})" if st["saveMode"] == "end-only" else ""),
        f"- Going back: {'allowed' if st['backNavigation'] else 'not allowed'}",
        f"- Resume link and quota holds expire after: {st['resumeExpiryDays']} idle days",
        f"- Consent page: {'yes' if st['consent'] else 'no'}",
        f"- Custom code (hooks): {'yes' if st['hooks'] else 'no'}",
        "",
        "## Rules and the evidence for each",
        "",
    ]
    for r in data["exclusions"]:
        tag = "" if r["applies"] else " (does not apply to this design)"
        out += [
            f"### {_md(r['title'])}{tag}",
            "",
            _md_keep_code(r["text"]),
            "",
            f"Evidence: {r['evidence']}.",
            "",
        ]
    return "\n".join(out)


# -- HTML summary ----------------------------------------------------------------------------

_CSS = """
:root { color-scheme: light; }
body { font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  color: #1a1a1a; background: #fff; max-width: 52rem; margin: 2rem auto; padding: 0 1.25rem; }
h1 { font-size: 1.6rem; margin: 0 0 .25rem; }
h2 { font-size: 1.2rem; margin: 2rem 0 .5rem; border-bottom: 1px solid #ccc;
  padding-bottom: .2rem; }
h3 { font-size: 1rem; margin: 1.25rem 0 .4rem; }
p { margin: .5rem 0; }
table { border-collapse: collapse; width: 100%; margin: .5rem 0 1rem; font-size: .92em; }
th, td { border: 1px solid #ccc; padding: .3rem .5rem; text-align: left; vertical-align: top; }
th { background: #f3f3f3; }
code { font: .92em ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  background: #f3f3f3; padding: 0 .2em; border-radius: 3px; overflow-wrap: anywhere; }
pre { background: #f3f3f3; padding: .6rem; overflow: auto; }
.muted { color: #555; } .na { color: #666; }
.flow { list-style: none; padding-left: 0; } .flow li { margin: .15rem 0; }
.flow .d1 { padding-left: 1.5rem; } .flow .d2 { padding-left: 3rem; }
.flow .d3 { padding-left: 4.5rem; } .flow .d4 { padding-left: 6rem; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: .25rem 1rem; }
dt { font-weight: 600; } dd { margin: 0; }
@media print { body { margin: 0; max-width: none; } h2 { break-after: avoid; }
  table, li { break-inside: avoid; } a { color: inherit; text-decoration: none; } }
"""


def _e(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _inline(text: str) -> str:
    """Escape, then turn `code` spans into <code> (the only markup the data uses)."""
    parts = _e(text).split("`")
    return "".join(p if i % 2 == 0 else f"<code>{p}</code>" for i, p in enumerate(parts))


def _langs_html(texts: Mapping[str, str] | None, languages: Sequence[str]) -> str:
    if not texts:
        return ""
    values = [texts.get(lang, "") for lang in languages]
    if len(set(values)) == 1:
        return _e(values[0])
    return "<br>".join(
        f"<span class=muted>[{_e(lang)}]</span> {_e(texts.get(lang, ''))}" for lang in languages
    )


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def summary_html(
    data: Mapping[str, Any],
    manifest: Mapping[str, Any],
    codebook: Mapping[str, Any] | None = None,
) -> bytes:
    """One printable page: identity and checksums, design, randomisation, exclusions, the
    variables, consent texts, custom code, tool versions and the bundle's contents."""
    s, st, r, langs = (
        data["survey"],
        data["structure"],
        data["randomisation"],
        data["survey"]["languages"],
    )
    title = _title(data)
    h: list[str] = [
        "<!DOCTYPE html>",
        f'<html lang="{_e(s["defaultLanguage"])}"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>Preregistration summary: {_e(title)}</title>",
        f"<style>{_CSS}</style></head><body>",
        f"<h1>Preregistration summary: {_e(title)}</h1>",
        '<p class="muted">Generated by the Open Survey Platform from the published survey '
        "version named below. Everything on this page is derived from that version's "
        "definition; nothing here was written by hand.</p>",
    ]
    # identity
    h.append("<h2>Identity</h2><dl>")
    h.append(f"<dt>Survey id</dt><dd><code>{_e(s['id'])}</code></dd>")
    h.append(
        f"<dt>Version</dt><dd>{_e(s['version'] if s['version'] is not None else 'draft')}</dd>"
    )
    if s["checksum"]:
        h.append(
            f"<dt>Version checksum</dt><dd><code>{_e(s['checksum'])}</code> "
            "(SHA-256 of the canonical JSON)</dd>"
        )
    plan = manifest.get("plan") or {}
    if plan.get("checksum"):
        h.append(f"<dt>Runtime plan checksum</dt><dd><code>{_e(plan['checksum'])}</code></dd>")
    h.append(
        f"<dt>Languages</dt><dd>{_e(', '.join(langs))} (default {_e(s['defaultLanguage'])})</dd>"
    )
    licence = _e(s["license"]) if s["license"] else "<span class=na>not set</span>"
    h.append(f"<dt>Licence</dt><dd>{licence}</dd>")
    if s.get("description"):
        h.append(f"<dt>Description</dt><dd>{_langs_html(s['description'], langs)}</dd>")
    h.append("</dl>")
    # design
    h.append("<h2>Design at a glance</h2><ul>")
    h.append(
        f"<li>{len(st['blocks'])} block(s), {st['pages']} page(s), {st['questions']} "
        f"question(s), {st['notes']} note(s)</li>"
    )
    pages = len([o for o in r["orders"] if o["kind"] == "items"])
    choices = len([o for o in r["orders"] if o["kind"] == "choices"])
    h.append(
        f"<li>{len(r['randomisers'])} randomiser(s), {pages} shuffled page(s), "
        f"{choices} question(s) with shuffled choices</li>"
    )
    conds = r["assignment"]["conditions"]
    h.append(
        f"<li>{len(conds)} assigned condition(s)"
        + (
            ": "
            + ", ".join(f"<code>{_e(c['name'])}</code> ({len(c['levels'])} levels)" for c in conds)
            if conds
            else ""
        )
        + "</li>"
    )
    consent = "yes" if data["settings"]["consent"] else "no"
    hooks_flag = "yes" if data["settings"]["hooks"] else "no"
    h.append(
        f"<li>{len(r['quotas'])} quota(s); consent page: {consent}; custom code: {hooks_flag}</li>"
    )
    h.append("</ul>")
    # flow
    h.append("<h2>Flow</h2><ul class=flow>")
    for n in data["flow"]:
        h.append(f"<li class=d{min(n['depth'], 4)}>{_inline(n['text'])}</li>")
    h.append(
        "<li>Reaching the end of the flow ends the session with outcome "
        "<code>complete</code>.</li></ul>"
    )
    h.append("<h3>Endings</h3>")
    h.append(
        _table(
            ["Outcome (<code>_end</code>)", "Reached by"],
            [
                [
                    f"<code>{_e(o['outcome'])}</code>",
                    "; ".join(f"{_e(x['kind'])} <code>{_e(x['id'])}</code>" for x in o["sources"]),
                ]
                for o in data["outcomes"]
            ],
        )
    )
    # randomisation
    h.append("<h2>Randomisation and assignment</h2>")
    h.append(f"<p>{_inline(r['seedScheme'])}</p>")
    if r["randomisers"]:
        h.append("<h3>Randomisers</h3>")
        h.append(
            _table(
                ["Randomiser", "Children", "Shown", "Recorded in"],
                [
                    [
                        f"<code>{_e(x['id'])}</code>",
                        ", ".join(f"<code>{_e(c)}</code>" for c in x["children"]),
                        f"{x['pick']} of {len(x['children'])}"
                        if x["pick"]
                        else f"all {len(x['children'])}",
                        f"<code>{_e(x['column'])}</code>",
                    ]
                    for x in r["randomisers"]
                ],
            )
        )
    others = [o for o in r["orders"] if o["kind"] != "blocks"]
    if others:
        h.append("<h3>Shuffled pages and choices</h3>")
        h.append(
            _table(
                ["Recorded in", "What is shuffled", "Of"],
                [
                    [
                        f"<code>{_e(o['column'])}</code>",
                        f"{_e(_WHAT[o['kind']])} <code>{_e(o['node'])}</code>",
                        ", ".join(f"<code>{_e(x)}</code>" for x in o["of"]),
                    ]
                    for o in others
                ],
            )
        )
    if not r["randomisers"] and not others:
        h.append("<p>No randomisers, shuffled pages or shuffled choices.</p>")
    h.append("<h3>Assignment to conditions</h3>")
    if conds:
        h.append(f"<p>{_inline(r['assignment']['method'])}</p>")
        where = {v: n["id"] for n in r["assignment"]["nodes"] for v in n["variables"]}
        h.append(
            _table(
                ["Condition", "Levels", "Assigned at"],
                [
                    [
                        f"<code>{_e(c['name'])}</code>",
                        ", ".join(f"<code>{_e(v)}</code>" for v in c["levels"]),
                        f"<code>{_e(where.get(c['name']) or where.get(c['id']))}</code>"
                        if (where.get(c["name"]) or where.get(c["id"]))
                        else "<span class=na>not in the flow</span>",
                    ]
                    for c in conds
                ],
            )
        )
    else:
        h.append("<p>None: this design assigns no between-subjects conditions.</p>")
    h.append("<h3>Quotas</h3>")
    if r["quotas"]:
        h.append(
            _table(
                ["Quota", "Counts a completed response when", "Limit", "When full"],
                [
                    [
                        f"<code>{_e(q['id'])}</code>",
                        f"<code>{_e(q['when'])}</code>",
                        _e(q["limit"]),
                        (
                            f"show <code>{_e(q['onFull']['block'])}</code>, then "
                            if q["onFull"]["block"]
                            else ""
                        )
                        + f"outcome <code>{_e(q['onFull']['outcome'])}</code>",
                    ]
                    for q in r["quotas"]
                ],
            )
        )
    else:
        h.append("<p>None.</p>")
    # exclusions
    h.append("<h2>Planned exclusions and data handling</h2>")
    h.append(
        "<p>What the platform records that an exclusion rule can rest on. The platform flags; "
        "it never drops a submitted response on its own (except the two-device case).</p>"
    )
    sx = data["settings"]
    h.append("<dl>")
    h.append(
        f"<dt>Saving</dt><dd>{_e(sx['saveMode'])}"
        + (f" (device copy: {_e(sx['localCopy'])})" if sx["saveMode"] == "end-only" else "")
        + "</dd>"
    )
    h.append(f"<dt>Going back</dt><dd>{'allowed' if sx['backNavigation'] else 'not allowed'}</dd>")
    h.append(f"<dt>Holds expire after</dt><dd>{_e(sx['resumeExpiryDays'])} idle days</dd>")
    h.append("</dl>")
    h.append(
        _table(
            ["Rule", "Applies", "What the platform does", "Evidence"],
            [
                [
                    _e(x["title"]),
                    "yes" if x["applies"] else "<span class=na>no</span>",
                    _inline(x["text"]),
                    _inline(x["evidence"]),
                ]
                for x in data["exclusions"]
            ],
        )
    )
    # variables
    h.append("<h2>Variables</h2>")
    h.append(
        "<p>In flow order; the full codebook (labels in every language, constraints, "
        "missing-value states, CSV columns) is in the bundle.</p>"
    )
    h.append(
        _table(
            ["Name", "Type", "Label", "Required", "Shown if", "Choices"],
            [
                [
                    f"<code>{_e(q['name'])}</code>",
                    _e(q["type"]),
                    _langs_html(q["label"], langs),
                    "yes" if q["required"] else "no",
                    f"<code>{_e(q['showIf'])}</code>" if q.get("showIf") else "always",
                    (
                        ", ".join(f"<code>{_e(c)}</code>" for c in q["choices"])
                        + (" (shuffled)" if q.get("choiceOrder") == "shuffle" else "")
                    )
                    if q.get("choices")
                    else "",
                ]
                for q in data["questions"]
            ],
        )
    )
    if codebook:
        others = codebook.get("otherVariables") or []
        if others:
            h.append("<h3>Other variables</h3>")
            h.append(
                _table(
                    ["Name", "Kind", "Details"],
                    [
                        [
                            f"<code>{_e(x['name'])}</code>",
                            _e(x["kind"]),
                            (
                                f"URL parameter <code>{_e(x.get('urlParam'))}</code>, "
                                f"{_e(x.get('valueType'))}"
                                + (
                                    f", default <code>{_e(x['default'])}</code>"
                                    if x.get("default") is not None
                                    else ""
                                )
                            )
                            if x["kind"] == "embedded"
                            else f"computed as <code>{_e(x.get('expr', ''))}</code>",
                        ]
                        for x in others
                    ],
                )
            )
        c = codebook.get("consent")
        if c:
            h.append("<h2>Consent</h2>")
            h.append(f"<p>{_e(c['note'])}</p><dl>")
            h.append(f"<dt>Text</dt><dd>{_langs_html(c['text'], langs)}</dd>")
            h.append(f"<dt>Agree button</dt><dd>{_langs_html(c['agreeLabel'], langs)}</dd>")
            h.append(f"<dt>Decline button</dt><dd>{_langs_html(c['declineLabel'], langs)}</dd>")
            h.append(
                f"<dt>Declines counted</dt><dd>{'yes' if c['declinesCounted'] else 'no'}</dd></dl>"
            )
        hooks = codebook.get("hooks") or []
        h.append("<h2>Custom code</h2>")
        if hooks:
            h.append(
                "<p>This version runs researcher hooks. Data-export capabilities can send "
                "participant data off the platform.</p>"
            )
            h.append(
                _table(
                    ["Hook", "Events", "Reads", "Data exports"],
                    [
                        [
                            f"<code>{_e(x['id'])}</code>",
                            _e(", ".join(x["events"]) or "-"),
                            _e(", ".join(x["reads"]) or "-"),
                            _e(", ".join(x["dataExports"]) or "none"),
                        ]
                        for x in hooks
                    ],
                )
            )
        else:
            h.append("<p>This version runs no custom code.</p>")
    # versions + contents
    h.append("<h2>Software versions</h2>")
    h.append(
        _table(
            ["What", "Version"],
            [[_e(k), f"<code>{_e(v)}</code>"] for k, v in (manifest.get("versions") or {}).items()],
        )
    )
    h.append("<h2>Bundle contents and verification</h2>")
    h.append(
        "<ul>"
        + "".join(
            f"<li><code>{_e(f)}</code>: {_e(_DESCRIBE.get(f, ''))}</li>"
            for f in manifest.get("files") or []
        )
        + "</ul>"
    )
    h.append("<p>From the folder that holds the bundle's files:</p>")
    h.append(
        "<pre>sha256sum -c checksums.sha256        # Linux\n"
        "shasum -a 256 -c checksums.sha256    # macOS</pre>"
    )
    h.append(
        "<p>The survey version checksum is the SHA-256 of <code>survey/survey.json</code> as "
        "canonical JSON (sorted keys, no whitespace, UTF-8). <code>survey/checksum.txt</code> "
        "repeats it.</p>"
    )
    h.append("</body></html>\n")
    return "\n".join(h).encode("utf-8")


# -- README -----------------------------------------------------------------------------------

_DESCRIBE = {
    "README.md": "this file",
    "manifest.json": "machine-readable summary: identity, checksums, versions, contents",
    "checksums.sha256": "SHA-256 of every other file in the bundle",
    "summary.html": "the human-readable summary (open in a browser; print to PDF)",
    "survey/survey.json": "the survey definition (`osp-survey`) of this published version",
    "survey/checksum.txt": "the version checksum and how it is computed",
    "codebook/codebook.md": "codebook: every variable, label, code, condition and missing state",
    "codebook/codebook.json": "the same codebook as JSON",
    "design/design.json": "structure, flow, randomisation, exclusions and settings as data",
    "design/structure.md": "blocks, pages, questions and the flow, as text",
    "design/randomisation.md": "how orders and conditions are drawn, and the quotas",
    "design/exclusions.md": "what is recorded about every response that exclusions can rest on",
    "reproducibility-package.zip": "the reproducibility package of this version (plan, "
    "exports, replay kit; no data)",
}


def readme_md(manifest: Mapping[str, Any]) -> bytes:
    s = manifest["survey"]
    lines = [
        f"# Preregistration bundle: {s['title'] or s['surveyJsonId']} (version {s['version']})",
        "",
        "Made by the Open Survey Platform from one published survey version. It holds what a",
        "preregistration needs about the instrument and design: the exact survey definition",
        "with its checksum, the codebook, how randomisation and assignment work, what the",
        "platform records that planned exclusions can rest on, and a human-readable summary.",
        "It contains **no participant data**.",
        "",
        "## Checksums",
        "",
        f"- Survey version checksum: `{s['checksum']}` (SHA-256 of the canonical JSON of",
        "  `survey/survey.json`: sorted keys, no whitespace, UTF-8). Every response collected",
        "  on this version names it.",
    ]
    plan = manifest.get("plan") or {}
    if plan.get("checksum"):
        lines.append(
            f"- Runtime plan checksum: `{plan['checksum']}` (the plan participants' browsers ran)."
        )
    lines += ["", "## Contents", ""]
    lines += [f"- `{f}`: {_DESCRIBE.get(f, '')}".rstrip(": ") for f in manifest["files"]]
    if not manifest.get("includesReproPackage"):
        lines += [
            "",
            "The reproducibility package was not included; it can be downloaded separately",
            "for the same version.",
        ]
    lines += [
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
        "The bundle is deterministic: building it again from the same version gives the same",
        "bytes, so a copy on a registry can be compared with a fresh download. It carries no",
        "timestamp of its own; the registry's upload record dates it.",
        "",
        "## Using it on OSF",
        "",
        "Upload the bundle's files to the OSF project (the platform can do this with a personal",
        "access token you supply once; it is never stored), then register the project. In the",
        "registration form, cite the version checksum above as the instrument's identifier,",
        "paste `design/randomisation.md` and `design/exclusions.md` into the design and",
        "exclusion sections, and attach `summary.html` (or a PDF printed from it).",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


__all__ = ["exclusions_md", "randomisation_md", "readme_md", "structure_md", "summary_html"]
