"""LimeSurvey .lss export: every survey exports to well-formed, deterministic XML; every
non-native feature used is reported with a JSON pointer that resolves in the survey;
golden files for three fixtures; feature checks on small surveys.

Regenerate the goldens with ``OSP_UPDATE_GOLDEN=1``.
"""

from __future__ import annotations

import copy
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest
from osp_spec import parse
from osp_targets.lss import LSS, RESERVED_CODES, build_lss, export_lss, feature_uses, sanitise_code

REPO = Path(__file__).resolve().parents[3]
CASES = sorted((REPO / "python/osp-spec/tests/cases/valid").glob("*.json"))
FIXTURES = sorted((REPO / "fixtures").glob("*/survey.json"))
GOLDEN = Path(__file__).parent / "data/lss"
GOLDEN_FIXTURES = ["13-randomiser-blocks", "17-piping", "20-worked-example"]


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


def _rows(root: ET.Element, table: str) -> list[dict[str, str]]:
    el = root.find(table)
    if el is None:
        return []
    return [{c.tag: c.text or "" for c in row} for row in el.iter("row")]


def _export(data: Any) -> tuple[Any, list[Any], ET.Element]:
    result, diags = build_lss(data)
    assert result is not None, diags
    return result, diags, ET.fromstring(result.xml)


def test_there_are_surveys() -> None:
    assert len(CASES) >= 10
    assert len(FIXTURES) >= 30


@pytest.mark.parametrize(("label", "data"), SURVEYS, ids=[s[0] for s in SURVEYS])
def test_export_is_well_formed(label: str, data: Any) -> None:
    xml, diags = export_lss(data)
    assert not [d for d in diags if d.severity == "error"], diags
    root = ET.fromstring(xml)  # raises if not well-formed
    assert root.tag == "document"
    assert root.findtext("LimeSurveyDocType") == "Survey"
    survey, _ = parse(data)
    assert survey is not None
    langs = [e.text for e in root.iter("language") if e.text and len(list(e)) == 0]
    assert set(survey.metadata.languages) <= set(langs)

    # Question codes: valid, unique ignoring case, never reserved.
    questions = _rows(root, "questions")
    codes = [q["title"] for q in questions]
    assert codes
    assert len({c.lower() for c in codes}) == len(codes)
    for c in codes:
        assert c == sanitise_code(c) and c.lower() not in RESERVED_CODES, c
    # Every question sits in a group that exists; every l10n row names a known language.
    gids = {g["gid"] for g in _rows(root, "groups")}
    assert {q["gid"] for q in questions} <= gids
    for row in _rows(root, "question_l10ns"):
        assert row["language"] in survey.metadata.languages
    for row in _rows(root, "answers"):
        assert 1 <= len(row["code"]) <= 5 and row["code"].isalnum(), row

    # Diagnostics: level from the table, pointer resolves in the survey document.
    doc = json.loads(json.dumps(data))
    for d in diags:
        assert d.target == "lss"
        assert d.feature in LSS, d
        cap = LSS[d.feature]
        assert d.level == cap.level != "native"
        assert d.code == f"lss.{cap.level}"
        assert d.severity == {"lowered": "info", "approximated": "warning",
                              "unsupported": "loss"}[cap.level]  # fmt: skip
        _resolve(doc, d.pointer)

    # Every non-native field the survey uses has a diagnostic at its pointer, except inside
    # a quota that could not be exported (reported once, as Quota.when=unmappable).
    dropped = {d.pointer.rsplit("/", 1)[0] for d in diags if d.feature == "Quota.when=unmappable"}
    reported = {(d.feature, d.pointer) for d in diags}
    for key, ptr, _value in feature_uses(survey):
        if LSS[key].level == "native" or any(ptr == q or ptr.startswith(q + "/") for q in dropped):
            continue
        node_ptr = ptr if key == "QuotaCheckNode.type" else ptr.rsplit("/", 1)[0]
        if key.startswith("QuotaCheckNode.") and ("$quota.dropped", node_ptr) in reported:
            continue
        assert (key, ptr) in reported, (key, ptr)


@pytest.mark.parametrize(("label", "data"), SURVEYS, ids=[s[0] for s in SURVEYS])
def test_deterministic_bytes(label: str, data: Any) -> None:
    a, da = export_lss(data)
    b, db = export_lss(copy.deepcopy(data))
    assert a == b
    assert da == db


def test_accepts_survey_model() -> None:
    data = json.loads(CASES[0].read_text(encoding="utf-8"))["survey"]
    survey, _ = parse(data)
    assert survey is not None
    assert export_lss(survey) == export_lss(data)


@pytest.mark.parametrize("name", GOLDEN_FIXTURES)
def test_golden(name: str) -> None:
    xml, diags = export_lss(_fixture_survey(REPO / "fixtures" / name / "survey.json"))
    got_diags = "".join(
        f"{d.severity}\t{d.feature}\t{d.pointer}\n" for d in diags
    )  # messages are long; the table holds them
    path_xml = GOLDEN / f"{name}.lss"
    path_diags = GOLDEN / f"{name}.diagnostics.tsv"
    if os.environ.get("OSP_UPDATE_GOLDEN") == "1":
        GOLDEN.mkdir(parents=True, exist_ok=True)
        path_xml.write_bytes(xml)
        path_diags.write_text(got_diags, encoding="utf-8", newline="\n")
    assert xml == path_xml.read_bytes(), f"{name}: regenerate with OSP_UPDATE_GOLDEN=1"
    assert got_diags == path_diags.read_text(encoding="utf-8")


def test_never_raises_on_bad_input() -> None:
    for bad in (None, 5, "x", [], {}, {"specVersion": "osp-survey/0.1"}):
        xml, diags = export_lss(bad)  # type: ignore[arg-type]
        assert xml == b""
        assert diags and all(d.severity == "error" for d in diags)
        assert diags[0].code.startswith("lss.error.")


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


def _question(root: ET.Element, code: str) -> dict[str, str]:
    return next(q for q in _rows(root, "questions") if q["title"] == code)


def _attrs(root: ET.Element, qid: str) -> dict[str, str]:
    return {
        a["attribute"]: a["value"] for a in _rows(root, "question_attributes") if a["qid"] == qid
    }


def test_names_that_become_reserved_are_renamed_and_reported() -> None:
    """`i_d` sanitises to `id`, a LimeSurvey response column (spike-1 Q2)."""
    data = _survey([_q("i_d"), _q("q2", name="Token_"), _q("ok")])
    result, diags, root = _export(data)
    assert result.renamed == {"i_d": "id2", "Token_": "Token2"}
    assert result.name_map["ok"] == "ok"
    reserved = {(d.feature, d.pointer) for d in diags if d.feature == "$names.reserved"}
    assert reserved == {
        ("$names.reserved", "/blocks/0/pages/0/items/0/id"),
        ("$names.reserved", "/blocks/0/pages/0/items/1/name"),
    }
    codes = [q["title"] for q in _rows(root, "questions")]
    assert codes == ["id2", "Token2", "ok"]
    assert "Renamed question codes: i_d=id2, Token_=Token2" in result.xml.decode()


def test_every_reserved_name_is_avoided() -> None:
    for name in ("id", "token", "submitdate", "lastpage", "startlanguage", "seed",
                 "startdate", "datestamp", "ipaddr", "refurl"):  # fmt: skip
        assert name in RESERVED_CODES
        mangled = name[0] + "_" + name[1:]
        result, diags, _ = _export(_survey([_q(mangled)]))
        assert result.name_map[mangled].lower() != name
        assert any(d.feature == "$names.reserved" for d in diags)


def test_invalid_codes_are_rewritten_without_collisions() -> None:
    data = _survey([_q("a_b"), _q("ab"), _q("x" * 30), _q("x" * 25 + "_2")])
    result, diags, _ = _export(data)
    assert result.name_map["ab"] == "ab"  # a valid name is never taken by a rewrite
    assert result.name_map["a_b"] == "ab2"
    assert result.name_map["x" * 30] == "x" * 20
    assert result.name_map["x" * 25 + "_2"] == "x" * 19 + "2"
    assert sum(d.feature == "$names.rename" for d in diags) == 3


def test_choice_codes_map_to_answers_and_subquestions() -> None:
    choices = [{"value": 1, "label": "One"}, {"value": -1, "label": "Minus"},
               {"value": "toolong", "label": "Long"}]  # fmt: skip
    data = _survey(
        [
            _q("s", "single", choices=choices, choiceOrder="shuffle"),
            _q(
                "m",
                "multi",
                choices=[{"value": "x-y", "label": "XY"}, {"value": "b", "label": "B"}],
            ),
            _q(
                "f",
                showIf={
                    "kind": "contains",
                    "ref": {"kind": "ref", "id": "m"},
                    "value": {"kind": "text", "value": "x-y"},
                },
            ),  # fmt: skip
        ]
    )
    result, diags, root = _export(data)
    assert [a["code"] for a in _rows(root, "answers")] == ["1", "A1", "A2"]
    assert result.choice_codes == {"s": {"-1": "A1", "toolong": "A2"}, "m": {"x-y": "A1"}}
    sub = _rows(root, "subquestions")
    assert [(s["title"], s["type"]) for s in sub] == [("A1", "T"), ("b", "T")]
    assert _question(root, "f")["relevance"] == 'm_A1.NAOK == "Y"'
    s = _question(root, "s")
    assert s["type"] == "L" and _attrs(root, s["qid"])["random_order"] == "1"
    assert _question(root, "m")["type"] == "M"
    features = {d.feature for d in diags}
    assert {"$choice.code", "SingleQuestion.choiceOrder=shuffle", "MultiQuestion.type"} <= features


def test_types_required_constraint_and_messages() -> None:
    con = {"kind": "compare", "op": ">=", "left": {"kind": "ref", "id": "age"},
           "right": {"kind": "int", "value": 18}}  # fmt: skip
    data = _survey(
        [
            _q(
                "age", required=True, constraint=con, constraintMessage={"en": "18+", "de": "ab 18"}
            ),
            _q("dec", "decimal"),
            _q("t", "text", help="A hint"),
            _q("d", "date"),
            {"id": "n", "type": "note", "label": "Hi"},
        ]
    )
    data["metadata"]["languages"] = ["en", "de"]
    _, _, root = _export(data)
    types = {q["title"]: q["type"] for q in _rows(root, "questions")}
    assert types == {"age": "N", "dec": "N", "t": "S", "d": "D", "n": "X"}
    age = _question(root, "age")
    assert age["mandatory"] == "Y"
    attrs = _rows(root, "question_attributes")
    mine = [(a["attribute"], a["value"], a["language"]) for a in attrs if a["qid"] == age["qid"]]
    assert mine == [
        ("num_value_int_only", "1", ""),
        ("em_validation_q", "is_empty(age.NAOK) or (!is_empty(age.NAOK) and (age.NAOK >= 18))", ""),
        ("em_validation_q_tip", "18+", "en"),
        ("em_validation_q_tip", "ab 18", "de"),
    ]
    helps = [r["help"] for r in _rows(root, "question_l10ns") if r["help"]]
    assert helps == ["A hint", "A hint"]


def test_languages_and_survey_settings() -> None:
    data = _survey([_q("q1")], settings={"backNavigation": False})
    data["metadata"] = {"title": {"en": "Hello", "cy": "Helo"}, "description": "D",
                        "languages": ["en", "cy"], "defaultLanguage": "cy"}  # fmt: skip
    _, _, root = _export(data)
    survey = _rows(root, "surveys")[0]
    assert survey["language"] == "cy"
    assert survey["additional_languages"] == "en"
    assert survey["allowprev"] == "N"
    assert survey["ipaddr"] == "N"
    titles = {
        r["surveyls_language"]: r["surveyls_title"] for r in _rows(root, "surveys_languagesettings")
    }
    assert titles == {"cy": "Helo", "en": "Hello"}
    assert [e.text for e in root.find("languages") or []] == ["cy", "en"]


def test_piping_uses_shown_for_choice_labels() -> None:
    data = _survey(
        [
            _q("c", "single", choices=[{"value": 1, "label": "Red"}]),
            _q("n"),
            _q("m", "multi", choices=[{"value": "a", "label": "A"}]),
        ]
    )
    data["blocks"].append(
        {
            "id": "b2",
            "pages": [
                {
                    "id": "p2",
                    "items": [
                        {
                            "id": "show",
                            "type": "note",
                            "label": "You chose ${c}, ${n} & ${m} {x} <b>",
                        }
                    ],
                }
            ],
        }  # fmt: skip
    )
    data["flow"].append({"type": "block", "id": "f2", "block": "b2"})
    _, diags, root = _export(data)
    show = _question(root, "show")["qid"]
    text = next(r["question"] for r in _rows(root, "question_l10ns") if r["qid"] == show)
    assert text.startswith("You chose {c.shown}, {n} &amp; {")
    assert text.endswith("} \\{x} &lt;b&gt;")
    assert {"$pipe.multi", "$text.markup", "$text.braces"} <= {d.feature for d in diags}


def test_branches_and_end_nodes_become_group_relevance() -> None:
    gate = _q("gate", "single", choices=[{"value": 1, "label": "Y"}, {"value": 0, "label": "N"}])
    data = _survey([gate])
    data["blocks"].append({"id": "b2", "pages": [{"id": "p2", "items": [_q("x")]},
                                                 {"id": "p3", "items": [_q("y")]}]})  # fmt: skip
    cond = {"kind": "compare", "op": "==", "left": {"kind": "ref", "id": "gate"},
            "right": {"kind": "int", "value": 0}}  # fmt: skip
    data["flow"] += [
        {"type": "branch", "id": "br", "if": cond,
         "then": [{"type": "end", "id": "e1", "outcome": "declined", "message": "Bye"}]},
        {"type": "block", "id": "f2", "block": "b2"},
    ]  # fmt: skip
    result, diags, root = _export(data)
    groups = _rows(root, "groups")
    rel = '!is_empty(gate.NAOK) and (gate.NAOK == "0")'
    assert [g["grelevance"] for g in groups] == ["1", rel, f"!({rel})", f"!({rel})", "1"]
    assert result.helpers["ospoutcome"].startswith("end outcome")
    outcome = _question(root, "ospoutcome")
    text = next(r["question"] for r in _rows(root, "question_l10ns") if r["qid"] == outcome["qid"])
    assert text == "{if(" + rel + ', "declined", "complete")}'
    assert "EndNode.type" in {d.feature for d in diags}


def test_assignment_is_latched() -> None:
    data = _survey([_q("q1")])
    data["variables"] = [{"kind": "assigned", "id": "arm", "levels": ["a", "b"]}]
    data["flow"].insert(0, {"type": "assign", "id": "as", "variables": ["arm"]})
    result, diags, root = _export(data)
    texts = {r["qid"]: r["question"] for r in _rows(root, "question_l10ns")}
    by_code = {q["title"]: texts[q["qid"]] for q in _rows(root, "questions")}
    assert by_code["ospseedarm"] == "{if(!is_empty(ospseedarm.NAOK), ospseedarm.NAOK, rand(1, 2))}"
    assert by_code["arm"] == '{if(ospseedarm.NAOK == 1, "a", if(ospseedarm.NAOK == 2, "b", ""))}'
    # Helpers sit in the first group, before the first question, and are hidden.
    assert [q["title"] for q in _rows(root, "questions")] == ["ospseedarm", "arm", "q1"]
    hidden = {a["qid"] for a in _rows(root, "question_attributes") if a["attribute"] == "hidden"}
    assert {_question(root, "arm")["qid"], _question(root, "ospseedarm")["qid"]} <= hidden
    approx = [d for d in diags if d.feature == "AssignedVariable.kind"]
    assert approx and approx[0].severity == "warning"


def test_randomiser_of_one_page_blocks_uses_randomization_group() -> None:
    data = _survey([_q("q0")])
    data["blocks"] += [{"id": f"r{i}", "pages": [{"id": f"rp{i}", "items": [_q(f"x{i}")]}]}
                       for i in range(3)]  # fmt: skip
    children = [{"type": "block", "id": f"fr{i}", "block": f"r{i}"} for i in range(3)]
    data["flow"].append({"type": "randomiser", "id": "rnd", "children": children})
    _, diags, root = _export(data)
    groups = _rows(root, "groups")
    assert [g["randomization_group"] for g in groups] == ["", *["osprandrnd"] * 3]
    msgs = [d for d in diags if d.feature == "RandomiserNode.children"]
    assert msgs and "seed is not reproduced" in msgs[0].message


def test_randomiser_pick_draws_in_a_setup_group() -> None:
    data = _survey([_q("q0")])
    data["blocks"] += [{"id": f"r{i}", "pages": [{"id": f"rp{i}", "items": [_q(f"x{i}")]},
                                                 {"id": f"rq{i}", "items": [_q(f"y{i}")]}]}
                       for i in range(3)]  # fmt: skip
    children = [{"type": "block", "id": f"fr{i}", "block": f"r{i}"} for i in range(3)]
    data["flow"] = [{"type": "randomiser", "id": "rnd", "children": children, "pick": 2}]
    data["flow"].append({"type": "block", "id": "f1", "block": "b1"})
    result, diags, root = _export(data)
    groups = _rows(root, "groups")
    # Multi-page children cannot be shuffled as groups: document order, reported.
    assert {g["randomization_group"] for g in groups} == {""}
    assert any(
        d.feature == "RandomiserNode.children" and "document order" in d.message for d in diags
    )
    # The draws come first, in their own group (the first real group is conditional).
    first = [q["title"] for q in _rows(root, "questions") if q["gid"] == groups[0]["gid"]]
    assert first == ["osprnd1", "osprnd2", "osprnd3"]
    assert groups[1]["grelevance"] == (
        "if(osprnd2.NAOK > osprnd1.NAOK, 1, 0) + if(osprnd3.NAOK > osprnd1.NAOK, 1, 0) < 2"
    )
    assert len(result.helpers) == 3


def test_page_item_shuffle_uses_random_group() -> None:
    data = _survey([_q("a"), _q("b")])
    data["blocks"][0]["pages"][0]["itemOrder"] = "shuffle"
    _, diags, root = _export(data)
    groups = {
        a["value"] for a in _rows(root, "question_attributes") if a["attribute"] == "random_group"
    }
    assert groups == {"osppagep1"}
    assert "Page.itemOrder=shuffle" in {d.feature for d in diags}


def test_embedded_variable_is_a_prefilled_hidden_question_with_default() -> None:
    data = _survey([_q("q1")])
    data["variables"] = [{"kind": "embedded", "id": "src", "param": "source", "default": "web"}]
    _, diags, root = _export(data)
    src = _question(root, "src")
    assert src["type"] == "S"
    assert _attrs(root, src["qid"]) == {"hidden": "1"}
    assert [d["defaultvalue"] for d in _rows(root, "defaultvalue_l10ns")] == ["web"]
    param = [d for d in diags if d.feature == "EmbeddedVariable.param"]
    assert param and param[0].pointer == "/variables/0/param"


def test_computed_variable_sits_with_its_last_input() -> None:
    data = _survey([_q("a")])
    data["blocks"].append({"id": "b2", "pages": [{"id": "p2", "items": [_q("b")]}]})
    data["flow"].append({"type": "block", "id": "f2", "block": "b2"})
    data["variables"] = [{"kind": "computed", "id": "total", "expr": {
        "kind": "arith", "op": "+", "left": {"kind": "ref", "id": "a"},
        "right": {"kind": "ref", "id": "b"}}}]  # fmt: skip
    _, _, root = _export(data)
    groups = _rows(root, "groups")
    total = _question(root, "total")
    assert total["gid"] == groups[1]["gid"] and total["type"] == "*"


def _quota_survey(when: dict) -> dict:
    region = _q("region", "single", choices=[{"value": "north", "label": "N"},
                                            {"value": "south", "label": "S"}])  # fmt: skip
    tags = _q("tags", "multi", choices=[{"value": "a", "label": "A"}, {"value": "b", "label": "B"}])
    data = _survey([region, tags])
    data["blocks"].append({"id": "full", "pages": [{"id": "fp", "items": [
        {"id": "sorry", "type": "note", "label": "Sorry, full"}]}]})  # fmt: skip
    data["quotas"] = [{"id": "qn", "when": when, "limit": 10,
                       "onFull": {"block": "full", "outcome": "screenout"}}]  # fmt: skip
    data["flow"].append({"type": "quotaCheck", "id": "qc", "quota": "qn"})
    return data


def _eq(qid: str, value: str) -> dict:
    return {"kind": "compare", "op": "==", "left": {"kind": "ref", "id": qid},
            "right": {"kind": "text", "value": value}}  # fmt: skip


def test_end_redirects_become_end_urls_when_every_param_is_literal() -> None:
    """EN2: the `complete` ending's redirect is the survey end URL (auto-loaded in `auto`
    mode), a quota outcome's redirect is the quota URL; literals are percent-encoded; a
    piped param drops the redirect with a loss (LimeSurvey cannot re-check the pattern)."""
    data = _quota_survey(_eq("region", "north"))
    data["settings"] = {
        "redirectTemplates": {
            "prolific": {"url": "https://app.prolific.com/submissions/complete?cc={cc}",
                         "params": {"cc": {"pattern": "[A-Z0-9 &]{4,8}"}}},
            "lab": {"url": "https://lab.example.org/full/{why}", "params": {"why": {}}},
        },
        "endings": {
            "complete": {"redirect": {"template": "prolific", "params": {"cc": "C1 &B2"},
                                      "label": "Back to Prolific"}},
            "screenout": {"redirect": {"template": "lab", "mode": "link",
                                       "params": {"why": "full"}}},
        },
    }  # fmt: skip
    _, diags, root = _export(data)
    [ls] = _rows(root, "surveys_languagesettings")
    assert ls["surveyls_url"] == "https://app.prolific.com/submissions/complete?cc=C1%20%26B2"
    assert ls["surveyls_urldescription"] == "Back to Prolific"
    [srv] = _rows(root, "surveys")
    assert srv["autoredirect"] == "Y"
    [quota] = _rows(root, "quota")
    assert quota["autoload_url"] == "0"  # link mode
    [ql] = _rows(root, "quota_languagesettings")
    assert ql["quotals_url"] == "https://lab.example.org/full/full"
    levels = {d.feature: d.severity for d in diags}
    assert levels["Ending.redirect"] == "warning" and levels["EndRedirect.delay"] == "loss"
    # A piped param: no URL, the redirect is reported as a loss; link mode: no autoredirect.
    data["settings"]["endings"]["complete"]["redirect"] = {
        "template": "prolific", "params": {"cc": "${region}"}, "mode": "link"}  # fmt: skip
    _, diags, root = _export(data)
    [ls] = _rows(root, "surveys_languagesettings")
    assert "surveyls_url" not in ls
    assert _rows(root, "surveys")[0]["autoredirect"] == "N"
    assert any(d.feature == "$redirect.piped" and d.severity == "loss" for d in diags)


def test_endings_fill_end_text_quota_message_and_end_groups() -> None:
    """EN1: `complete` → surveyls_endtext, a quota's outcome → its quota message, another
    outcome → a boilerplate question with the End node."""
    data = _quota_survey(_eq("region", "north"))
    data["flow"].append({"type": "branch", "id": "br", "if": _eq("region", "south"),
                         "then": [{"type": "end", "id": "e_out", "outcome": "out"}]})  # fmt: skip
    data["settings"] = {"endings": {
        "complete": {"title": "Thanks", "body": "Region ${region}."},
        "screenout": {"body": "Group full"},
        "out": {"title": "Not for you"},
    }}  # fmt: skip
    _, diags, root = _export(data)
    [ls] = _rows(root, "surveys_languagesettings")
    assert ls["surveyls_endtext"] == "<p>Thanks</p><p>Region {region.shown}.</p>"
    assert [m["quotals_message"] for m in _rows(root, "quota_languagesettings")] == [
        "<p>Group full</p>"
    ]
    ending = _question(root, "ospendingeout")
    assert ending["type"] == "X"
    texts = {q["qid"]: q["question"] for q in _rows(root, "question_l10ns")}
    assert texts[ending["qid"]] == "<p>Not for you</p>"
    levels = {d.feature: d.severity for d in diags}
    assert levels["Settings.endings"] == "warning" and levels["Ending.body"] == "info"


def test_quota_maps_to_members() -> None:
    when = {"kind": "and", "args": [
        {"kind": "or", "args": [_eq("region", "north"), _eq("region", "south")]},
        {"kind": "contains", "ref": {"kind": "ref", "id": "tags"},
         "value": {"kind": "text", "value": "b"}},
    ]}  # fmt: skip
    _, diags, root = _export(_quota_survey(when))
    quota = _rows(root, "quota")
    assert [(q["name"], q["qlimit"], q["action"]) for q in quota] == [("qn", "10", "1")]
    region, tags = _question(root, "region")["qid"], _question(root, "tags")["qid"]
    members = [(m["qid"], m["code"]) for m in _rows(root, "quota_members")]
    assert members == [(region, "north"), (region, "south"), (tags, "b")]
    msg = _rows(root, "quota_languagesettings")
    assert [m["quotals_message"] for m in msg] == ["<p>Sorry, full</p>"]
    features = {d.feature for d in diags}
    assert {"Quota.when", "QuotaFull.block", "QuotaCheckNode.type"} <= features
    assert "Quota.when=unmappable" not in features


@pytest.mark.parametrize(
    "when",
    [
        {"kind": "answered", "ref": {"kind": "ref", "id": "region"}},
        {"kind": "and", "args": [_eq("region", "north"), _eq("region", "south")]},
        {"kind": "or", "args": [_eq("region", "north"),
                                {"kind": "contains", "ref": {"kind": "ref", "id": "tags"},
                                 "value": {"kind": "text", "value": "a"}}]},
        _eq("region", "west"),
    ],
    ids=["answered", "and-same-question", "or-across-questions", "unknown-code"],
)  # fmt: skip
def test_unmappable_quota_is_dropped_and_reported_once(when: dict) -> None:
    _, diags, root = _export(_quota_survey(when))
    assert _rows(root, "quota") == []
    under = [d for d in diags if d.pointer.startswith("/quotas/")]
    assert [(d.feature, d.severity) for d in under] == [("Quota.when=unmappable", "loss")]
    check = [d for d in diags if d.pointer == "/flow/1"]
    assert [(d.feature, d.severity) for d in check] == [("$quota.dropped", "loss")]


def test_multiline_text_is_long_free_text() -> None:
    data = _survey([_q("long", "text", multiline=True), _q("short", "text")])
    _, _, root = _export(data)
    assert _question(root, "long")["type"] == "T"
    assert _question(root, "short")["type"] == "S"
    themes = {q["title"]: q.get("question_theme_name") for q in _rows(root, "questions")}
    assert themes == {"long": "longfreetext", "short": "shortfreetext"}


def test_matrix_is_an_array_and_slider_a_number() -> None:
    """C2c: matrix → type F with one subquestion per row; a row is `<q>_<sq>` in EM.
    Slider → type N with min/max/step validation, reported as approximated."""
    import re

    data = json.loads((REPO / "fixtures/38-matrix/survey.json").read_text(encoding="utf-8"))
    out, diags = build_lss(data)
    assert out is not None, diags
    xml = out.xml.decode()
    assert "<type><![CDATA[F]]></type>" in xml
    assert out.name_map["drink_tea"] == "drink_tea"
    assert 'drink_tea.NAOK == "3"' in xml
    assert "!is_empty(drink_tea.NAOK) and !is_empty(drink_coffee.NAOK)" in xml
    assert "$matrix.someRowsRequired" in {d.feature for d in diags}

    data = json.loads((REPO / "fixtures/39-slider/survey.json").read_text(encoding="utf-8"))
    out, diags = build_lss(data)
    assert out is not None, diags
    assert re.search(r"fmod\(sleep\.NAOK - \(0\), 0\.5\) == 0", out.xml.decode())
    levels = {d.feature: d.level for d in diags}
    assert levels["SliderQuestion.type"] == "approximated"
