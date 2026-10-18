"""SurveyJS JSON export (task XP1): every survey exports to valid, deterministic JSON;
every non-native feature used is reported with a JSON pointer that resolves in the survey;
golden files for six fixtures; every fixture reads back through our own SurveyJS importer
with the same questions and the same logic; feature checks on small surveys.

Regenerate the goldens with ``OSP_UPDATE_GOLDEN=1``.
"""

from __future__ import annotations

import copy
import json
import os
import random
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from osp_expr.ast import EXPR_ADAPTER, Expr
from osp_expr.evaluate import evaluate_condition
from osp_expr.static import references
from osp_spec import Survey, parse
from osp_spec.model import (
    ComputedVariable,
    EmbeddedVariable,
    MatrixQuestion,
    MultiQuestion,
    NoteQuestion,
    SingleQuestion,
    matrix_row_id,
)
from osp_spec.richtext import to_plain
from osp_targets.imports import import_surveyjs
from osp_targets.surveyjs import SURVEYJS, build_surveyjs, export_surveyjs, feature_uses

REPO = Path(__file__).resolve().parents[3]
CASES = sorted((REPO / "python/osp-spec/tests/cases/valid").glob("*.json"))
FIXTURES = sorted((REPO / "fixtures").glob("*/survey.json"))
GOLDEN = Path(__file__).parent / "data/surveyjs"
GOLDEN_FIXTURES = [
    "11-end-nodes",
    "13-randomiser-blocks",
    "17-piping",
    "20-worked-example",
    "38-matrix",
    "41-rich-text",
]


def _fixture_survey(path: Path) -> Any:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("survey", data) if isinstance(data, dict) else data


SURVEYS: list[tuple[str, Any]] = [
    (f"case/{p.stem}", json.loads(p.read_text(encoding="utf-8"))["survey"]) for p in CASES
] + [(f"fixture/{p.parent.name}", _fixture_survey(p)) for p in FIXTURES]


def _resolve(doc: Any, ptr: str) -> Any:
    if ptr == "":
        return doc
    for raw in ptr.split("/")[1:]:
        part = raw.replace("~1", "/").replace("~0", "~")
        doc = doc[int(part)] if isinstance(doc, list) else doc[part]
    return doc


def _elements(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [el for page in doc["pages"] for el in page["elements"]]


def test_there_are_surveys() -> None:
    assert len(CASES) >= 10
    assert len(FIXTURES) >= 30


@pytest.mark.parametrize(("label", "data"), SURVEYS, ids=[s[0] for s in SURVEYS])
def test_export_is_valid(label: str, data: Any) -> None:
    body, diags = export_surveyjs(data)
    assert not [d for d in diags if d.severity == "error"], diags
    doc = json.loads(body)  # raises if not JSON
    survey, _ = parse(data)
    assert survey is not None
    assert doc["pages"] and all(isinstance(p["elements"], list) for p in doc["pages"])

    # Names: unique ignoring case (SurveyJS reads `{name}` case-insensitively).
    names = [el["name"] for el in _elements(doc)]
    names += [cv["name"] for cv in doc.get("calculatedValues", [])]
    assert len({n.lower() for n in names}) == len(names)
    # Every localisable string names only the survey's languages.
    langs = set(survey.metadata.languages)

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            if "default" in v and all(isinstance(x, str) for x in v.values()):
                assert set(v) - {"default"} <= langs, v
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(doc)

    # Diagnostics: level from the table, pointer resolves in the survey document.
    raw = json.loads(json.dumps(data))
    for d in diags:
        assert d.target == "surveyjs"
        assert d.feature in SURVEYJS, d
        cap = SURVEYJS[d.feature]
        assert d.level == cap.level != "native"
        assert d.code == f"surveyjs.{cap.level}"
        assert (
            d.severity
            == {"lowered": "info", "approximated": "warning", "unsupported": "loss"}[cap.level]
        )
        _resolve(raw, d.pointer)

    # Every non-native field the survey uses has a diagnostic at its pointer.
    reported = {(d.feature, d.pointer) for d in diags}
    for key, ptr, _value in feature_uses(survey):
        if SURVEYJS[key].level != "native":
            assert (key, ptr) in reported, (key, ptr)


@pytest.mark.parametrize(("label", "data"), SURVEYS, ids=[s[0] for s in SURVEYS])
def test_deterministic_bytes(label: str, data: Any) -> None:
    a, da = export_surveyjs(data)
    b, db = export_surveyjs(copy.deepcopy(data))
    assert a == b
    assert da == db


def test_accepts_survey_model() -> None:
    data = json.loads(CASES[0].read_text(encoding="utf-8"))["survey"]
    survey, _ = parse(data)
    assert survey is not None
    assert export_surveyjs(survey) == export_surveyjs(data)


@pytest.mark.parametrize("name", GOLDEN_FIXTURES)
def test_golden(name: str) -> None:
    body, diags = export_surveyjs(_fixture_survey(REPO / "fixtures" / name / "survey.json"))
    got_diags = "".join(
        f"{d.severity}\t{d.feature}\t{d.pointer}\n" for d in diags
    )  # messages are long; the table holds them
    path_json = GOLDEN / f"{name}.json"
    path_diags = GOLDEN / f"{name}.diagnostics.tsv"
    if os.environ.get("OSP_UPDATE_GOLDEN") == "1":
        GOLDEN.mkdir(parents=True, exist_ok=True)
        path_json.write_bytes(body)
        path_diags.write_text(got_diags, encoding="utf-8", newline="\n")
    assert body == path_json.read_bytes(), f"{name}: regenerate with OSP_UPDATE_GOLDEN=1"
    assert got_diags == path_diags.read_text(encoding="utf-8")


def test_never_raises_on_bad_input() -> None:
    for bad in (None, 5, "x", [], {}, {"specVersion": "osp-survey/0.1"}):
        body, diags = export_surveyjs(bad)  # type: ignore[arg-type]
        assert body == b""
        assert diags and all(d.severity == "error" for d in diags)
        assert diags[0].code.startswith("surveyjs.error.")


# --- Round trip through our own importer -----------------------------------------------------
#
# export → import_surveyjs → the same questions (by name), types, texts, choices, rows,
# required flags, orders, bounds, and conditions and constraints that mean the same (checked
# by evaluating both on random answers). Accepted differences, all reported as diagnostics
# by one side or the other:
#
# - integer questions come back as decimal (SurveyJS has no whole-number input; the export's
#   regex validator is not read back);
# - formatting is gone (titles are plain text; notes come back as their text, with the help
#   after it), and `${$built-in}` pipes are dropped;
# - questions in blocks the flow never shows (a quota's `onFull.block`) are not exported;
# - the flow comes back as page conditions in one block, end texts only as the default
#   completion text, and a matrix with only some rows required as not required;
# - conditions on assigned or embedded variables are not read back (the importer knows no
#   such variable), nor are quotas, consent, endings' extras or the theme.


def _questions_in_flow(s: Survey) -> list[Any]:
    placed: list[str] = []

    def walk(nodes: list[Any]) -> None:
        for n in nodes:
            if n.type == "block":
                placed.append(n.block)
            elif n.type == "branch":
                walk(n.then)
                walk(n.else_)
            elif n.type == "randomiser":
                walk(n.children)

    walk(s.flow)
    blocks = {b.id: b for b in s.blocks}
    return [q for bid in dict.fromkeys(placed) for page in blocks[bid].pages for q in page.items]


def _flat(text: Any, lang: str, base: str) -> str:
    """One language of a `Text` as words: formatting, whitespace and built-in pipes gone."""
    if text is None:
        return ""
    if isinstance(text, dict) and not ("blocks" in text and text.get("type") == "rich"):
        text = text.get(lang, text.get(base, next(iter(text.values()), "")))
    s = to_plain(text)
    s = re.sub(r"\$\{\$[^}]*\}", "", s)
    s = re.sub(r"^\s*(?:- |\d+\. )", "", s, flags=re.M)
    return " ".join(s.split())


def _choices(s: Survey, q: Any) -> list[Any]:
    if q.choiceList is not None:
        return next(cl.choices for cl in s.choiceLists if cl.id == q.choiceList)
    return q.choices or []


def _domain(qtype: str | None, choices: list[Any], literals: list[Any]) -> list[Any]:
    if qtype in ("single",):
        return [None, *choices]
    if qtype == "multi":
        return [None, *[[c] for c in choices], choices[:2], choices]
    if qtype == "text":
        return [None, "a", "b", *[x for x in literals if isinstance(x, str)]]
    if qtype == "date":
        return [None, "2020-01-01", "2026-10-18", *[x for x in literals if isinstance(x, str)]]
    nums = [x for x in literals if isinstance(x, (int, Decimal))]
    return [None, -1, 0, 1, 2, 3, 5, 10, Decimal("2.5"), *nums, *[n + 1 for n in nums]]


def _literals(e: Any) -> list[Any]:
    out: list[Any] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            if v.get("kind") in ("int", "text"):
                out.append(v["value"])
            elif v.get("kind") == "decimal":
                out.append(Decimal(str(v["value"])))
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(json.loads(EXPR_ADAPTER.dump_json(e)) if not isinstance(e, dict) else e)
    return out


class _RoundTrip:
    def __init__(self, data: Any) -> None:
        survey, _ = parse(data)
        assert survey is not None
        self.s = survey
        self.base = survey.metadata.defaultLanguage or survey.metadata.languages[0]
        result, _diags = build_surveyjs(data)
        assert result is not None
        self.export = result
        self.back = import_surveyjs(result.json)
        assert self.back.survey is not None, self.back.diagnostics
        self.theirs = {
            q["id"]: q for b in self.back.survey["blocks"] for p in b["pages"] for q in p["items"]
        }
        # Our id → their id (the SurveyJS name they claimed it back under).
        self.ids: dict[str, str] = {}
        self.types: dict[str, str] = {}
        self.values: dict[str, list[Any]] = {}
        for b in survey.blocks:
            for page in b.pages:
                for q in page.items:
                    name = getattr(q, "name", None) or q.id
                    self.ids[q.id] = name
                    self.types[q.id] = q.type
                    if isinstance(q, SingleQuestion | MultiQuestion):
                        self.values[q.id] = [c.value for c in _choices(survey, q)]
                    if isinstance(q, MatrixQuestion):
                        for r in q.rows:
                            rid = matrix_row_id(q.id, r.id)
                            self.ids[rid] = f"{name}_{r.id}"
                            self.types[rid] = "single"
                            self.values[rid] = [c.value for c in _choices(survey, q)]
        self.skip: set[str] = set()  # ids the importer cannot know
        for v in survey.variables:
            self.ids[v.id] = v.name or v.id
            if isinstance(v, ComputedVariable):
                self.types[v.id] = "decimal"
            else:
                self.skip.add(v.id)
                self.types[v.id] = v.valueType if isinstance(v, EmbeddedVariable) else "assigned"

    def problems(self) -> list[str]:
        out: list[str] = []
        langs = self.s.metadata.languages
        back_meta = self.back.survey["metadata"]
        if sorted(back_meta["languages"]) != sorted(langs):
            out.append(f"languages {langs} → {back_meta['languages']}")
        if back_meta.get("defaultLanguage", back_meta["languages"][0]) != self.base:
            out.append("default language")
        for q in _questions_in_flow(self.s):
            out += self._question(q)
        for v in self.s.variables:
            if isinstance(v, ComputedVariable) and not (set(references(v.expr)) & self.skip):
                theirs = next(
                    (x for x in self.back.survey["variables"] if x["id"] == self.ids[v.id]), None
                )
                if theirs is None:
                    out.append(f"computed {v.id} missing")
        return out

    def _question(self, q: Any) -> list[str]:
        name = self.ids[q.id]
        t = self.theirs.get(name)
        if t is None:
            return [f"{q.id}: not read back"]
        out: list[str] = []
        want = "decimal" if q.type == "integer" else q.type
        if t["type"] != want:
            out.append(f"{q.id}: type {q.type} → {t['type']}")
        for lang in self.s.metadata.languages:
            ours = _flat(q.label, lang, self.base)
            if isinstance(q, NoteQuestion):
                ours = " ".join([ours, _flat(q.help, lang, self.base)]).strip()
            ours = self._pipes(ours)
            if _flat(t["label"], lang, self.base) != ours:
                out.append(
                    f"{q.id}: label [{lang}] {ours!r} → {_flat(t['label'], lang, self.base)!r}"
                )
            if not isinstance(q, NoteQuestion):
                if _flat(t.get("help"), lang, self.base) != self._pipes(
                    _flat(q.help, lang, self.base)
                ):
                    out.append(f"{q.id}: help [{lang}]")
        if isinstance(q, NoteQuestion):
            return out
        partly = isinstance(q, MatrixQuestion) and any(r.required is not None for r in q.rows)
        if not partly and bool(t.get("required")) != q.required:
            out.append(f"{q.id}: required {q.required} → {t.get('required')}")
        for key in ("multiline", "choiceOrder", "valueType"):
            ours_v = getattr(q, key, None)
            if ours_v is not None and t.get(key, type(q).model_fields[key].default) != ours_v:
                out.append(f"{q.id}: {key} {ours_v} → {t.get(key)}")
        for key in ("min", "max", "step"):
            ours_v = getattr(q, key, None)
            if ours_v is not None and Decimal(str(t.get(key))) != Decimal(str(ours_v)):
                out.append(f"{q.id}: {key} {ours_v} → {t.get(key)}")
        if isinstance(q, SingleQuestion | MultiQuestion | MatrixQuestion):
            got = [(c["value"], _flat(c["label"], self.base, self.base)) for c in t["choices"]]
            ours_c = [
                (c.value, self._pipes(_flat(c.label, self.base, self.base)))
                for c in _choices(self.s, q)
            ]
            if got != ours_c:
                out.append(f"{q.id}: choices {ours_c} → {got}")
        if isinstance(q, MatrixQuestion):
            got_rows = [(r["id"], _flat(r["label"], self.base, self.base)) for r in t["rows"]]
            if got_rows != [(r.id, _flat(r.label, self.base, self.base)) for r in q.rows]:
                out.append(f"{q.id}: rows")
        out += self._same_logic(q.id, "showIf", q.showIf, t.get("showIf"))
        if getattr(q, "constraint", None) is not None:
            out += self._same_logic(q.id, "constraint", q.constraint, t.get("constraint"), q.id)
        return out

    def _pipes(self, s: str) -> str:
        """Our pipes as they come back: by name; an assigned variable's dropped."""

        def back(m: re.Match[str]) -> str:
            if self.types.get(m[1]) == "assigned":
                return ""
            if m[1] in self.skip:  # an embedded variable: SurveyJS text the importer keeps
                return "{" + self.ids.get(m[1], m[1]) + "}"
            return "${" + self.ids.get(m[1], m[1]) + "}"

        return " ".join(re.sub(r"\$\{([^}$][^}]*)\}", back, s).split())

    def _same_logic(
        self, qid: str, what: str, ours: Expr | None, theirs: Any, answered: str | None = None
    ) -> list[str]:
        if ours is None:
            return [f"{qid}: {what} appeared"] if theirs is not None else []
        refs = set(references(ours))
        if refs & self.skip:
            return []  # accepted: the importer knows no such variable
        if theirs is None:
            return [f"{qid}: {what} lost"]
        their_expr = EXPR_ADAPTER.validate_python(theirs)
        lits = _literals(ours)
        rng = random.Random(f"{qid}/{what}")
        refs |= {answered} if answered else set()
        for _ in range(300):
            env = {
                r: rng.choice(_domain(self.types.get(r), self.values.get(r, []), lits))
                for r in sorted(refs)
            }
            if answered and env[answered] is None:
                continue  # a constraint is only checked on answered values
            mine = evaluate_condition(ours, env)
            got = evaluate_condition(their_expr, {self.ids[k]: v for k, v in env.items()})
            if mine != got:
                return [f"{qid}: {what} differs at {env}: {mine} → {got}"]
        return []


FIXTURE_DATA = [(p.parent.name, _fixture_survey(p)) for p in FIXTURES]


@pytest.mark.parametrize(("name", "data"), FIXTURE_DATA, ids=[f[0] for f in FIXTURE_DATA])
def test_round_trip_through_our_importer(name: str, data: Any) -> None:
    assert _RoundTrip(data).problems() == []


# --- Feature checks on small surveys -------------------------------------------------------


def _survey(items: list[dict], flow_extra: list[dict] | None = None, **top: Any) -> dict:
    return {
        "specVersion": "osp-survey/0.1",
        "id": "s1",
        "metadata": {"title": "T", "languages": ["en"]},
        "blocks": [{"id": "b1", "pages": [{"id": "p1", "items": items}]}],
        "flow": [{"type": "block", "id": "f1", "block": "b1"}, *(flow_extra or [])],
        **top,
    }


def _q(qid: str, qtype: str = "integer", **extra: Any) -> dict:
    return {"id": qid, "type": qtype, "label": f"Label {qid}", **extra}


def _export(data: Any) -> tuple[dict[str, Any], list[Any]]:
    result, diags = build_surveyjs(data)
    assert result is not None, diags
    assert json.loads(result.json) == result.document
    return result.document, diags


def _ref(qid: str) -> dict:
    return {"kind": "ref", "id": qid}


def _cmp(op: str, qid: str, value: Any) -> dict:
    kind = "text" if isinstance(value, str) else "int"
    return {"kind": "compare", "op": op, "left": _ref(qid), "right": {"kind": kind, "value": value}}


def test_types_required_bounds_and_constraint() -> None:
    data = _survey(
        [
            _q(
                "n",
                min=1,
                max=7,
                required=True,
                constraint=_cmp("!=", "n", 4),
                constraintMessage="Not 4",
            ),
            _q("d", "decimal", min="0.5"),
            _q("t", "text", multiline=True),
            _q("when", "date"),
            _q("note", "note", help="More."),
        ]
    )
    doc, diags = _export(data)
    n, d, t, when, note = _elements(doc)
    assert n == {
        "name": "n",
        "type": "text",
        "title": "Label n",
        "inputType": "number",
        "step": 1,
        "min": 1,
        "max": 7,
        "isRequired": True,
        "validators": [
            {"type": "regex", "regex": "^-?[0-9]+$"},
            {"type": "numeric", "minValue": 1, "maxValue": 7},
            {
                "type": "expression",
                "expression": "{n} empty or {n} notempty and {n} <> 4",
                "text": "Not 4",
            },
        ],
    }
    assert d["min"] == 0.5 and "step" not in d
    assert t["type"] == "comment"
    assert when["inputType"] == "date"
    assert note == {"name": "note", "type": "html", "html": "Label note<p>More.</p>"}
    features = {x.feature for x in diags}
    assert {
        "IntegerQuestion.type",
        "DecimalQuestion.type",
        "IntegerQuestion.constraint",
    } <= features


def test_choices_shuffle_and_shared_lists() -> None:
    data = _survey(
        [
            _q("one", "single", choiceList="yn", choiceOrder="shuffle"),
            _q(
                "many",
                "multi",
                choices=[{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
            ),
        ],
        choiceLists=[
            {"id": "yn", "choices": [{"value": 1, "label": "Yes"}, {"value": 0, "label": "No"}]}
        ],
    )
    doc, diags = _export(data)
    one, many = _elements(doc)
    assert one["type"] == "radiogroup" and one["choicesOrder"] == "random"
    assert one["choices"] == [{"value": 1, "text": "Yes"}, {"value": 0, "text": "No"}]
    assert many["type"] == "checkbox" and [c["value"] for c in many["choices"]] == ["a", "b"]
    assert ("SingleQuestion.choiceOrder=shuffle", "/blocks/0/pages/0/items/0/choiceOrder") in {
        (x.feature, x.pointer) for x in diags
    }


def test_comparisons_are_guarded_for_missing_values() -> None:
    gate = _q(
        "gate", "single", choices=[{"value": "y", "label": "Y"}, {"value": "n", "label": "N"}]
    )
    tags = _q("tags", "multi", choices=[{"value": "a", "label": "A"}])
    data = _survey(
        [
            gate,
            tags,
            _q("age"),
            _q("a", "text", showIf=_cmp("==", "gate", "y")),
            _q("b", "text", showIf=_cmp(">=", "age", 18)),
            _q(
                "c",
                "text",
                showIf={
                    "kind": "not",
                    "arg": {
                        "kind": "contains",
                        "ref": _ref("tags"),
                        "value": {"kind": "text", "value": "a"},
                    },
                },
            ),
            _q(
                "e",
                "text",
                showIf={
                    "kind": "or",
                    "args": [{"kind": "answered", "ref": _ref("age")}, _cmp("!=", "gate", "y")],
                },
            ),
        ]
    )
    doc, _ = _export(data)
    shown = {el["name"]: el.get("visibleIf") for el in _elements(doc)}
    assert shown["a"] == "{gate} = 'y'"
    assert shown["b"] == "{age} notempty and {age} >= 18"
    assert shown["c"] == "!({tags} contains 'a')"
    assert shown["e"] == "{age} notempty or {gate} notempty and {gate} <> 'y'"


def test_text_literals_are_quoted() -> None:
    data = _survey([_q("t", "text"), _q("u", "text", showIf=_cmp("==", "t", "it's \\ ok"))])
    doc, _ = _export(data)
    assert _elements(doc)[1]["visibleIf"] == "{t} = 'it\\'s \\\\ ok'"


def test_branches_and_end_nodes_become_page_conditions_and_completion_texts() -> None:
    gate = _q("gate", "single", choices=[{"value": 1, "label": "Y"}, {"value": 0, "label": "N"}])
    data = _survey([gate])
    data["blocks"].append({"id": "b2", "pages": [{"id": "p2", "items": [_q("x")]}]})
    data["flow"] += [
        {
            "type": "branch",
            "id": "br",
            "if": _cmp("==", "gate", 0),
            "then": [{"type": "end", "id": "e1", "outcome": "declined", "message": "Bye"}],
        },
        {"type": "block", "id": "f2", "block": "b2"},
    ]
    data["settings"] = {"endings": {"complete": {"title": "Thanks", "body": "You said ${gate}."}}}
    doc, diags = _export(data)
    assert [p.get("visibleIf") for p in doc["pages"]] == [None, "!({gate} = 0)"]
    assert doc["completedHtml"] == "<h3>Thanks</h3><p>You said {gate}.</p>"
    assert doc["completedHtmlOnCondition"] == [{"expression": "{gate} = 0", "html": "<p>Bye</p>"}]
    [outcome] = doc["calculatedValues"]
    assert outcome == {
        "name": "osp_outcome",
        "expression": "iif({gate} = 0, 'declined', 'complete')",
        "includeIntoResult": True,
    }
    assert "EndNode.type" in {d.feature for d in diags}


def test_end_redirects_become_urls_when_every_param_is_literal() -> None:
    data = _survey([_q("x")])
    data["settings"] = {
        "redirectTemplates": {
            "prolific": {
                "url": "https://app.prolific.com/submissions/complete?cc={cc}",
                "params": {"cc": {"pattern": "[A-Z0-9 &]{4,8}"}},
            },
        },
        "endings": {"complete": {"redirect": {"template": "prolific", "params": {"cc": "C1 &B2"}}}},
    }
    doc, diags = _export(data)
    assert doc["navigateToUrl"] == "https://app.prolific.com/submissions/complete?cc=C1%20%26B2"
    assert "Ending.redirect" in {d.feature for d in diags}
    data["settings"]["endings"]["complete"]["redirect"]["params"]["cc"] = "${x}"
    doc, diags = _export(data)
    assert "navigateToUrl" not in doc
    assert "$redirect.piped" in {d.feature for d in diags}


def test_assigned_variables_are_dropped_with_their_conditions() -> None:
    data = _survey([_q("q1"), _q("q2", "text", showIf=_cmp("==", "arm", "a"))])
    data["variables"] = [{"kind": "assigned", "id": "arm", "levels": ["a", "b"]}]
    data["flow"].insert(0, {"type": "assign", "id": "as", "variables": ["arm"]})
    doc, diags = _export(data)
    assert "visibleIf" not in _elements(doc)[1]
    found = {(d.feature, d.pointer) for d in diags}
    assert ("$expr.unmappable", "/blocks/0/pages/0/items/1/showIf") in found
    assert ("AssignedVariable.kind", "/variables/0") in found
    assert ("AssignNode.type", "/flow/0") in found


def test_computed_variables_are_calculated_values() -> None:
    expr = {"kind": "arith", "op": "*", "left": _ref("q1"), "right": {"kind": "int", "value": 2}}
    data = _survey([_q("q1"), _q("q2", "text", label="Double: ${dbl}")])
    data["variables"] = [{"kind": "computed", "id": "dbl", "expr": expr}]
    doc, _ = _export(data)
    assert doc["calculatedValues"] == [
        {"name": "dbl", "expression": "{q1} * 2", "includeIntoResult": True}
    ]
    assert _elements(doc)[1]["title"] == "Double: {dbl}"


def test_languages_are_localisable_strings() -> None:
    data = _survey([_q("q1", label={"en": "Age?", "de": "Alter?"}), _q("q2", label={"en": "Only"})])
    data["metadata"] = {"title": "T", "languages": ["de", "en"], "defaultLanguage": "de"}
    data["settings"] = {"backNavigation": False}
    doc, _ = _export(data)
    assert doc["locale"] == "de"
    assert doc["showPrevButton"] is False
    q1, q2 = _elements(doc)
    assert q1["title"] == {"default": "Alter?", "en": "Age?"}
    assert q2["title"] == {"default": "Only", "en": "Only"} or q2["title"] == "Only"


def test_rich_text_is_html_in_notes_and_plain_in_titles() -> None:
    rich = {
        "type": "rich",
        "blocks": [
            {
                "type": "p",
                "content": [
                    {"text": "Very ", "marks": ["b"]},
                    {"text": "good", "href": "https://example.org"},
                ],
            }
        ],
    }
    data = _survey([_q("n", "note", label=rich), _q("q", "text", label=rich)])
    doc, diags = _export(data)
    note, q = _elements(doc)
    assert note["html"] == (
        '<strong>Very </strong><a href="https://example.org" target="_blank" '
        'rel="noopener noreferrer">good</a>'
    )
    assert q["title"] == "Very good"
    found = {(d.feature, d.pointer) for d in diags}
    assert ("$rich.bold", "/blocks/0/pages/0/items/1/label") in found
    assert ("$rich.link", "/blocks/0/pages/0/items/1/label") in found
    assert not any(p == "/blocks/0/pages/0/items/0/label" for _f, p in found)


def test_matrix_rows_and_partial_requirement() -> None:
    m = _q(
        "m",
        "matrix",
        name="grid",
        choices=[{"value": 1, "label": "Bad"}, {"value": 2, "label": "Good"}],
        rows=[{"id": "r1", "label": "Tea", "required": True}, {"id": "r2", "label": "Coffee"}],
    )
    data = _survey([m, _q("x", "text", showIf=_cmp("==", "m_r1", 2))])
    doc, diags = _export(data)
    grid, x = _elements(doc)
    assert grid["rows"] == [{"value": "r1", "text": "Tea"}, {"value": "r2", "text": "Coffee"}]
    assert grid["columns"] == [{"value": 1, "text": "Bad"}, {"value": 2, "text": "Good"}]
    assert grid["validators"] == [{"type": "expression", "expression": "{grid.r1} notempty"}]
    assert "isAllRowRequired" not in grid
    assert x["visibleIf"] == "{grid.r1} = 2"
    assert "$matrix.someRowsRequired" in {d.feature for d in diags}


def test_slider_and_randomiser() -> None:
    data = _survey([_q("s", "slider", min=0, max=10, step=2)])
    data["blocks"].append({"id": "b2", "pages": [{"id": "p2", "items": [_q("x")]}]})
    data["flow"] = [
        {
            "type": "randomiser",
            "id": "r",
            "pick": 1,
            "children": [
                {"type": "block", "id": "f1", "block": "b1"},
                {"type": "block", "id": "f2", "block": "b2"},
            ],
        }
    ]
    doc, diags = _export(data)
    assert [p["name"] for p in doc["pages"]] == ["p1", "p2"]
    s = _elements(doc)[0]
    assert (s["type"], s["min"], s["max"], s["step"]) == ("slider", 0, 10, 2)
    features = {d.feature for d in diags}
    assert {"RandomiserNode.type", "RandomiserNode.pick", "SliderQuestion.type"} <= features
