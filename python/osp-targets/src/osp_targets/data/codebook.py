"""The codebook of one published version (Markdown for people, JSON for tools).

It documents every column the CSV export writes and every key of the JSON export: names,
labels in all languages, types, choice codes, display logic, constraints, how each missing
state is encoded, conditions, randomisers, the save mode, and any custom code (hooks) with
its data-export capabilities. Same input, same bytes: nothing here reads a clock.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any

from .layout import (
    META_COLUMNS,
    STATE_SUFFIX,
    QuestionInfo,
    build_layout,
    csv_columns,
    split_names,
)
from .model import Codebook, CsvOptions, SurveyVersion

FORMAT = "osp-codebook/1"

STATE_MEANINGS = [
    ("answered", "Shown and answered.", "the value", "the value"),
    (
        "unanswered",
        "Shown, left empty (only possible when not required).",
        "empty",
        "null",
    ),
    (
        "irrelevant",
        "Its page was reached, but its show-if hid it.",
        "empty",
        "null",
    ),
    ("not-reached", "The flow never got to its page.", "empty", "null"),
]

SAVE_MODES = {
    "every-page": (
        "Answers were saved to the server on every page change. Partial sessions exist on "
        "the server, so drop-outs are visible to the researcher, but this export holds only "
        "submitted responses."
    ),
    "end-only": (
        "No response data (answers, hook output, paradata, URL parameters) was uploaded "
        "before the participant submitted; the server saw only session start (seed, "
        "assignment) and quota checks. Drop-outs and attrition are invisible, there is no "
        "cross-device resume, and a crash or storage eviction before submit loses the "
        "session. Only submitted responses exist."
    ),
}
SAVE_MODE_UNKNOWN = (
    "Not recorded for this version (it has no publication with a save mode, or no "
    "responses yet). The per-response _save_mode column is authoritative."
)

TYPE_NOTES = {
    "integer": "Whole number.",
    "decimal": "Exact decimal, exported as canonical text (2.50 is stored as 2.5) so no "
    "binary rounding creeps in.",
    "text": "Free text, trimmed.",
    "single": "One choice code.",
    "multi": "Any number of choice codes.",
    "date": "Calendar date, YYYY-MM-DD.",
    "slider": "A number picked on a slider, stored like an integer or decimal answer "
    "(see valueType); empty until the participant set it (it never defaults to a value).",
}


def _lang_text(texts: dict[str, str] | None, languages: list[str]) -> str:
    if not texts:
        return ""
    values = [texts.get(lang, "") for lang in languages]
    if len(set(values)) == 1:
        return _md(values[0])
    return "; ".join(f"[{lang}] {_md(texts.get(lang, ''))}" for lang in languages)


def _md(text: str) -> str:
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


def _question_columns(q: QuestionInfo, opts: CsvOptions) -> list[str]:
    if q.type == "multi" and opts.multi == "columns":
        cols = [f"{q.name}_{c.code}" for c in q.choices or []]
    else:
        cols = [q.name]
    if opts.state_columns:
        cols.append(q.name + STATE_SUFFIX)
    return cols


def _encoding(q: QuestionInfo, opts: CsvOptions) -> str:
    state = (
        f"{q.name}{STATE_SUFFIX} says which state applies"
        if opts.state_columns
        else "state columns were switched off, so the CSV cannot say why a cell is empty "
        "(the JSON export can)"
    )
    if q.type == "multi" and opts.multi == "columns":
        return (
            f"Answered: 1 in each chosen choice's column, 0 in the others. Unanswered, "
            f"irrelevant, not-reached: every choice column empty; {state}."
        )
    if q.type == "multi":
        return (
            f"Answered: the chosen codes separated by spaces, in choice-list order. "
            f"Otherwise empty; {state}."
        )
    return f"Answered: the value. Unanswered, irrelevant, not-reached: empty; {state}."


def _variable_missing(kind: str, opts: CsvOptions) -> str:
    where = "its __state column" if opts.state_columns else "the JSON export"
    if kind == "embedded":
        return (
            "Answered: the URL parameter, or its default when the parameter was missing. "
            "Unanswered (empty): no parameter and no default, or a malformed parameter. "
            f"See {where}."
        )
    return (
        "Answered: the computed value. Empty when an input was null: not-reached if every "
        "question it reads was not reached, irrelevant if each was not reached or hidden, "
        f"otherwise unanswered. See {where}."
    )


def codebook_data(
    version: SurveyVersion, options: CsvOptions | None = None, split: Collection[str] = ()
) -> dict[str, Any]:
    """The codebook as data. ``split``: names exported as ``<name>_v<N>`` (combined export)."""
    opts = options or CsvOptions()
    lay = build_layout(version, split)
    columns = csv_columns(lay, opts)  # also checks for clashing names
    langs = lay.languages
    save_mode = version.save_mode
    variables: list[dict[str, Any]] = []
    for q in lay.questions:
        entry: dict[str, Any] = {
            "name": q.name,
            "id": q.id,
            "type": q.type,
            "label": q.label,
            "help": q.help,
            "block": q.block,
            "page": q.page,
            "required": q.required,
            "showIf": q.show_if,
            "constraint": q.constraint,
            "constraintMessage": q.constraint_message,
            "choices": (
                None
                if q.choices is None
                else [
                    {
                        "code": c.code,
                        "label": c.label,
                        **(
                            {"column": f"{q.name}_{c.code}"}
                            if q.type == "multi" and opts.multi == "columns"
                            else {}
                        ),
                    }
                    for c in q.choices
                ]
            ),
            "choiceOrder": q.choice_order,
            "matrix": q.matrix,
            "matrixLabel": q.matrix_label,
            **(q.scale or {}),
            "csvColumns": _question_columns(q, opts),
            "missing": _encoding(q, opts),
        }
        variables.append({k: v for k, v in entry.items() if v is not None})
    return {
        "format": FORMAT,
        "survey": {
            "id": lay.survey.id,
            "title": lay.text(lay.survey.metadata.title),
            "version": lay.number,
            "checksum": lay.checksum,
            "languages": langs,
            "defaultLanguage": lay.default_language,
        },
        "csv": {
            "stateColumns": opts.state_columns,
            "multi": opts.multi,
            "bom": opts.bom,
            "escapeFormulas": opts.escape_formulas,
            "columns": [c.header for c in columns],
        },
        "missingValues": {
            "states": [
                {"state": s, "meaning": m, "csv": csv_cell, "json": json_value}
                for s, m, csv_cell, json_value in STATE_MEANINGS
            ],
            "csv": "Empty value cell plus the <var>__state column. No numeric missing "
            "codes (such as -99) are ever written.",
            "json": "value null plus state per answer.",
        },
        "saveMode": {
            "mode": save_mode,
            "implications": SAVE_MODES.get(save_mode or "", SAVE_MODE_UNKNOWN),
        },
        "metaColumns": [{"column": h, "meaning": m} for h, m in META_COLUMNS],
        "conditions": [{"name": v.name, "id": v.id, "levels": v.levels} for v in lay.assigned],
        "randomisers": [
            {
                "id": r.id,
                "children": r.children,
                "blocks": r.blocks,
                "pick": r.pick,
                "column": f"_order.blocks.{r.id}",
            }
            for r in lay.randomisers
        ],
        "orders": [
            {"column": o.column, "kind": o.kind, "node": o.node, "of": o.of} for o in lay.orders
        ],
        "variables": variables,
        "otherVariables": [
            {
                k: v
                for k, v in {
                    "name": x.name,
                    "id": x.id,
                    "kind": x.kind,
                    "valueType": x.value_type,
                    "urlParam": x.param,
                    "default": x.default,
                    "expr": x.expr,
                    "csvColumns": [x.name, x.name + STATE_SUFFIX]
                    if opts.state_columns
                    else [x.name],
                    "missing": _variable_missing(x.kind, opts),
                }.items()
                if v is not None
            }
            for x in [*lay.embedded, *lay.computed]
        ],
        "quotas": [
            {
                "id": q.id,
                "when": lay.expr_text(q.when),
                "limit": q.limit,
                "countOn": q.countOn,
                "onFull": {"block": q.onFull.block, "outcome": q.onFull.outcome},
            }
            for q in lay.survey.quotas
        ],
        "hooks": [
            {
                "id": h.id,
                "events": list(h.events),
                "reads": list(h.reads),
                "dataExports": list(h.data_exports),
            }
            for h in version.hooks
        ],
    }


# -- Markdown -------------------------------------------------------------------------


def _render(data: dict[str, Any], heading: str = "#") -> str:
    h1, h2, h3 = heading, heading + "#", heading + "##"
    s = data["survey"]
    langs: list[str] = s["languages"]
    out: list[str] = []
    add = out.append
    title = _lang_text(s["title"], langs)
    add(f"{h1} Codebook: {title}")
    add("")
    add(f"- Survey id: {_code(s['id'])}")
    add(f"- Version: {s['version'] if s['version'] is not None else 'draft'}")
    if s["checksum"]:
        add(f"- Version checksum: {_code(s['checksum'])}")
    add(f"- Languages: {', '.join(langs)} (default {s['defaultLanguage']})")
    add(f"- Codebook format: {_code(data['format'])}")
    add("")

    add(f"{h2} How to read this data")
    add("")
    add(
        "Every question is in exactly one state. The value cell is filled only when the "
        "state is `answered`."
    )
    add("")
    add("| State | Meaning | CSV value cell | JSON `value` |")
    add("|---|---|---|---|")
    for st in data["missingValues"]["states"]:
        add(f"| `{st['state']}` | {st['meaning']} | {st['csv']} | {st['json']} |")
    add("")
    csv_opts = data["csv"]
    if csv_opts["stateColumns"]:
        add(
            "- **CSV:** an empty value cell plus a companion column `<var>__state` holding "
            "the state. **No numeric missing codes such as -99 are ever written**, so an "
            "average can never include one."
        )
    else:
        add(
            "- **CSV:** state columns were **switched off** for this file, so an empty cell "
            "does not say why it is empty. Use the JSON export (or re-export with state "
            "columns) to tell `unanswered`, `irrelevant` and `not-reached` apart. No numeric "
            "missing codes such as -99 are ever written."
        )
    add("- **JSON:** every answer is `{state, value}`; `value` is `null` unless answered.")
    if csv_opts["multi"] == "columns":
        add(
            "- **Multiple choice** questions get one 0/1 column per choice, "
            "`<var>_<code>`, plus `<var>__state`."
        )
    else:
        add(
            "- **Multiple choice** answers are one cell: the chosen codes separated by "
            "spaces, in choice-list order."
        )
    add("- Timestamps are UTC, ISO 8601 with milliseconds (`2026-10-16T09:30:00.000Z`).")
    add(
        "- Decimals are exported as exact canonical text (`2.50` is `2.5`), never as binary floats."
    )
    add(
        "- CSV is UTF-8, RFC 4180 (CRLF line ends, quoted fields)"
        + (", with a byte order mark for Excel" if csv_opts["bom"] else "")
        + "."
    )
    if csv_opts["escapeFormulas"]:
        add(
            "- **Formula protection is on:** a cell starting with `=`, `+`, `-`, `@`, tab "
            "or carriage return gets a leading `'` so a spreadsheet shows it as text. Plain "
            "numbers such as `-3` are not changed. Strip one leading `'` from text cells "
            "to get the participant's exact input."
        )
    add("")

    sm = data["saveMode"]
    add(f"{h2} Save mode")
    add("")
    add(f"Mode: **{sm['mode'] or 'not recorded'}**. {sm['implications']}")
    add("")

    add(f"{h2} Response metadata columns")
    add("")
    add("| Column | Meaning |")
    add("|---|---|")
    for m in data["metaColumns"]:
        add(f"| `{m['column']}` | {_md(m['meaning'])} |")
    add("")

    add(f"{h2} Conditions")
    add("")
    if data["conditions"]:
        add(
            "Assigned by the server at session start (semantics §7). One column per "
            "condition, named after it, holding the level in force."
        )
        add("")
        add("| Column | Levels |")
        add("|---|---|")
        for c in data["conditions"]:
            levels = ", ".join(_code(v) for v in c["levels"])
            add(f"| `{c['name']}` | {levels} |")
    else:
        add("This version assigns no conditions.")
    add("")

    add(f"{h2} Randomisation")
    add("")
    if data["orders"]:
        add(
            "Each realised order is fixed at first reach and recorded per response as one "
            "cell: ids or codes separated by spaces, in the order shown. Empty means the "
            "participant never reached it. Every order is reproducible from `_seed`."
        )
        add("")
        add("| Column | What is ordered | Of |")
        add("|---|---|---|")
        picks = {r["id"]: r["pick"] for r in data["randomisers"]}
        for o in data["orders"]:
            what = {
                "blocks": "flow children of randomiser",
                "items": "items on page",
                "choices": "choices of question",
            }[o["kind"]]
            pick = picks.get(o["node"]) if o["kind"] == "blocks" else None
            extra = f" (shows {pick} of {len(o['of'])})" if pick else ""
            of = ", ".join(_code(x) for x in o["of"])
            add(f"| `{o['column']}` | {what} {_code(o['node'])}{extra} | {of} |")
    else:
        add("This version has no randomisers and no shuffled items or choices.")
    add("")

    add(f"{h2} Questions")
    add("")
    add("In survey (flow) order. Conditions refer to other variables by export name.")
    add("")
    for v in data["variables"]:
        add(f"{h3} `{v['name']}`")
        add("")
        add(f"- Type: {v['type']}. {TYPE_NOTES.get(v['type'], '')}".rstrip())
        if v.get("matrix"):
            add(
                f"- Row of matrix {_code(v['matrix'])}: "
                f"{_lang_text(v.get('matrixLabel'), langs)} (each row is its own variable)"
            )
        add(f"- Label: {_lang_text(v['label'], langs)}")
        if v.get("valueType"):
            add(f"- Slider: {v['valueType']} from {v['min']} to {v['max']} in steps of {v['step']}")
        if v.get("help"):
            add(f"- Help: {_lang_text(v['help'], langs)}")
        if v["id"] != v["name"]:
            add(f"- Stable id: {_code(v['id'])}")
        add(f"- Block / page: {_code(v['block'])} / {_code(v['page'])}")
        add(f"- Required: {'yes (while shown)' if v['required'] else 'no'}")
        add(f"- Shown if: {_code(v['showIf']) if v.get('showIf') else 'always'}")
        if v.get("constraint"):
            msg = v.get("constraintMessage")
            add(
                f"- Constraint: {_code(v['constraint'])}"
                + (f" (message: {_lang_text(msg, langs)})" if msg else "")
            )
        add(f"- CSV columns: {', '.join(_code(c) for c in v['csvColumns'])}")
        add(f"- Missing values: {v['missing']}")
        if v.get("choiceOrder") == "shuffle":
            add(
                "- Choice order: shuffled per participant, recorded in "
                f"`_order.choices.{v['name']}`"
            )
        if v.get("choices"):
            add("")
            lang_heads = " | ".join(f"Label ({lang})" for lang in langs)
            has_col = any("column" in c for c in v["choices"])
            add(f"| Code | {lang_heads} |" + (" Column |" if has_col else ""))
            add("|---|" + "---|" * len(langs) + ("---|" if has_col else ""))
            for c in v["choices"]:
                labels = " | ".join(_md(c["label"].get(lang, "")) for lang in langs)
                col = f" `{c['column']}` |" if has_col else ""
                add(f"| {_code(c['code'])} | {labels} |{col}")
        add("")

    others = data["otherVariables"]
    add(f"{h2} Other variables")
    add("")
    if others:
        add("| Column | Kind | Details |")
        add("|---|---|---|")
        for x in others:
            if x["kind"] == "embedded":
                detail = f"URL parameter {_code(x['urlParam'])}, {x['valueType']}"
                if x.get("default") is not None:
                    detail += f", default {_code(x['default'])}"
            else:
                detail = f"computed as {_code(x.get('expr', ''))}"
            add(f"| `{x['name']}` | {x['kind']} | {detail} |")
        add("")
        add(
            "Each has a `<var>__state` column like a question: `answered` when it has a "
            "value; an embedded variable without a value (no parameter and no default, or a "
            "malformed one) is `unanswered`; a computed one whose input was null is "
            "`not-reached` if every question it reads was not reached, `irrelevant` if each "
            "was not reached or hidden, otherwise `unanswered`."
        )
    else:
        add("None.")
    add("")

    if data["quotas"]:
        add(f"{h2} Quotas")
        add("")
        add("| Quota | Counts when | Limit | When full |")
        add("|---|---|---|---|")
        for q in data["quotas"]:
            full = f"outcome {_code(q['onFull']['outcome'])}"
            if q["onFull"]["block"]:
                full = f"show {_code(q['onFull']['block'])}, then {full}"
            add(f"| `{q['id']}` | {_code(q['when'])} | {q['limit']} | {full} |")
        add("")

    add(f"{h2} Custom code (hooks) and data exports")
    add("")
    if data["hooks"]:
        add(
            "This version runs researcher hooks. Data-export capabilities can send "
            "participant data off the platform (runtime-design §7a)."
        )
        add("")
        add("| Hook | Events | Reads | Data exports |")
        add("|---|---|---|---|")
        for h in data["hooks"]:
            add(
                f"| `{h['id']}` | {', '.join(h['events']) or '-'} | "
                f"{', '.join(h['reads']) or '-'} | {', '.join(h['dataExports']) or 'none'} |"
            )
    else:
        add("This version runs no custom code, so it has no data-export capabilities.")
    add("")
    return "\n".join(out)


def codebook(version: SurveyVersion, options: CsvOptions | None = None) -> Codebook:
    """The codebook for one version, for CSV files written with the same ``options``."""
    data = codebook_data(version, options)
    return Codebook(_render(data), data)


def codebook_combined(
    versions: Sequence[SurveyVersion], options: CsvOptions | None = None
) -> Codebook:
    """The codebook for a combined export: a note on how versions were merged, the union
    of columns with the versions each appears in, then every version's own codebook."""
    opts = options or CsvOptions()
    ordered = sorted(versions, key=lambda v: (v.number or 0, v.checksum or ""))
    split = sorted(split_names([build_layout(v) for v in ordered]))
    books = [codebook_data(v, opts, split) for v in ordered]
    if len(books) == 1:
        return Codebook(_render(books[0]), books[0])
    union: list[str] = []
    where: dict[str, list[Any]] = {}
    for b in books:
        for c in b["csv"]["columns"]:
            if c not in where:
                union.append(c)
                where[c] = []
            where[c].append(b["survey"]["version"])
    defs: dict[str, dict[Any, Any]] = {}
    for b in books:
        suffix = f"_v{b['survey']['version'] if b['survey']['version'] is not None else 0}"
        for v in b["variables"]:
            key = {k: v.get(k) for k in ("type", "choices", "showIf", "required", "constraint")}
            name = v["name"]
            if name.endswith(suffix) and name[: -len(suffix)] in split:
                name = name[: -len(suffix)]  # compare a split question under its own name
            defs.setdefault(name, {})[b["survey"]["version"]] = key
    changed = sorted(n for n, per in defs.items() if len({repr(x) for x in per.values()}) > 1)
    all_versions = [b["survey"]["version"] for b in books]
    data = {
        "format": FORMAT,
        "combined": True,
        "versions": all_versions,
        "columns": [{"column": c, "versions": where[c]} for c in union],
        "changedVariables": changed,
        "splitVariables": split,
        "codebooks": books,
    }
    first = books[0]["survey"]
    langs = first["languages"]
    out = [
        f"# Codebook: {_lang_text(first['title'], langs)} (combined versions)",
        "",
        "## How versions were combined",
        "",
        f"This file merges the responses of versions {', '.join(map(str, all_versions))}. "
        "Each response belongs to exactly one version (the `_version` column) and was "
        "collected with that version's questions, wording and logic; each version's own "
        "codebook follows below.",
        "",
        "- Columns are the union of every version's columns, in order of first appearance "
        "(oldest version first).",
        "- **A column that a response's version does not have is empty, including its "
        "`__state` cell.** An empty `__state` therefore means *not in this version*, never "
        "one of the four states.",
        "- **A question whose type or choice codes changed between versions is split:** "
        "each version exports it under its own columns, `<var>_v<N>` (N = version), so "
        "differently coded data is never pooled in one column.",
        "- Any other change (wording, display logic, required flag, constraint) keeps one "
        "column; compare the per-version codebooks before pooling it.",
        "",
    ]
    if split:
        out.append(
            "Split into per-version columns (type or choices changed): "
            + ", ".join(f"`{n}`" for n in split)
            + "."
        )
        out.append("")
    if changed:
        out.append(
            "Variables whose type, choices, display logic, required flag or constraint "
            "differ between versions: " + ", ".join(f"`{n}`" for n in changed) + "."
        )
        out.append("")
    partial = [c for c in union if len(where[c]) != len(all_versions)]
    if partial:
        out.append("| Column | Present in versions |")
        out.append("|---|---|")
        for c in partial:
            out.append(f"| `{c}` | {', '.join(map(str, where[c]))} |")
        out.append("")
    for b in books:
        out.append(_render(b, heading="##"))
    return Codebook("\n".join(out), data)
