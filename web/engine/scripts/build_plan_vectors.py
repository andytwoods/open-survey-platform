"""Plan-compile parity vectors (task CE3) into web/engine/.build/plan-vectors.json.

    uv run python web/engine/scripts/build_plan_vectors.py

For every survey we can find, `osp_runtime.plan.compile_survey` (Python, authoritative)
gives the expected plan (and so its canonical JSON and checksum) or diagnostics, plus
`runtime_config` with and without a save-mode override. `test/compile-parity.test.ts`
compiles the same input with the TS `compileSurvey` and asserts byte identity.

Inputs: every `fixtures/*/survey.json`; every `osp-spec` test case (valid and invalid);
every other committed osp-survey document (ops, targets, runtime e2e, builder dev); a set
of hand-written edge cases (rich text, pipes, languages, consent, endings, redirects,
quotas, external tasks, hooks, matrices, sliders, randomiser/assign, decimal and big
integer literals, a hook manifest given beside the survey); and seeded random mutations
of the valid surveys (texts turned rich or per-language, defaults flipped).
Also: `segments` on tricky strings, `consent_version`, `embed_theme`.
"""

from __future__ import annotations

import copy
import json
import random
import sys
from pathlib import Path
from typing import Any

from osp_runtime.plan import (
    canonical_json,
    compile_survey,
    consent_version,
    embed_theme,
    runtime_config,
    segments,
)

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "web" / "engine" / ".build"

OTHER_SURVEYS = [
    "python/osp-ops/tests/base_survey.json",
    "python/osp-targets/tests/data/instruments-survey.json",
    "python/osp-targets/tests/data/imports/*.expected.json",
    "web/runtime/e2e/surveys/*/survey.json",
    "web/builder/src/dev/conditions/*.json",
]


def _survey_of(data: Any) -> Any:
    if (
        isinstance(data, dict)
        and "specVersion" not in data
        and isinstance(data.get("survey"), dict)
    ):
        return data["survey"]
    return data


def found_surveys() -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for f in sorted((ROOT / "fixtures").glob("*/survey.json")):
        out.append((f"fixture/{f.parent.name}", json.loads(f.read_text())))
    for f in sorted((ROOT / "python/osp-spec/tests/cases").glob("*/*.json")):
        out.append((f"spec-case/{f.parent.name}/{f.stem}", json.loads(f.read_text())["survey"]))
    for pattern in OTHER_SURVEYS:
        for f in sorted(ROOT.glob(pattern)):
            data = _survey_of(json.loads(f.read_text()))
            if isinstance(data, dict) and data.get("specVersion") == "osp-survey/0.1":
                out.append((f"other/{f.relative_to(ROOT)}", data))
    return out


# --- Hand-written edge cases -----------------------------------------------------------


def _q(qid: str, qtype: str = "integer", **kw: Any) -> dict:
    return {"id": qid, "type": qtype, "label": kw.pop("label", f"Question {qid}"), **kw}


def _base(*items: dict, **kw: Any) -> dict:
    survey: dict[str, Any] = {
        "specVersion": "osp-survey/0.1",
        "id": "srv_edge",
        "metadata": {"title": "Edge", "languages": ["en"]},
        "blocks": [{"id": "b1", "pages": [{"id": "p1", "items": list(items) or [_q("q1")]}]}],
        "flow": [{"type": "block", "id": "f_b1", "block": "b1"}],
    }
    survey.update(kw)
    return survey


def _rich(*content: Any) -> dict:
    return {"type": "rich", "blocks": [{"type": "p", "content": list(content)}]}


HOOKS = {
    "format": "osp-hooks/1",
    "source": "osp.on('onPageShown', function (ctx, data, act) {});",
    "handlers": {"onPageShown": {"reads": ["q1"], "writes": []}},
    "redirects": {
        "hookdone": {"url": "https://example.org/done?c={code}", "params": {"code": {}}},
        "shared": {
            "url": "https://example.org/hook?c={code}",
            "params": {"code": {"pattern": "[a-z]+"}},
        },
    },
}

TEMPLATES = {
    "prolific": {
        "url": "https://app.prolific.com/submissions/complete?cc={code}",
        "params": {"code": {"pattern": "[A-Z0-9]{6,8}"}},
    },
    "task": {
        "url": "https://tasks.example.org/run?pid={pid}&c={cond}",
        "params": {"pid": {}, "cond": {}},
    },
}


def edge_cases() -> list[tuple[str, Any, Any]]:
    """(name, survey, hooks option)."""
    cases: list[tuple[str, Any, Any]] = []
    add = lambda name, s, hooks=None: cases.append((f"edge/{name}", s, hooks))  # noqa: E731

    add("minimal", _base())
    add("version-3", _base(version=3))
    add(
        "settings",
        _base(
            settings={
                "backNavigation": False,
                "saveMode": "end-only",
                "localCopy": "memory",
                "resumeExpiryDays": 7,
                "retention": {"kind": "indefinite"},
            }
        ),
    )
    add(
        "all-types",
        _base(
            _q("qi", "integer", min=0, max=10, required=True, help="Help"),
            _q("qd", "decimal", min="0.5", max=7, constraintMessage="Bad"),
            _q("qt", "text", multiline=True),
            _q("qt2", "text", multiline=False),
            _q("qdate", "date"),
            _q(
                "qs",
                "single",
                choices=[{"value": 1, "label": "One"}, {"value": "b", "label": "Bee"}],
            ),
            _q("qm", "multi", choiceList="cl", choiceOrder="shuffle"),
            _q("qn", "note", label="Note ${qi} and ${ qs }"),
            choiceLists=[
                {
                    "id": "cl",
                    "choices": [{"value": "x", "label": "X"}, {"value": "y", "label": "Y"}],
                }
            ],
        ),
    )
    pipes = [
        "${q1}",
        "a ${ q1 } b",
        "${$trial} of ${$position.of} ${$position.index} ${$pagesDone} ${$language} ${$device}",
        "${$response.id} ${$session.id} ${$outcome}",
        "${bad id} ${} ${1abc} ${$nope} $q1 {q1} ${q1",
        "${ q1　}",
        "${\x1cq1\x1f}",
        "${﻿q1}",
        "${q1\n}",
        "😀${q1}é${q1}${q1}",
        "",
        "${q1}${q1}",
    ]
    for i, text in enumerate(pipes):
        add(f"pipes-{i}", _base(_q("q1"), _q("n1", "note", label=text)))
        add(f"segments-in-help-{i}", _base(_q("q1"), _q("q2", help=text)))
    rich = _rich(
        {"text": "Bold ", "marks": ["b"]},
        {"text": "link", "href": "https://example.org", "marks": None, "lang": None},
        {"text": "fr", "lang": "fr"},
        {"pipe": "q1"},
        {"pipe": "$trial"},
        {"br": True},
    )
    rich_all = {
        "type": "rich",
        "blocks": [
            {"type": "h", "level": 2, "content": [{"text": "Heading"}]},
            {"type": "p", "content": [{"text": "Para ", "marks": ["i", "b"]}, {"pipe": "q1"}]},
            {"type": "ul", "items": [[{"text": "one"}], [{"pipe": "q1"}, {"text": " two"}]]},
            {"type": "ol", "items": [[{"text": "first"}]]},
        ],
    }
    add("rich-note", _base(_q("q1"), _q("n1", "note", label=rich_all)))
    add("rich-label-runs", _base(_q("q1"), _q("n1", "note", label=rich)))
    add("rich-help", _base(_q("q1"), _q("q2", help=_rich({"text": "see "}, {"pipe": "q1"}))))
    add(
        "rich-bad-pipe",
        _base(_q("q1"), _q("n1", "note", label=_rich({"pipe": "not valid"}, {"pipe": "q1\n"}))),
    )
    add("rich-empty", _base(_q("q1"), _q("n1", "note", label={"type": "rich", "blocks": []})))
    add(
        "languages",
        {
            **_base(
                _q("q1", label={"en": "One", "de": "Eins", "fr": "Un"}),
                _q("q2", label={"en": "Two"}),
                _q("q3", label={"de": "Drei", "fr": _rich({"text": "Trois", "marks": ["b"]})}),
                _q(
                    "q4",
                    "single",
                    label="Plain",
                    choices=[
                        {"value": 1, "label": {"en": "Yes", "de": "Ja"}},
                        {"value": 2, "label": "No"},
                    ],
                ),
            ),
            "metadata": {
                "title": {"en": "Edge", "de": "Kante"},
                "languages": ["en", "de", "fr"],
                "defaultLanguage": "de",
            },
        },
    )
    add(
        "languages-no-default",
        {
            **_base(_q("q1", label={"fr": "Un", "de": "Eins"})),
            "metadata": {"title": "T", "languages": ["en", "de", "fr"]},
        },
    )
    add("consent-defaults", _base(consent={"text": "Do you agree?"}))
    add(
        "consent-full",
        {
            **_base(
                consent={
                    "text": _rich({"text": "Read this", "marks": ["b"]}),
                    "agreeLabel": {"en": "Yes", "de": "Ja"},
                    "declineLabel": "No",
                    "declineOutcome": "nope",
                    "countDeclines": True,
                }
            ),
            "metadata": {"title": "T", "languages": ["en", "de"]},
        },
    )
    endings = {
        "complete": {
            "title": "Thanks ${q1}",
            "body": _rich({"text": "Body "}, {"pipe": "$response.id"}),
            "summary": "answers",
            "redirect": {
                "template": "prolific",
                "params": {"code": "C0DE${q1}"},
                "delay": 0,
                "mode": "link",
                "label": "Go",
            },
        },
        "screened": {"status": "none"},
        "hook-failed": {"body": "Sorry"},
        "aaa": {"redirect": {"template": "task", "params": {"pid": "${pid}", "cond": "x"}}},
    }
    flow_end = [
        {"type": "block", "id": "f_b1", "block": "b1"},
        {"type": "end", "id": "e_s", "outcome": "screened", "message": "Bye ${q1}"},
    ]
    variables = [{"kind": "embedded", "id": "pid", "param": "PID"}]
    add(
        "endings-redirects",
        _base(
            settings={"endings": endings, "redirectTemplates": TEMPLATES},
            flow=flow_end,
            variables=variables,
        ),
    )
    add(
        "endings-redirects-hooks",
        _base(
            settings={"endings": endings, "redirectTemplates": TEMPLATES},
            flow=flow_end,
            variables=variables,
            hooks=copy.deepcopy(HOOKS),
        ),
    )
    add("hooks-own", _base(hooks=copy.deepcopy(HOOKS)))
    add("hooks-option", _base(), copy.deepcopy(HOOKS))
    add(
        "hooks-option-with-templates",
        _base(settings={"redirectTemplates": TEMPLATES}, hooks=copy.deepcopy(HOOKS)),
        {**copy.deepcopy(HOOKS), "redirects": None, "urlParams": None},
    )
    add("hooks-option-bad-shape", _base(), {"format": "osp-hooks/1", "handlers": {}})
    add("hooks-option-not-json", _base(), {"format": "osp-hooks/1", "source": 1})
    add("templates-only", _base(settings={"redirectTemplates": TEMPLATES}))
    blocks2 = [
        {"id": "b1", "pages": [{"id": "p1", "items": [_q("q1")]}]},
        {
            "id": "b2",
            "pages": [{"id": "p2", "items": [_q("q2")]}, {"id": "p3", "items": [_q("q3")]}],
        },
        {"id": "full", "pages": [{"id": "pf", "items": [_q("nf", "note", label="Full")]}]},
    ]
    gt = {
        "kind": "compare",
        "op": ">",
        "left": {"kind": "ref", "id": "q1"},
        "right": {"kind": "int", "value": 5},
    }
    add(
        "quotas",
        _base(
            blocks=blocks2,
            quotas=[
                {
                    "id": "qa",
                    "when": gt,
                    "limit": 10,
                    "onFull": {"outcome": "overquota", "block": "full"},
                },
                {
                    "id": "qb",
                    "when": {"kind": "bool", "value": True},
                    "limit": 0,
                    "onFull": {"outcome": "full2"},
                },
            ],
            flow=[
                {"type": "block", "id": "f1", "block": "b1"},
                {"type": "quotaCheck", "id": "qc1", "quota": "qa"},
                {
                    "type": "branch",
                    "id": "br",
                    "if": gt,
                    "then": [{"type": "quotaCheck", "id": "qc2", "quota": "qb"}],
                    "else": [{"type": "block", "id": "f2", "block": "b2"}],
                },
            ],
        ),
    )
    add(
        "random-assign",
        _base(
            blocks=blocks2,
            variables=[
                {"kind": "assigned", "id": "cond", "levels": ["a", "b", 3]},
                {"kind": "assigned", "id": "cond2", "name": "Cond2", "levels": [1]},
                {"kind": "assigned", "id": "unused", "levels": [1, 2]},
                {
                    "kind": "embedded",
                    "id": "e1",
                    "param": "x",
                    "valueType": "integer",
                    "default": 4,
                },
                {"kind": "embedded", "id": "e2", "param": "y", "default": "z"},
                {
                    "kind": "computed",
                    "id": "c1",
                    "expr": {
                        "kind": "arith",
                        "op": "+",
                        "left": {"kind": "ref", "id": "cond2"},
                        "right": {"kind": "int", "value": 1},
                    },
                },
            ],
            flow=[
                {"type": "assign", "id": "as1", "variables": ["cond", "cond2"]},
                {
                    "type": "randomiser",
                    "id": "r1",
                    "children": [
                        {"type": "block", "id": "f1", "block": "b1"},
                        {"type": "block", "id": "f2", "block": "b2"},
                    ],
                },
                {
                    "type": "randomiser",
                    "id": "r2",
                    "pick": 1,
                    "children": [
                        {"type": "end", "id": "e1n", "outcome": "a"},
                        {"type": "end", "id": "e2n"},
                    ],
                },
            ],
        ),
    )
    add(
        "external-task",
        _base(
            settings={"redirectTemplates": TEMPLATES},
            variables=[
                {"kind": "embedded", "id": "pid", "param": "PID"},
                {"kind": "embedded", "id": "score", "param": "score", "valueType": "integer"},
            ],
            flow=[
                {"type": "block", "id": "f_b1", "block": "b1"},
                {
                    "type": "externalTask",
                    "id": "x1",
                    "template": "task",
                    "params": {"pid": "${pid}", "cond": "lit ${$session.id}"},
                    "returns": ["score"],
                },
                {
                    "type": "externalTask",
                    "id": "x2",
                    "template": "task",
                    "params": {"pid": "a", "cond": "b"},
                },
            ],
        ),
    )
    cols = [
        {"value": 1, "label": "Agree"},
        {"value": 2, "label": _rich({"text": "Dis", "marks": ["i"]})},
    ]
    add(
        "matrix",
        _base(
            {
                "id": "m1",
                "type": "matrix",
                "label": "Rate",
                "help": "help",
                "required": True,
                "rows": [
                    {"id": "a", "label": "A"},
                    {"id": "b", "label": "B ${$trial}", "required": False},
                ],
                "choices": cols,
            },
            {
                "id": "m2",
                "type": "matrix",
                "name": "mat_two",
                "label": {"en": "Rate 2"},
                "rows": [{"id": "x", "label": "X", "required": True}],
                "choiceList": "cl",
            },
            choiceLists=[{"id": "cl", "choices": cols}],
        ),
    )
    add(
        "slider",
        _base(
            _q("s1", "slider"),
            _q(
                "s2",
                "slider",
                valueType="decimal",
                min="-1.5",
                max="2.50",
                step="0.25",
                minLabel="Low",
                maxLabel=_rich({"text": "High"}),
            ),
            _q("s3", "slider", min=10, max=20, step=5, required=True),
        ),
    )
    decimals = [
        "1.50",
        " 2.5 ",
        "007.50",
        "1E+3",
        "1e3",
        "-0.0",
        "0.000",
        "1_000",
        ".5",
        "5.",
        "1e-7",
        "0.0000001",
        "123456789012345678901234567890.5",
        "+3",
        1.5,
        0.1,
        2.5e-8,
        1e21,
    ]
    for i, d in enumerate(decimals):
        expr = {
            "kind": "compare",
            "op": "<",
            "left": {"kind": "ref", "id": "q1"},
            "right": {"kind": "decimal", "value": d},
        }
        add(f"decimal-literal-{i}", _base(_q("q1", "decimal"), _q("q2", showIf=expr)))
    for i, n in enumerate([2**60, -(2**60), 2**53 - 1, -(2**53 - 1), 0]):
        expr = {
            "kind": "compare",
            "op": "<",
            "left": {"kind": "ref", "id": "q1"},
            "right": {"kind": "int", "value": n},
        }
        add(f"int-literal-{i}", _base(_q("q1"), _q("q2", constraint=expr)))
    all_kinds = {
        "kind": "and",
        "args": [
            {
                "kind": "or",
                "args": [
                    {"kind": "answered", "ref": {"id": "q1"}},
                    {"kind": "bool", "value": True},
                ],
            },
            {
                "kind": "not",
                "arg": {
                    "kind": "contains",
                    "ref": {"kind": "ref", "id": "qm"},
                    "value": {"kind": "text", "value": "x"},
                },
            },
            {
                "kind": "compare",
                "op": "==",
                "left": {
                    "kind": "if",
                    "cond": {"kind": "bool", "value": False},
                    "then": {"kind": "ref", "id": "q1"},
                    "else": {"kind": "int", "value": 2},
                },
                "right": {
                    "kind": "arith",
                    "op": "/",
                    "left": {"kind": "int", "value": 1},
                    "right": {"kind": "decimal", "value": "3"},
                },
            },
        ],
    }
    add(
        "expression-kinds",
        _base(
            _q("q1"),
            _q("qm", "multi", choices=[{"value": "x", "label": "X"}]),
            {"id": "p2_note", "type": "note", "label": "n", "showIf": all_kinds},
        ),
    )
    add(
        "page-showif-order",
        _base(
            blocks=[
                {
                    "id": "b1",
                    "pages": [{"id": "p1", "items": [_q("q1"), _q("q2")], "itemOrder": "shuffle"}],
                },
                {
                    "id": "b2",
                    "title": "builder only",
                    "pages": [
                        {"id": "p2", "title": "Page title", "showIf": gt, "items": [_q("q3")]}
                    ],
                },
                {"id": "b_unused", "pages": [{"id": "pu", "items": [_q("qu")]}]},
            ],
            flow=[
                {"type": "block", "id": "f1", "block": "b1"},
                {"type": "block", "id": "f2", "block": "b2"},
            ],
        ),
    )
    add(
        "names-custom-source",
        _base(
            _q("q1", name="age_years", custom={"construct": "age", "w": 1.5, "flag": True}),
            _q(
                "q2", source={"bank": "phq9", "version": 1, "library": "bundled", "item": "phq9_q1"}
            ),
        ),
    )
    add(
        "nulls",
        _base(
            _q("q1", help=None, showIf=None, name=None, constraint=None), consent=None, hooks=None
        ),
    )
    # Refused by the validator: the TS must refuse too (with the validator, CE4).
    add(
        "bad-unknown-ref",
        _base(_q("q2", showIf={"kind": "answered", "ref": {"kind": "ref", "id": "nope"}})),
    )
    add("bad-not-object", ["not", "a", "survey"])
    add("bad-spec-version", {**_base(), "specVersion": "osp-survey/9"})
    return cases


# --- Random mutations of valid surveys ----------------------------------------------

TEXT_KEYS = ("label", "help", "message", "constraintMessage", "body", "minLabel", "maxLabel")


def _mutate(r: random.Random, node: Any, langs: list[str]) -> Any:
    if isinstance(node, list):
        return [_mutate(r, x, langs) for x in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k in TEXT_KEYS and isinstance(v, str) and r.random() < 0.4:
            roll = r.random()
            if roll < 0.4:
                v = _rich(
                    {"text": v, "marks": r.choice([["b"], ["i"], ["b", "i"], None])},
                    {"pipe": r.choice(["$trial", "$pagesDone", "$language"])},
                )
            elif roll < 0.7:
                v = {lang: f"{v} [{lang}]" for lang in r.sample(langs, r.randint(1, len(langs)))}
            else:
                v = v + " ${" + r.choice([" $trial ", "$trial", "$device", "\u00a0$language"]) + "}"
        out[k] = _mutate(r, v, langs)
    if node.get("type") in ("single", "multi") and r.random() < 0.3:
        out["choiceOrder"] = r.choice(["fixed", "shuffle"])
    if node.get("type") in ("integer", "text", "single") and r.random() < 0.2:
        out["required"] = not node.get("required", False)
    return out


def mutations(sources: list[tuple[str, Any]], per: int = 4) -> list[tuple[str, Any, Any]]:
    r = random.Random(20261018)
    out = []
    for name, survey in sources:
        if not isinstance(survey, dict):
            continue
        langs = list(survey.get("metadata", {}).get("languages") or ["en"])
        for i in range(per):
            out.append((f"mutant/{name}/{i}", _mutate(r, copy.deepcopy(survey), langs), None))
    return out


# --- Vectors ---------------------------------------------------------------------------


def vector(name: str, survey: Any, hooks: Any) -> dict:
    plan, diags = compile_survey(copy.deepcopy(survey), hooks=copy.deepcopy(hooks))
    row: dict[str, Any] = {
        "name": name,
        "survey": survey,
        "diagnostics": [d.model_dump(mode="json") for d in diags],
    }
    if hooks is not None:
        row["hooks"] = hooks
    if plan is None:
        row["plan"] = None
        return row
    row["plan"] = plan
    row["canonical"] = canonical_json(plan)
    row["checksum"] = plan["checksum"]
    row["runtimeConfig"] = runtime_config(plan)
    row["runtimeConfigEndOnly"] = runtime_config(plan, save_mode="end-only")
    return row


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    found = found_surveys()
    cases = [(n, s, None) for n, s in found] + edge_cases()
    valid_sources = [(n, s) for n, s in found if compile_survey(copy.deepcopy(s))[0] is not None]
    cases += mutations(valid_sources)
    rows = [vector(*c) for c in cases]
    texts = [
        "",
        "plain",
        "${q1}",
        " ${ q1 } ",
        "${$trial}${$outcome}",
        "${a b}",
        "${ q }",
        "${\x1dq}",
    ]
    texts += [
        "${﻿q}",
        "${q\n}",
        "x${}y",
        "${{q}}",
        "😀${q1}😀",
        "${$position.index}",
        "${$pos}",
        "$${q}",
    ]
    extras = {
        "segments": [[t, segments(t)] for t in texts],
        "consentVersion": [
            [t, a, d, consent_version(t, a, d)]
            for t, a, d in [
                ({"en": ["x"]}, {"en": ["Yes"]}, {"en": ["No"]}),
                ({"de": ["é😀"]}, {"de": [{"pipe": "q"}]}, {"de": []}),
            ]
        ],
        "embedTheme": [],
    }
    first = next(r for r in rows if r["plan"] is not None)
    theme = {"preset": "clean", "colors": {"accent": "#123456"}, "radius": 4}
    extras["embedTheme"].append([first["name"], theme, embed_theme(first["plan"], theme)])
    (OUT / "plan-vectors.json").write_text(json.dumps({"rows": rows, **extras}, ensure_ascii=False))
    ok = sum(1 for r in rows if r["plan"] is not None)
    print(f"plan vectors: {len(rows)} surveys ({ok} compiled, {len(rows) - ok} refused)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
