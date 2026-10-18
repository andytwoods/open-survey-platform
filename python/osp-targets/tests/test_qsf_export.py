"""Qualtrics .qsf export: every survey exports to well-formed, deterministic JSON; every
non-native feature used is reported with a JSON pointer that resolves in the survey;
display logic says what our conditions say (checked by evaluating both); golden files for
five fixtures; round trips through our own importer; feature checks on small surveys.

Regenerate the goldens with ``OSP_UPDATE_GOLDEN=1``.

Round trip (export → ``imports.qsf`` → compare): every question comes back with its id
(the export tag), type, required flag, choice values (the recodes), grid rows and, for a
plain label, its text; display logic comes back meaning the same as the original
condition. Accepted differences, each reported by the exporter or by design:

- generated questions come back as notes (page titles, end messages, the consent text) or
  questions (the consent answer): they are the export's ``helpers``;
- a label with help text comes back with the help as part of the label (``*.help``);
- text choice values come back as their numeric recodes (``$choice.code``);
- an else arm comes back as a second branch, an assignment randomizer and an embedded
  variable's default are not read back (the importer reads embedded data only as a
  declaration), slider end labels are not read back;
- page and flow ids are the importer's own.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
import random
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from osp_expr.ast import EXPR_ADAPTER, And, Expr
from osp_expr.evaluate import evaluate_condition
from osp_expr.static import references
from osp_spec import Survey, parse
from osp_spec.model import (
    AssignedVariable,
    DateQuestion,
    DecimalQuestion,
    EmbeddedVariable,
    IntegerQuestion,
    MatrixQuestion,
    MultiQuestion,
    NoteQuestion,
    SingleQuestion,
    SliderQuestion,
    TextQuestion,
    matrix_row_id,
)
from osp_targets.imports import import_qsf
from osp_targets.qsf import QSF, RESERVED_NAMES, build_qsf, export_qsf, feature_uses, sanitise_name

REPO = Path(__file__).resolve().parents[3]
CASES = sorted((REPO / "python/osp-spec/tests/cases/valid").glob("*.json"))
FIXTURES = sorted((REPO / "fixtures").glob("*/survey.json"))
GOLDEN = Path(__file__).parent / "data/qsf"
GOLDEN_FIXTURES = ["13-randomiser-blocks", "17-piping", "20-worked-example", "38-matrix",
                   "41-rich-text"]  # fmt: skip


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


def _elements(doc: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [e for e in doc["SurveyElements"] if e["Element"] == kind]


def _questions_by_tag(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {e["Payload"]["DataExportTag"]: e["Payload"] for e in _elements(doc, "SQ")}


def _model(data: Any) -> Survey:
    survey, _ = parse(data)
    assert survey is not None
    return survey


def _items(s: Survey) -> list[tuple[str, Any, Any]]:
    """(pointer, page, question) for every question."""
    return [
        (f"/blocks/{bi}/pages/{pi}/items/{qi}", page, q)
        for bi, b in enumerate(s.blocks)
        for pi, page in enumerate(b.pages)
        for qi, q in enumerate(page.items)
    ]


def test_there_are_surveys() -> None:
    assert len(CASES) >= 10
    assert len(FIXTURES) >= 30


@pytest.mark.parametrize(("label", "data"), SURVEYS, ids=[s[0] for s in SURVEYS])
def test_export_is_well_formed(label: str, data: Any) -> None:
    result, diags = build_qsf(data)
    assert result is not None, diags
    assert not [d for d in diags if d.severity == "error"], diags
    doc = json.loads(result.qsf.decode("utf-8"))
    survey = _model(data)
    assert doc["SurveyEntry"]["SurveyName"] == survey.metadata.title
    assert re.fullmatch(r"SV_[0-9A-Za-z]{15}", doc["SurveyEntry"]["SurveyID"])
    assert [e["Element"] for e in doc["SurveyElements"][:5]] == ["BL", "FL", "SO", "QC", "RS"]

    # Questions: unique QIDs and export tags (ignoring case), valid, never a response column.
    sq = [e["Payload"] for e in _elements(doc, "SQ")]
    assert [q["QuestionID"] for q in sq] == [f"QID{i + 1}" for i in range(len(sq))]
    tags = [q["DataExportTag"] for q in sq]
    assert len({t.lower() for t in tags}) == len(tags)
    for t in tags:
        assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", t) and t.lower() not in RESERVED_NAMES, t
    assert _elements(doc, "QC")[0]["SecondaryAttribute"] == str(len(sq))
    for q in sq:
        if survey.metadata.languages[1:]:
            codes = {lang.upper() for lang in survey.metadata.languages}
            assert set(q["Language"]) <= codes
        for key, order in (("Choices", "ChoiceOrder"), ("Answers", "AnswerOrder")):
            if key in q:
                assert q[order] == list(q[key]) and all(c.isdigit() for c in q[key])

    # Blocks: every question in exactly one block; the flow names only blocks that exist.
    blocks = _elements(doc, "BL")[0]["Payload"]
    in_blocks = [
        el["QuestionID"] for b in blocks for el in b["BlockElements"] if el["Type"] == "Question"
    ]
    assert sorted(in_blocks) == sorted(q["QuestionID"] for q in sq)
    ids = {b["ID"] for b in blocks}
    flow = _elements(doc, "FL")[0]["Payload"]
    flow_ids: list[str] = []

    def walk(nodes: list[dict[str, Any]]) -> None:
        for n in nodes:
            flow_ids.append(n["FlowID"])
            if n["Type"] in ("Block", "Standard"):
                assert n["ID"] in ids
            walk(n.get("Flow", []))

    walk(flow["Flow"])
    assert len(set(flow_ids)) == len(flow_ids)
    assert flow["Properties"]["Count"] == 1 + len(flow_ids)

    # Diagnostics: level from the table, pointer resolves in the survey document.
    raw = json.loads(json.dumps(data))
    for d in diags:
        assert d.target == "qsf"
        assert d.feature in QSF, d
        cap = QSF[d.feature]
        assert d.level == cap.level != "native"
        assert d.code == f"qsf.{cap.level}"
        assert d.severity == {"lowered": "info", "approximated": "warning",
                              "unsupported": "loss"}[cap.level]  # fmt: skip
        _resolve(raw, d.pointer)

    # Every non-native field the survey uses has a diagnostic at its pointer.
    reported = {(d.feature, d.pointer) for d in diags}
    for key, ptr, _value in feature_uses(survey):
        if QSF[key].level != "native":
            assert (key, ptr) in reported, (key, ptr)


@pytest.mark.parametrize(("label", "data"), SURVEYS, ids=[s[0] for s in SURVEYS])
def test_deterministic_bytes(label: str, data: Any) -> None:
    a, da = export_qsf(data)
    b, db = export_qsf(copy.deepcopy(data))
    assert a == b
    assert da == db


def test_accepts_survey_model() -> None:
    data = json.loads(CASES[0].read_text(encoding="utf-8"))["survey"]
    assert export_qsf(_model(data)) == export_qsf(data)


@pytest.mark.parametrize("name", GOLDEN_FIXTURES)
def test_golden(name: str) -> None:
    qsf, diags = export_qsf(_fixture_survey(REPO / "fixtures" / name / "survey.json"))
    got_diags = "".join(f"{d.severity}\t{d.feature}\t{d.pointer}\n" for d in diags)
    path_qsf = GOLDEN / f"{name}.qsf"
    path_diags = GOLDEN / f"{name}.diagnostics.tsv"
    if os.environ.get("OSP_UPDATE_GOLDEN") == "1":
        GOLDEN.mkdir(parents=True, exist_ok=True)
        path_qsf.write_bytes(qsf)
        path_diags.write_text(got_diags, encoding="utf-8", newline="\n")
    assert qsf == path_qsf.read_bytes(), f"{name}: regenerate with OSP_UPDATE_GOLDEN=1"
    assert got_diags == path_diags.read_text(encoding="utf-8")


def test_never_raises_on_bad_input() -> None:
    for bad in (None, 5, "x", [], {}, {"specVersion": "osp-survey/0.1"}):
        qsf, diags = export_qsf(bad)  # type: ignore[arg-type]
        assert qsf == b""
        assert diags and all(d.severity == "error" for d in diags)
        assert diags[0].code.startswith("qsf.error.")


# --- Logic: what Qualtrics would decide, against our evaluator ----------------------------

_TEXTS = ("a", "b", "yes", "no", "red", "Ü")
_INTS = (-1, 0, 1, 2, 3, 4, 5, 6, 10, 17, 18, 30, 65)


def _literals(s: Survey) -> tuple[set[str], set[int]]:
    """Text and whole-number literals the survey's conditions use, so random answers hit
    the interesting values."""
    texts: set[str] = set()
    ints: set[int] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("kind") == "text":
                texts.add(str(node.get("value")))
            if node.get("kind") == "int" and isinstance(node.get("value"), int):
                ints.update({node["value"] - 1, node["value"], node["value"] + 1})
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(s.model_dump(mode="json", by_alias=True))
    return texts, ints


def _choices(s: Survey, q: Any) -> list[Any]:
    if q.choiceList is not None:
        return [c.value for c in next(cl for cl in s.choiceLists if cl.id == q.choiceList).choices]
    return [c.value for c in q.choices or []]


def _random_env(s: Survey, rng: random.Random) -> dict[str, Any]:
    """Random answers (or none) for every question and variable, as our evaluator reads
    them: ints, Decimals, text, frozensets of codes, dates, or None."""
    texts, ints = _literals(s)
    text_pool = sorted(set(_TEXTS) | texts)
    int_pool = sorted(set(_INTS) | ints)
    env: dict[str, Any] = {}

    def maybe(v: Any) -> Any:
        return None if rng.random() < 0.25 else v

    for _p, _page, q in _items(s):
        match q:
            case IntegerQuestion() | SliderQuestion():
                env[q.id] = maybe(rng.choice(int_pool))
            case DecimalQuestion():
                env[q.id] = maybe(Decimal(rng.choice(int_pool)) + Decimal(rng.choice((0, 0.5))))
            case TextQuestion():
                env[q.id] = maybe(rng.choice(text_pool))
            case DateQuestion():
                env[q.id] = maybe(dt.date(2020, 1, 1) + dt.timedelta(days=rng.randrange(900)))
            case SingleQuestion():
                env[q.id] = maybe(rng.choice(_choices(s, q)))
            case MultiQuestion():
                pick = frozenset(v for v in _choices(s, q) if rng.random() < 0.4)
                env[q.id] = maybe(pick) if pick else None
            case MatrixQuestion():
                for row in q.rows:
                    env[matrix_row_id(q.id, row.id)] = maybe(rng.choice(_choices(s, q)))
    for v in s.variables:
        if isinstance(v, EmbeddedVariable):
            pool = text_pool if v.valueType == "text" else [str(i) for i in int_pool]
            value = maybe(rng.choice(pool))
            env[v.id] = Decimal(value) if value is not None and v.valueType != "text" else value
        elif isinstance(v, AssignedVariable):
            env[v.id] = rng.choice(v.levels)
    return env


def _qualtrics_env(
    s: Survey, doc: dict[str, Any], tags: dict[str, str], env: dict[str, Any]
) -> dict[str, Any]:
    """The same answers as Qualtrics holds them: a choice id (or a set of them, or a
    statement → choice id map) per QID, the entry text per QID, the value per field."""
    by_tag = _questions_by_tag(doc)
    out: dict[str, Any] = {}

    def cid_of(payload: dict[str, Any], value: Any, codes: dict[str, str]) -> str:
        recode = codes.get(str(value), str(value))
        return next(c for c, r in payload["RecodeValues"].items() if r == recode)

    for _p, _page, q in _items(s):
        payload = by_tag[tags[q.id]]
        qid = payload["QuestionID"]
        codes = {}
        if isinstance(q, (SingleQuestion, MultiQuestion, MatrixQuestion)):
            codes = {str(c): str(r) for c, r in _recodes(payload, s, q).items()}
        match q:
            case SingleQuestion():
                v = env[q.id]
                out[qid] = None if v is None else cid_of(payload, v, codes)
            case MultiQuestion():
                v = env[q.id]
                out[qid] = None if v is None else {cid_of(payload, x, codes) for x in v}
            case MatrixQuestion():
                cells = {}
                for k, row in enumerate(q.rows):
                    v = env[matrix_row_id(q.id, row.id)]
                    if v is not None:
                        cells[str(k + 1)] = cid_of(payload, v, codes)
                out[qid] = cells
            case DateQuestion():
                v = env[q.id]
                out[qid] = None if v is None else v.strftime("%Y/%m/%d")
            case NoteQuestion():
                pass
            case _:
                v = env[q.id]
                out[qid] = None if v is None else str(v)
    for v in s.variables:
        if isinstance(v, (EmbeddedVariable, AssignedVariable)) and v.id in env:
            field = v.param if isinstance(v, EmbeddedVariable) else tags[v.id]
            out["e:" + field] = None if env[v.id] is None else str(env[v.id])
    return out


def _recodes(payload: dict[str, Any], s: Survey, q: Any) -> dict[Any, int]:
    """Our choice value → its recode, read back from the payload (choices in order)."""
    key = "Answers" if isinstance(q, MatrixQuestion) else "Choices"
    order = payload["AnswerOrder" if key == "Answers" else "ChoiceOrder"]
    return {
        v: int(payload["RecodeValues"][cid]) for v, cid in zip(_choices(s, q), order, strict=True)
    }


def _number(text: str) -> Decimal | None:
    return Decimal(text) if re.fullmatch(r"-?\d+(\.\d+)?", text) else None


def _qualtrics_truth(logic: dict[str, Any], qenv: dict[str, Any], empty_is: bool) -> bool:
    """Evaluate a Qualtrics logic object as Qualtrics would. How an operator treats an
    unanswered entry is undocumented: ``empty_is`` is that result, and the exporter's
    guards must make it irrelevant."""

    def cond(c: dict[str, Any]) -> bool:
        op = c["Operator"]
        if c["LogicType"] == "EmbeddedField":
            value = qenv.get("e:" + c["LeftOperand"])
        else:
            parts = c["ChoiceLocator"].split("/")
            qid, part = parts[2], parts[3]
            if part == "SelectableChoice":
                answer = qenv.get(qid)
                if len(parts) == 6:  # a grid cell
                    selected = (answer or {}).get(parts[4]) == parts[5]
                elif isinstance(answer, set):
                    selected = parts[4] in answer
                else:
                    selected = answer == parts[4]
                return selected if op == "Selected" else not selected
            value = qenv.get(qid)
        if op == "Empty":
            return value is None
        if op == "NotEmpty":
            return value is not None
        if value is None:
            return empty_is
        right = str(c.get("RightOperand", ""))
        a, b = _number(value), _number(right)
        if a is not None and b is not None:
            x: Any = (a, b)
        elif op in ("EqualTo", "NotEqualTo"):
            x = (value, right)
        else:
            return empty_is  # Qualtrics would not compare text by order: never written
        return {
            "EqualTo": x[0] == x[1],
            "NotEqualTo": x[0] != x[1],
            "LessThan": x[0] < x[1],
            "LessThanOrEqual": x[0] <= x[1],
            "GreaterThan": x[0] > x[1],
            "GreaterThanOrEqual": x[0] >= x[1],
        }[op]

    sets = [v for k, v in sorted(logic.items(), key=lambda kv: kv[0]) if k.isdigit()]
    return any(all(cond(c) for k, c in sorted(s.items()) if k.isdigit()) for s in sets)


def _condition_of(page: Any, q: Any) -> Expr | None:
    parts = [c for c in (page.showIf, q.showIf) if c is not None]
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else And(args=tuple(parts))


@pytest.mark.parametrize(("label", "data"), SURVEYS, ids=[s[0] for s in SURVEYS])
def test_display_logic_means_what_the_condition_means(label: str, data: Any) -> None:
    result, diags = build_qsf(data)
    assert result is not None
    s = _model(data)
    doc = json.loads(result.qsf)
    by_tag = _questions_by_tag(doc)
    unmappable = {d.pointer for d in diags if d.feature == "$logic.unmappable"}
    tags = {q.id: result.name_map[getattr(q, "name", None) or q.id] for _p, _page, q in _items(s)}
    for v in s.variables:
        if isinstance(v, AssignedVariable):
            tags[v.id] = result.name_map[v.name or v.id]
    rng = random.Random(label)
    envs = [_random_env(s, rng) for _ in range(150)]
    checked = 0
    for ptr, page, q in _items(s):
        page_ptr = ptr.rsplit("/items/", 1)[0]
        if f"{page_ptr}/showIf" in unmappable or f"{ptr}/showIf" in unmappable:
            continue
        cond = _condition_of(page, q)
        logic = by_tag[tags[q.id]].get("DisplayLogic")
        assert (logic is None) == (cond is None), ptr
        if cond is None:
            continue
        checked += 1
        for env in envs:
            qenv = _qualtrics_env(s, doc, tags, env)
            want = evaluate_condition(cond, env)
            for empty_is in (False, True):
                assert _qualtrics_truth(logic, qenv, empty_is) == want, (ptr, env)
    if label in ("fixture/05-showif-null", "fixture/19-expressions"):
        assert checked >= 3


# --- Round trip through our importer ------------------------------------------------------


def _plain_label(text: Any) -> str | None:
    """A label the round trip can compare: plain text in one language, no pipes."""
    if isinstance(text, str) and "${" not in text:
        return " ".join(text.split())
    return None


@pytest.mark.parametrize(("label", "data"), SURVEYS, ids=[s[0] for s in SURVEYS])
def test_round_trip_through_the_importer(label: str, data: Any) -> None:
    result, diags = build_qsf(data)
    assert result is not None
    s = _model(data)
    imported = import_qsf(result.qsf)
    assert imported.survey is not None, imported.diagnostics
    assert not [d for d in imported.validation if d.severity == "error"]
    # The importer only drops what the export reported (or what it cannot read back).
    dropped = [d for d in imported.diagnostics if d.severity in ("loss", "error")]
    assert not [d for d in dropped if d.code == "qsf.condition_dropped"], dropped
    assert not [d for d in dropped if d.feature != "SurveyTermination"], dropped
    if any(d.feature == "SurveyTermination" for d in dropped):
        assert any(d.feature == "Ending.redirect" for d in diags)

    got = {
        q["id"]: (q, page)
        for b in imported.survey["blocks"]
        for page in b["pages"]
        for q in page["items"]
    }
    tags: dict[str, str] = {}
    for _ptr, _page, q in _items(s):
        tag = result.name_map[getattr(q, "name", None) or q.id]
        tags[q.id] = tag
        assert tag in got, f"{q.id} ({tag}) did not come back"
        back, _bpage = got[tag]
        assert back["type"] == q.type, q.id
        if isinstance(q, MatrixQuestion):
            assert [r["id"] for r in back["rows"]] == [r.id for r in q.rows]
            assert back.get("required", False) == all(
                q.required if r.required is None else r.required for r in q.rows
            )
        elif not isinstance(q, NoteQuestion):
            assert back.get("required", False) == q.required, q.id
        if isinstance(q, (SingleQuestion, MultiQuestion, MatrixQuestion)):
            codes = result.choice_codes.get(getattr(q, "name", None) or q.id, {})
            want = [int(codes.get(str(v), v)) for v in _choices(s, q)]
            assert [c["value"] for c in back["choices"]] == want, q.id
        if isinstance(q, SliderQuestion):
            for key in ("min", "max"):
                assert Decimal(str(back[key])) == Decimal(str(getattr(q, key))), q.id
        plain = _plain_label(q.label)
        if plain is not None and q.help is None and len(s.metadata.languages) == 1:
            assert " ".join(str(back["label"]).split()) == plain, q.id
    # Generated questions are the export's helpers; nothing else comes back.
    extra = set(got) - set(tags.values())
    assert extra <= set(result.helpers), extra
    # Embedded variables come back under their URL parameter.
    params = {v["param"] for v in imported.survey["variables"] if v["kind"] == "embedded"}
    for v in s.variables:
        if isinstance(v, EmbeddedVariable):
            assert v.param in params

    # Display logic comes back meaning the same.
    unmappable = {d.pointer for d in diags if d.feature == "$logic.unmappable"}
    rng = random.Random("rt" + label)
    envs = [_random_env(s, rng) for _ in range(100)]
    for v in s.variables:
        if isinstance(v, EmbeddedVariable):
            tags[v.id] = next(
                iv["id"] for iv in imported.survey["variables"] if iv.get("param") == v.param
            )
        elif isinstance(v, AssignedVariable):
            tags[v.id] = result.name_map[v.name or v.id]
    for ptr, page, q in _items(s):
        page_ptr = ptr.rsplit("/items/", 1)[0]
        if f"{page_ptr}/showIf" in unmappable or f"{ptr}/showIf" in unmappable:
            continue
        cond = _condition_of(page, q)
        back_cond = got[tags[q.id]][0].get("showIf")
        assert (back_cond is None) == (cond is None), ptr
        if cond is None:
            continue
        back_expr = EXPR_ADAPTER.validate_python(back_cond)
        for env in envs:
            back_env = _imported_env(s, result, tags, env, references(back_expr))
            assert evaluate_condition(back_expr, back_env) == evaluate_condition(cond, env), (
                ptr,
                env,
            )


def _imported_env(
    s: Survey, result: Any, tags: dict[str, str], env: dict[str, Any], refs: tuple[str, ...]
) -> dict[str, Any]:
    """Our answers as the imported survey holds them: renamed ids, recoded choices."""
    out: dict[str, Any] = {}
    for _p, _page, q in _items(s):
        codes: dict[str, str] = {}
        if isinstance(q, (SingleQuestion, MultiQuestion, MatrixQuestion)):
            codes = result.choice_codes.get(getattr(q, "name", None) or q.id, {})

        def code(v: Any, codes: dict[str, str] = codes) -> Any:
            return int(codes.get(str(v), v))

        match q:
            case SingleQuestion():
                out[tags[q.id]] = None if env[q.id] is None else code(env[q.id])
            case MultiQuestion():
                v = env[q.id]
                out[tags[q.id]] = None if v is None else frozenset(code(x) for x in v)
            case MatrixQuestion():
                for row in q.rows:
                    v = env[matrix_row_id(q.id, row.id)]
                    out[f"{tags[q.id]}_{row.id}"] = None if v is None else code(v)
            case NoteQuestion():
                pass
            case _:
                out[tags[q.id]] = env[q.id]
    for v in s.variables:
        if isinstance(v, EmbeddedVariable):
            value = env[v.id]
            out[tags[v.id]] = (
                None
                if value is None
                else (str(value) if v.valueType == "text" else Decimal(str(value)))
            )
        elif isinstance(v, AssignedVariable):
            out[tags[v.id]] = str(env[v.id])
    return {k: out.get(k) for k in refs} | out


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


def _export(data: Any) -> tuple[Any, list[Any], dict[str, Any]]:
    result, diags = build_qsf(data)
    assert result is not None, diags
    return result, diags, json.loads(result.qsf)


def _flow(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return _elements(doc, "FL")[0]["Payload"]["Flow"]


def test_types_selectors_and_validation() -> None:
    data = _survey(
        [
            _q("n", min=1, max=9, required=True),
            _q("d", "decimal", min="0.5"),
            _q("t", "text"),
            _q("tm", "text", multiline=True),
            _q("dt", "date"),
            _q("nt", "note"),
            _q("sl", "slider", min=0, max=10, step=1, minLabel="Low", maxLabel="High"),
        ]
    )
    _result, diags, doc = _export(data)
    q = _questions_by_tag(doc)
    assert (q["n"]["QuestionType"], q["n"]["Selector"]) == ("TE", "SL")
    v = q["n"]["Validation"]["Settings"]
    assert v["ForceResponse"] == "ON"
    assert v["ContentType"] == "ValidNumber"
    assert v["ValidNumber"] == {"Min": "1", "Max": "9", "NumDecimals": "0"}
    assert q["d"]["Validation"]["Settings"]["ValidNumber"]["NumDecimals"] == ""
    assert q["tm"]["Selector"] == "ML"
    assert q["dt"]["Validation"]["Settings"]["ContentType"] == "ValidDate"
    assert (q["nt"]["QuestionType"], q["nt"]["Selector"]) == ("DB", "TB")
    assert q["sl"]["QuestionType"] == "Slider"
    assert q["sl"]["Configuration"]["CSSliderMax"] == 10
    assert q["sl"]["Labels"] == {"1": {"Display": "Low"}, "2": {"Display": "High"}}
    assert {d.feature for d in diags} >= {"DateQuestion.type", "$missingStates"}


def test_reserved_names_are_renamed_and_reported() -> None:
    """Our identifiers are valid export tags; a Qualtrics response column is renamed."""
    data = _survey([_q("Status"), _q("q2", name="finished"), _q("ok"), _q("Status_2")])
    result, diags, doc = _export(data)
    assert result.renamed == {"Status": "Status_3", "finished": "finished_2"}
    assert result.name_map["ok"] == "ok"
    assert result.name_map["Status_2"] == "Status_2"  # a valid name is never taken
    features = {(d.feature, d.pointer) for d in diags if d.feature.startswith("$names")}
    assert features == {
        ("$names.reserved", "/blocks/0/pages/0/items/0/id"),
        ("$names.reserved", "/blocks/0/pages/0/items/1/name"),
    }
    assert list(_questions_by_tag(doc)) == ["Status_3", "finished_2", "ok", "Status_2"]


def test_sanitise_name() -> None:
    assert sanitise_name("a-b c") == "a_b_c"
    assert sanitise_name("_x") == "q_x"
    assert sanitise_name("9") == "q9"
    assert len(sanitise_name("x" * 90)) == 64


def test_text_choice_values_get_numeric_recodes() -> None:
    choices = [{"value": 1, "label": "One"}, {"value": -1, "label": "Minus"},
               {"value": "x", "label": "X"}]  # fmt: skip
    data = _survey([_q("s", "single", choices=choices, choiceOrder="shuffle")])
    result, diags, doc = _export(data)
    s = _questions_by_tag(doc)["s"]
    # A positive recode is the choice id; -1 gets the next free id.
    assert s["RecodeValues"] == {"1": "1", "3": "-1", "2": "2"}
    assert s["ChoiceOrder"] == ["1", "3", "2"]
    assert s["Randomization"]["Type"] == "All"
    assert result.choice_codes == {"s": {"x": "2"}}
    assert {"$choice.code", "SingleQuestion.choiceOrder=shuffle"} <= {d.feature for d in diags}


def test_branch_with_else_is_two_branches() -> None:
    cond = {"kind": "compare", "op": ">", "left": {"kind": "ref", "id": "n"},
            "right": {"kind": "int", "value": 5}}  # fmt: skip
    data = _survey([_q("n")])
    data["blocks"] += [
        {"id": "b2", "pages": [{"id": "p2", "items": [_q("x", "note")]}]},
        {"id": "b3", "pages": [{"id": "p3", "items": [_q("y", "note")]}]},
    ]
    data["flow"].append(
        {
            "type": "branch",
            "id": "br",
            "if": cond,
            "then": [{"type": "block", "id": "f2", "block": "b2"}],
            "else": [{"type": "block", "id": "f3", "block": "b3"}],
        }
    )
    _result, diags, doc = _export(data)
    branches = [n for n in _flow(doc) if n["Type"] == "Branch"]
    assert len(branches) == 2
    yes, no = branches
    qenv = {"QID1": "7"}
    assert _qualtrics_truth(yes["BranchLogic"], qenv, False)
    assert not _qualtrics_truth(no["BranchLogic"], qenv, True)
    for empty_is in (False, True):
        assert not _qualtrics_truth(yes["BranchLogic"], {"QID1": None}, empty_is)
        assert _qualtrics_truth(no["BranchLogic"], {"QID1": None}, empty_is)
    assert ("BranchNode.else", "/flow/1/else") in {(d.feature, d.pointer) for d in diags}


def test_unmappable_condition_is_reported_and_dropped() -> None:
    cond = {"kind": "compare", "op": "==", "left": {"kind": "ref", "id": "a"},
            "right": {"kind": "ref", "id": "b"}}  # fmt: skip
    data = _survey([_q("a"), _q("b"), _q("c", showIf=cond)])
    _result, diags, doc = _export(data)
    assert "DisplayLogic" not in _questions_by_tag(doc)["c"]
    unmappable = [d for d in diags if d.feature == "$logic.unmappable"]
    assert [d.pointer for d in unmappable] == ["/blocks/0/pages/0/items/2/showIf"]
    assert unmappable[0].severity == "loss"


def test_end_nodes_outcomes_and_redirect() -> None:
    data = _survey(
        [_q("n")],
        flow_extra=[{"type": "end", "id": "e1", "outcome": "screened_out", "message": "Bye"}],
        settings={
            "endings": {
                "screened_out": {
                    "title": "Thanks",
                    "redirect": {"template": "panel", "params": {"code": "XYZ"}},
                }
            },
            "redirectTemplates": {
                "panel": {"url": "https://example.org/return?c={code}", "params": {"code": {}}}
            },
        },
    )
    _result, diags, doc = _export(data)
    flow = _flow(doc)
    assert [n["Type"] for n in flow] == ["Block", "Standard", "EndSurvey"]
    end = flow[-1]["Options"]
    assert end["ResponseFlag"] == "Screened"
    assert end["SurveyTermination"] == "Redirect"
    assert end["EOSRedirectURL"] == "https://example.org/return?c=XYZ"
    message = _questions_by_tag(doc)["ospend_e1"]
    assert message["QuestionText"] == "<p>Bye</p><p>Thanks</p>"
    assert {"EndNode.message", "Settings.endings", "EndRedirect.delay"} <= {
        d.feature for d in diags
    }


def test_embedded_and_assigned_variables() -> None:
    data = _survey(
        [
            _q(
                "n",
                showIf={
                    "kind": "compare",
                    "op": "==",
                    "left": {"kind": "ref", "id": "grp"},
                    "right": {"kind": "text", "value": "b"},
                },
            )
        ],  # fmt: skip
        variables=[
            {"kind": "embedded", "id": "pid", "param": "PROLIFIC_PID", "default": "none"},
            {"kind": "assigned", "id": "grp", "levels": ["a", "b"]},
        ],
    )
    data["flow"].insert(0, {"type": "assign", "id": "as", "variables": ["grp"]})
    result, diags, doc = _export(data)
    flow = _flow(doc)
    assert flow[0]["Type"] == "EmbeddedData"
    assert flow[0]["EmbeddedData"][0]["Field"] == "PROLIFIC_PID"
    assert flow[1]["Type"] == "Branch"  # the default, when the URL left the field empty
    assert flow[1]["Flow"][0]["EmbeddedData"][0]["Value"] == "none"
    rnd = flow[2]
    assert rnd["Type"] == "BlockRandomizer" and rnd["SubSet"] == 1
    assert [e["EmbeddedData"][0]["Value"] for e in rnd["Flow"]] == ["a", "b"]
    logic = _questions_by_tag(doc)["n"]["DisplayLogic"]
    assert logic["0"]["0"]["LogicType"] == "EmbeddedField"
    assert result.name_map["pid"] == "PROLIFIC_PID"
    assert "$embedded.param" in {d.feature for d in diags}


def test_piping_is_qualtrics_piped_text() -> None:
    data = _survey(
        [
            _q("s", "single", choices=[{"value": 1, "label": "Yes"}]),
            _q("n"),
            _q("x", "note", label="You said ${s} and ${n}; trial ${$trial} & <b>"),
        ]
    )
    _result, diags, doc = _export(data)
    text = _questions_by_tag(doc)["x"]["QuestionText"]
    assert text == (
        "You said ${q://QID1/ChoiceGroup/SelectedChoices} and "
        "${q://QID2/ChoiceTextEntryValue}; trial  &amp; &lt;b&gt;"
    )
    assert {"$pipe.builtin", "$text.markup"} <= {d.feature for d in diags}


def test_multi_language_texts_are_translations() -> None:
    data = _survey(
        [
            _q(
                "s",
                "single",
                label={"en": "Hello", "de": "Hallo"},
                choices=[{"value": 1, "label": {"en": "Yes", "de": "Ja"}}],
            ),
        ]  # fmt: skip
    )
    data["metadata"]["languages"] = ["en", "de"]
    _result, _diags, doc = _export(data)
    s = _questions_by_tag(doc)["s"]
    assert s["QuestionText"] == "Hello"
    assert s["Language"] == {"DE": {"QuestionText": "Hallo", "Choices": {"1": {"Display": "Ja"}}}}
    assert doc["SurveyEntry"]["SurveyLanguage"] == "EN"


def test_consent_is_a_first_block_and_a_branch() -> None:
    data = _survey([_q("n")], consent={"text": "Do you agree?"})
    result, diags, doc = _export(data)
    flow = _flow(doc)
    assert [n["Type"] for n in flow[:3]] == ["Block", "Branch", "Standard"]
    assert [n["Type"] for n in flow[1]["Flow"]] == ["EmbeddedData", "EndSurvey"]
    assert flow[1]["Flow"][0]["EmbeddedData"][0]["Value"] == "declined"
    consent = _questions_by_tag(doc)["ospconsent"]
    assert consent["Validation"]["Settings"]["ForceResponse"] == "ON"
    assert {"ospconsent", "ospconsent_text", "ospoutcome"} <= set(result.helpers)
    assert "Survey.consent" in {d.feature for d in diags}
