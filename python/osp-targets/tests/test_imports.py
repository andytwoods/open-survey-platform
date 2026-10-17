"""Importers (task IM1): the invented sample files import to the expected survey (golden
files), every result is a valid draft, every unsupported feature is a diagnostic, bad input
never raises, and every fixture survives an export to ``.lss`` and back.

Regenerate the goldens with ``OSP_UPDATE_GOLDEN=1``. The samples are invented: no real
surveys, no personal data.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from osp_spec import parse
from osp_targets.imports import (
    FORMATS,
    detect_format,
    import_lss,
    import_qsf,
    import_survey,
    import_surveyjs,
    result_to_json,
)
from osp_targets.imports.common import (
    Ids,
    choice_value,
    html_to_text,
    language_tag,
    sanitise_identifier,
    unique_values,
)
from osp_targets.imports.em_expr import EMNames, parse_em
from osp_targets.imports.sjs_expr import parse_expression
from osp_targets.lss import export_lss

REPO = Path(__file__).resolve().parents[3]
DATA = Path(__file__).parent / "data/imports"
FIXTURES = sorted((REPO / "fixtures").glob("*/survey.json"))
SAMPLES = {"qsf": "coffee.qsf", "lss": "coffee.lss", "surveyjs": "coffee-surveyjs.json"}


def _questions(s: dict[str, Any]) -> list[dict[str, Any]]:
    return [q for b in s["blocks"] for p in b["pages"] for q in p["items"]]


def _by_id(s: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {q["id"]: q for q in _questions(s)}


def _import(fmt: str) -> Any:
    return import_survey(SAMPLES[fmt], (DATA / SAMPLES[fmt]).read_bytes())


# -- goldens and validity ------------------------------------------------------------------


@pytest.mark.parametrize("fmt", sorted(SAMPLES))
def test_sample_matches_golden(fmt: str) -> None:
    result = _import(fmt)
    assert result.ok, [d.message for d in result.diagnostics if d.severity == "error"]
    actual = result_to_json(result)
    golden = DATA / f"{SAMPLES[fmt]}.expected.json"
    if os.environ.get("OSP_UPDATE_GOLDEN") == "1":
        golden.write_text(
            json.dumps(actual, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    assert golden.exists(), f"run with OSP_UPDATE_GOLDEN=1 to write {golden.name}"
    assert actual == json.loads(golden.read_text(encoding="utf-8"))


@pytest.mark.parametrize("fmt", sorted(SAMPLES))
def test_sample_is_a_valid_draft_with_a_summary(fmt: str) -> None:
    result = _import(fmt)
    assert result.format == fmt
    model, diags = parse(result.survey)
    assert model is not None
    assert [d for d in diags if d.severity == "error"] == []
    assert result.validation == diags
    assert result.summary is not None
    assert result.summary.questions == len(_questions(result.survey))
    assert result.summary.losses == sum(d.severity == "loss" for d in result.diagnostics)
    for d in result.diagnostics:
        assert d.code.startswith(fmt + ".")
        assert d.message
        if d.target:
            assert d.target.startswith("/")


# -- what carried over, per format ----------------------------------------------------------


def test_qsf_structure_logic_and_flow() -> None:
    s = _import("qsf").survey
    q = _by_id(s)
    assert [b["id"] for b in s["blocks"]] == ["Habits", "Sleep", "Mood_A", "Mood_B"]
    assert [len(b["pages"]) for b in s["blocks"]] == [2, 1, 1, 1]  # a Page Break splits
    assert q["drinks_coffee"]["type"] == "single" and q["drinks_coffee"]["required"] is True
    assert q["drinks_coffee"]["label"] == {
        "en": "Do you drink coffee?",
        "de": "Trinken Sie Kaffee?",
    }
    # TE ValidNumber with 0 decimals → integer with bounds; display logic → showIf.
    assert q["cups"]["type"] == "integer" and (q["cups"]["min"], q["cups"]["max"]) == (0, 30)
    assert q["cups"]["showIf"] == {
        "kind": "compare",
        "op": "==",
        "left": {"kind": "ref", "id": "drinks_coffee"},
        "right": {"kind": "int", "value": 1},
    }
    # Recoded, shuffled multi; piped text entry value → our piping.
    assert [c["value"] for c in q["kinds"]["choices"]] == [10, 20, 30, 99]
    assert q["kinds"]["choiceOrder"] == "shuffle"
    assert q["kinds"]["label"] == {"en": "Which kinds of coffee do you drink? (${cups} cups)"}
    assert q["agree"]["type"] == "matrix"
    assert [r["id"] for r in q["agree"]["rows"]] == ["focus", "awake"]
    assert q["energy"] == {
        "type": "slider",
        "id": "energy",
        "label": {"en": "How energetic do you feel right now?"},
        "valueType": "integer",
        "min": 0,
        "max": 10,
        "step": 1,
    }
    assert q["sleep_intro"]["type"] == "note"
    assert q["slept_well_on"]["type"] == "date"
    assert "rank" not in q and "old" not in q
    assert q["mood_pick"].get("required") is None  # RequestResponse is only a request
    assert s["blocks"][1]["pages"][0]["itemOrder"] == "shuffle"
    # Flow: embedded data up front, branch with And of a choice and an embedded field,
    # randomiser picking one of two, end.
    assert [v["id"] for v in s["variables"]] == ["source", "cohort"]
    assert s["variables"][1]["default"] == "2026"
    assert [n["type"] for n in s["flow"]] == ["block", "branch", "randomiser", "end"]
    branch = s["flow"][1]
    assert branch["if"]["kind"] == "and" and len(branch["if"]["args"]) == 2
    assert branch["then"][0]["block"] == "Sleep"
    assert s["flow"][2]["pick"] == 1 and len(s["flow"][2]["children"]) == 2
    codes = {d.code for d in _import("qsf").diagnostics}
    assert {
        "qsf.question_type",
        "qsf.text_entry_choice",
        "qsf.request_response",
        "qsf.trash",
    } <= codes


def test_lss_structure_logic_quotas_and_languages() -> None:
    result = _import("lss")
    s = result.survey
    q = _by_id(s)
    assert s["metadata"]["languages"] == ["en", "de"]
    assert s["metadata"]["title"]["de"].startswith("Kaffee")
    assert [b["id"] for b in s["blocks"]] == ["welcome", "Habits", "Sleep", "Mood_A", "Mood_B"]
    assert q["coffee"]["type"] == "single" and q["coffee"]["required"] is True
    assert [c["value"] for c in q["coffee"]["choices"]] == ["Y", "N"]
    assert q["coffee"]["help"] == {"en": "Any kind counts.", "de": "Jede Sorte zählt."}
    # N with int-only and bounds; em_validation_q → constraint with its tip.
    assert q["cups"]["type"] == "integer" and (q["cups"]["min"], q["cups"]["max"]) == (0, 30)
    assert q["cups"]["constraint"] == {
        "kind": "compare",
        "op": "!=",
        "left": {"kind": "ref", "id": "cups"},
        "right": {"kind": "int", "value": 13},
    }
    assert q["cups"]["constraintMessage"]["de"].startswith("Dreizehn")
    assert q["cups"]["showIf"] == {
        "kind": "compare",
        "op": "==",
        "left": {"kind": "ref", "id": "coffee"},
        "right": {"kind": "text", "value": "Y"},
    }
    # M → multi with shuffled subquestion codes; {cups} and {cups.shown} → ${cups}.
    assert [c["value"] for c in q["kinds"]["choices"]] == ["esp", "fil", "ins"]
    assert q["kinds"]["choiceOrder"] == "shuffle"
    assert q["kinds"]["label"]["de"] == "Welche Sorten trinken Sie? (${cups} Tassen)"
    assert q["kinds"]["showIf"]["kind"] == "and"
    # kinds_esp.NAOK == "Y" → contains.
    assert q["favourite"]["showIf"] == {
        "kind": "or",
        "args": [
            {
                "kind": "contains",
                "ref": {"kind": "ref", "id": "kinds"},
                "value": {"kind": "text", "value": "esp"},
            },
            {
                "kind": "contains",
                "ref": {"kind": "ref", "id": "kinds"},
                "value": {"kind": "text", "value": "fil"},
            },
        ],
    }
    assert q["agree"]["type"] == "matrix" and q["agree"]["required"] is True
    assert [c["value"] for c in q["agree"]["choices"]] == [1, 2, 3]
    assert q["moodscore"]["choices"][4]["value"] == 5  # type 5: fixed 1..5
    assert "rank" not in q and q["notes"].get("required") is None
    # Group relevance → page showIf; random_group → itemOrder; group description → note.
    sleep = s["blocks"][2]["pages"][0]
    assert sleep["showIf"]["kind"] == "compare" and sleep["itemOrder"] == "shuffle"
    assert s["blocks"][1]["pages"][0]["items"][0]["type"] == "note"
    # Hidden S with a default → embedded variable; equation → computed.
    assert s["variables"][0] == {
        "kind": "embedded",
        "id": "source",
        "param": "source",
        "default": "web",
    }
    assert s["variables"][1]["kind"] == "computed" and s["variables"][1]["id"] == "cupsweek"
    # Quota with a quota check after the block of its question; randomisation group.
    assert s["quotas"][0]["limit"] == 200 and s["quotas"][0]["when"]["left"]["id"] == "coffee"
    assert [n["type"] for n in s["flow"]] == [
        "block",
        "block",
        "quotaCheck",
        "block",
        "randomiser",
        "end",
    ]
    assert [c["block"] for c in s["flow"][4]["children"]] == ["Mood_A", "Mood_B"]
    assert s["flow"][-1]["message"]["de"].startswith("Vielen Dank")
    codes = {d.code for d in result.diagnostics}
    assert {"lss.other_option", "lss.question_type", "lss.soft_mandatory", "lss.attribute"} <= codes
    assert {"lss.hidden_field", "lss.randomization_group", "lss.quota", "lss.welcome_text"} <= codes


def test_surveyjs_structure_logic_and_values() -> None:
    result = _import("surveyjs")
    s = result.survey
    q = _by_id(s)
    assert s["metadata"]["languages"] == ["en", "de"]
    assert len(s["blocks"]) == 1 and [p["id"] for p in s["blocks"][0]["pages"]] == [
        "habits",
        "sleep",
        "about",
    ]
    assert q["drinks_coffee"]["required"] is True
    assert q["cups"]["type"] == "decimal" and (q["cups"]["min"], q["cups"]["max"]) == (0, 30)
    assert q["cups"]["showIf"]["right"] == {"kind": "text", "value": "yes"}
    assert [c["value"] for c in q["kinds"]["choices"]] == ["Espresso", "Filter", "Instant"]
    assert q["decaf"]["choices"][0]["value"] == "true"
    assert q["decaf"]["showIf"]["kind"] == "or"  # anyof
    assert q["sleep_quality"]["choices"][0]["label"] == {"en": "1 (Very badly)"}
    assert q["agree"]["type"] == "matrix" and q["agree"]["required"] is True
    assert q["notes"]["multiline"] is True
    assert q["notes"]["label"]["en"].endswith("drink ${cups} cups.")
    assert q["age"]["constraint"] is None if "constraint" in q["age"] else True
    assert (q["age"]["min"], q["age"]["max"]) == (16, 120)
    assert q["chronotype"]["showIf"]["op"] == ">="
    assert "rank" not in q
    sleep = s["blocks"][0]["pages"][1]
    assert sleep["showIf"] == {"kind": "answered", "ref": {"kind": "ref", "id": "drinks_coffee"}}
    assert sleep["itemOrder"] == "shuffle"
    assert {v["id"]: v["kind"] for v in s["variables"]} == {
        "adult": "computed",
        "cupsPerWeek": "computed",
    }
    assert s["flow"][-1]["message"] == {"en": "Thank you for taking part."}
    codes = {d.code for d in result.diagnostics}
    assert {
        "surveyjs.question_type",
        "surveyjs.question_property",
        "surveyjs.survey_property",
    } <= codes


# -- detection and bad input ---------------------------------------------------------------


def test_detect_format() -> None:
    assert detect_format("x.qsf", (DATA / "coffee.qsf").read_bytes()) == "qsf"
    assert detect_format("x.lss", (DATA / "coffee.lss").read_bytes()) == "lss"
    assert detect_format("x.json", (DATA / "coffee-surveyjs.json").read_bytes()) == "surveyjs"
    assert detect_format("renamed.txt", '{"SurveyEntry": {}, "SurveyElements": []}') == "qsf"
    assert detect_format("renamed.qsf", '{"pages": []}') == "qsf"
    assert detect_format("renamed.txt", '{"pages": []}') == "surveyjs"
    assert detect_format("renamed.txt", "<document/>") == "lss"
    assert detect_format("x.json", "") == "surveyjs"  # by extension; the importer says why
    assert detect_format("x.txt", "") is None
    assert detect_format(None, b"\x00\x01binary") is None
    assert import_survey("x.bin", b"\x00\x01").diagnostics[0].code == "import.unknown_format"


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"not json",
        b"[]",
        b"{}",
        b'{"SurveyEntry": 5, "SurveyElements": "no"}',
        b'{"SurveyElements": [{"Element": "SQ", "Payload": "null"}, 7, null]}',
        b'{"SurveyElements": [{"Element": "BL", "Payload": {"1": {"Type": "Default", "BlockElements": [{"Type": "Question", "QuestionID": "QID9"}]}}}, {"Element": "FL", "Payload": {"Flow": [{"Type": "Branch", "BranchLogic": {"0": {"0": {"LogicType": "Question", "ChoiceLocator": "q://QID9/SelectableChoice/1", "Operator": "Selected"}}}, "Flow": [{"Type": "Block", "ID": "nope"}]}, {"Type": "Weird"}]}}]}',  # noqa: E501
        b'{"SurveyElements": [{"Element": "SQ", "PrimaryAttribute": "QID1", "Payload": {"QuestionType": "MC", "Selector": "SAVR", "Choices": {"1": {"Display": "a"}, "2": {"Display": "a"}}, "RecodeValues": {"1": "x", "2": "x"}, "DataExportTag": "and", "Language": {"??": {"QuestionText": 1}}}}, {"Element": "BL", "Payload": [{"Type": "Standard", "ID": "b", "BlockElements": [{"Type": "Question", "QuestionID": "QID1"}, {"Type": "Question", "QuestionID": "QID1"}]}]}, {"Element": "FL", "Payload": {"Flow": [{"Type": "Block", "ID": "b"}, {"Type": "Block", "ID": "b"}]}}]}',  # noqa: E501
        "{" + '"pages": [' * 2000 + "]" * 2000 + "}",
        json.dumps(
            {
                "pages": [
                    {
                        "elements": [
                            {
                                "type": "text",
                                "name": "x" * 500,
                                "visibleIf": "{y} = 1 and (((",
                                "title": {"zz-ZZ-ZZ-ZZ": "t"},
                            },
                            {"type": "checkbox", "name": "x", "choices": [1, 1, {"value": None}]},
                        ]
                    }
                ]
            }
        ),
        json.dumps(
            {
                "pages": [
                    {
                        "elements": [
                            {"type": "text", "name": "a", "visibleIf": "{b} = 1"},
                            {"type": "text", "name": "b", "inputType": "number"},
                        ]
                    }
                ],
                "calculatedValues": [
                    {"name": "a", "expression": "{a}"},
                    {"name": "c", "expression": "{c} + 1"},
                ],
            }
        ),
        b"<document></document>",
        b"<document><LimeSurveyDocType>Survey</LimeSurveyDocType></document>",
        b"<document><LimeSurveyDocType>Survey</LimeSurveyDocType><questions><rows><row><qid>1</qid><type>L</type><title>q</title><gid>1</gid><relevance>rand(1,2) == 1</relevance></row><row><qid>1</qid><type>F</type><title>q</title><gid>1</gid></row></rows></questions><groups><rows><row><gid>1</gid></row><row><gid>1</gid></row></rows></groups></document>",  # noqa: E501
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><document>&a;</document>',
        b"<document><LimeSurveyDocType>Survey</LimeSurveyDocType><surveys><rows><row><language>xx-!!</language><format>Z</format></row></rows></surveys><quota><rows><row><id>1</id><active>1</active></row></rows></quota></document>",
        "\ufeff<document><LimeSurveyDocType>Survey</LimeSurveyDocType><groups><rows><row><gid>1</gid><grelevance>Q1 == 1</grelevance></row></rows></groups></document>".encode(),  # noqa: E501
    ],
)
def test_bad_input_never_raises(content: bytes | str) -> None:
    for fn in (import_qsf, import_lss, import_surveyjs):
        result = fn(content)
        assert result.format in FORMATS
        if result.ok:
            model, diags = parse(result.survey)
            assert model is not None and not [d for d in diags if d.severity == "error"]
        else:
            assert any(d.severity == "error" for d in result.diagnostics)
            assert not any(d.code.endswith(".internal") for d in result.diagnostics), [
                d.message for d in result.diagnostics
            ]


def test_forward_reference_is_dropped_not_fatal() -> None:
    doc = {
        "pages": [
            {"elements": [{"type": "text", "name": "a", "visibleIf": "{b} notempty"}]},
            {"elements": [{"type": "text", "name": "b"}]},
        ]
    }
    result = import_surveyjs(json.dumps(doc))
    assert result.ok
    assert "showIf" not in _by_id(result.survey)["a"]
    dropped = [d for d in result.diagnostics if d.code == "surveyjs.condition_dropped"]
    assert len(dropped) == 1 and dropped[0].target == "/blocks/0/pages/0/items/0/showIf"


def test_empty_survey_gets_a_page() -> None:
    result = import_surveyjs('{"pages": []}')
    assert result.ok and len(_questions(result.survey)) == 1
    assert any(d.code == "surveyjs.no_questions" for d in result.diagnostics)


# -- round trip through our own LimeSurvey export -------------------------------------------


@pytest.mark.parametrize("path", FIXTURES, ids=[p.parent.name for p in FIXTURES])
def test_fixture_round_trips_through_lss(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    source = data.get("survey", data)
    xml, export_diags = export_lss(source)
    assert xml
    result = import_lss(xml)
    assert result.ok, [d.message for d in result.diagnostics if d.severity == "error"]
    model, diags = parse(result.survey)
    assert model is not None and not [d for d in diags if d.severity == "error"]
    # Every question comes back with its export name, type and label (sliders too, via
    # the step check); the only questions that may go missing sit in a quota's
    # screen-out block, which the exporter turns into the quota message.
    quota_blocks = {q["onFull"].get("block") for q in source.get("quotas", [])}
    expected = [
        (q["type"], q.get("name") or q["id"])
        for b in source["blocks"]
        if b["id"] not in quota_blocks
        for p in b["pages"]
        for q in p["items"]
    ]
    got = [(q["type"], q.get("name") or q["id"]) for q in _questions(result.survey)]
    assert [x for x in expected if x not in got] == []
    # Variables keep their kinds (plus, at most, the exporter's end-outcome helper).
    ours = [(v["kind"], v["id"]) for v in source.get("variables", [])]
    back = [(v["kind"], v["id"]) for v in result.survey["variables"] if v["id"] != "ospoutcome"]
    assert back == ours
    # Required flags, choice values and bounds survive.
    src_q = {
        q.get("name") or q["id"]: q
        for b in source["blocks"]
        for p in b["pages"]
        for q in p["items"]
    }
    for q in _questions(result.survey):
        s = src_q.get(q.get("name") or q["id"])
        if s is None or s["type"] == "note":
            continue
        if s["type"] != "matrix":
            assert bool(q.get("required")) == bool(s.get("required")), q["id"]
        if "choices" in s:
            assert [c["value"] for c in q["choices"]] == [c["value"] for c in s["choices"]], q["id"]
        for key in ("min", "max"):
            if key in s and s["type"] in ("integer", "slider"):
                assert Decimal(str(q.get(key))) == Decimal(str(s[key])), (q["id"], key)


def test_renamed_codes_come_back_as_our_ids() -> None:
    xml, _ = export_lss(json.loads((REPO / "fixtures/01-all-types/survey.json").read_text("utf-8")))
    assert b"Renamed question codes" in xml
    result = import_lss(xml)
    assert [q["id"] for q in _questions(result.survey)] == [
        "note_intro", "n_int", "n_dec", "t_text", "s_single", "m_multi", "d_date",
    ]  # fmt: skip


# -- helpers and expression parsers --------------------------------------------------------


def test_identifier_helpers() -> None:
    assert sanitise_identifier("Q1 - Age?") == "Q1_Age"
    assert sanitise_identifier("1st") == "q_1st"
    assert sanitise_identifier("") == "item"
    assert sanitise_identifier("and") == "and_q"
    assert sanitise_identifier("seed") == "seed_q"  # reserved column name
    assert sanitise_identifier("_meta") == "meta_q"
    assert sanitise_identifier("__x") == "x"
    assert len(sanitise_identifier("x" * 100)) == 64
    ids = Ids()
    assert [ids.claim("Q1"), ids.claim("q1"), ids.claim("Q1")] == ["Q1", "q1_2", "Q1_3"]
    assert (
        choice_value("12") == 12 and choice_value("012") == "012" and choice_value(True) == "true"
    )
    assert unique_values([1, 1, "1"]) == (["1", "1_2", "1_3"], [1, 2])
    assert language_tag("EN") == "en" and language_tag("pt_br") == "pt-BR"
    assert language_tag("de-informal") == "de-informal" and language_tag("??", "en") == "en"
    assert html_to_text("<p>Hi&nbsp;<b>there</b></p><p>Two</p>") == ("Hi there\n\nTwo", True)
    assert html_to_text("plain") == ("plain", False)
    assert html_to_text("<script>x()</script>Shown<br>Next") == ("Shown\nNext", True)


def test_surveyjs_expressions() -> None:
    names = {"s": "s", "m": "m", "n": "n", "t": "t"}
    types = {"s": "single", "m": "multi", "n": "decimal", "t": "text"}
    values = {"s": {"a": "a", "1": 1}, "m": {"x": "x", "y": "y"}}

    def conv(src: str, value: bool = False) -> Any:
        return parse_expression(src, names, types, values, value=value)

    assert conv("{s} = 'a'").expr == {
        "kind": "compare",
        "op": "==",
        "left": {"kind": "ref", "id": "s"},
        "right": {"kind": "text", "value": "a"},
    }
    assert conv("{s} equal 1").expr["right"] == {"kind": "int", "value": 1}
    assert conv("{m} contains 'x'").expr == {
        "kind": "contains",
        "ref": {"kind": "ref", "id": "m"},
        "value": {"kind": "text", "value": "x"},
    }
    assert conv("{m} notcontains 'x'").expr["kind"] == "not"
    assert conv("{m} allof ['x', 'y']").expr["kind"] == "and"
    assert conv("{s} anyof ['a', 1]").expr["kind"] == "or"
    assert conv("{n} empty").expr == {
        "kind": "not",
        "arg": {"kind": "answered", "ref": {"kind": "ref", "id": "n"}},
    }
    assert conv("{n} notempty and {n} >= 2.5 or !({t} <> 'q')").expr["kind"] == "or"
    assert conv("{n}").expr["kind"] == "answered" and conv("{n}").notes
    assert conv("iif({n} > 1, {n} * 2, 0)", value=True).expr["kind"] == "if"
    assert conv("-{n} + 1", value=True).expr["kind"] == "arith"
    for bad in (
        "{zz} = 1",
        "age({n}) > 18",
        "{t} contains 'q'",
        "{n} = [1]",
        "{n} % 2 = 0",
        "({n} > 1",
        "{n} + 1",
        "'a' = 'b' =",
    ):
        r = conv(bad)
        assert r.expr is None and r.reason, bad


def test_em_expressions() -> None:
    names = EMNames(
        codes={"Q1": "q1", "M": "m", "N": "n", "D": "d"},
        qids={"7": "Q1"},
        types={"q1": "single", "m": "multi", "n": "decimal", "d": "date"},
        multi_codes={"m": {"a": "a", "b": "b"}},
        values={"q1": {"1": 1, "2": 2}},
    )
    conv = lambda s, value=False: parse_em(s, names, value=value)  # noqa: E731
    assert conv('Q1.NAOK == "1"').expr == {
        "kind": "compare",
        "op": "==",
        "left": {"kind": "ref", "id": "q1"},
        "right": {"kind": "int", "value": 1},
    }
    assert conv("123X4X7 eq 2").expr["right"] == {"kind": "int", "value": 2}
    assert conv('M_a.NAOK == "Y"').expr == {
        "kind": "contains",
        "ref": {"kind": "ref", "id": "m"},
        "value": {"kind": "text", "value": "a"},
    }
    assert conv('M_b != "Y"').expr["kind"] == "not"
    assert conv("!is_empty(N.NAOK) && N.NAOK > 3 || Q1.NAOK == 2").expr["kind"] == "or"
    assert conv("is_empty(N)").expr == {
        "kind": "not",
        "arg": {"kind": "answered", "ref": {"kind": "ref", "id": "n"}},
    }
    assert conv('N.NAOK == ""').expr["kind"] == "not"
    assert conv("strtotime(D.NAOK) >= strtotime('2026-01-01')").notes
    assert conv('if(N.NAOK > 1, N.NAOK, "")', value=True).expr["else"] == {"kind": "null"}
    assert conv("(N.NAOK + 1) / 2", value=True).expr["kind"] == "arith"
    assert conv("1").expr == {"kind": "bool", "value": True}
    assert conv("N.NAOK > 1 and 1").expr["kind"] == "compare"
    for bad in (
        "rand(1, 2) == 1",
        "ZZ == 1",
        "count(N) > 1",
        "N.NAOK ==",
        "M_a.NAOK == 3",
        "N.foo == 1",
        "N.NAOK + 1",
    ):
        r = conv(bad)
        assert r.expr is None and r.reason, bad
