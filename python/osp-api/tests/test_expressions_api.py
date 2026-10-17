"""POST /api/meta/expressions/parse and /print (condition builder, task B7)."""

from __future__ import annotations

import pytest
from osp_api.routes.expressions import parse_expression, print_expression

PARSE = "/api/meta/expressions/parse"
PRINT = "/api/meta/expressions/print"

SURVEY = {
    "specVersion": "osp-survey/0.1",
    "id": "s_cond",
    "version": 1,
    "metadata": {"title": "Conditions", "languages": ["en"]},
    "choiceLists": [
        {
            "id": "colour",
            "choices": [{"value": "red", "label": "Red"}, {"value": "blue", "label": "Blue"}],
        }
    ],
    "blocks": [
        {
            "id": "b1",
            "pages": [
                {
                    "id": "p1",
                    "items": [
                        {"type": "integer", "id": "age", "label": "Age"},
                        {
                            "type": "multi",
                            "id": "colours",
                            "label": "Colours",
                            "choiceList": "colour",
                        },
                    ],
                },
                {
                    "id": "p2",
                    "items": [
                        {"type": "text", "id": "q3", "label": "Why?"},
                        {"type": "text", "id": "q4", "label": "More"},
                    ],
                },
            ],
        }
    ],
    "flow": [{"type": "block", "id": "n1", "block": "b1"}, {"type": "end", "id": "end"}],
}

EXAMPLE = '(age >= 18 and contains(colours, "red")) or not answered(q3)'
CANONICAL = 'age >= 18 and contains(colours, "red") or not answered(q3)'  # minimal parentheses


def _survey(c) -> str:
    r = c.post("/api/surveys", json={"title": "Conditions", "survey": SURVEY})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_parse_returns_ast_canonical_text_and_references(benv):
    c = benv.login("editor@a.example")
    r = c.post(PARSE, json={"text": EXAMPLE.replace(" and ", "  and ")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["diagnostics"] == []
    assert body["text"] == CANONICAL
    assert body["references"] == ["age", "colours", "q3"]
    assert body["ast"]["kind"] == "or"
    assert body["ast"]["args"][1] == {
        "kind": "not",
        "arg": {"kind": "answered", "ref": {"kind": "ref", "id": "q3"}},
    }


def test_parse_error_has_positions(benv):
    c = benv.login("editor@a.example")
    body = c.post(PARSE, json={"text": "age >= 18 andd q3"}).json()
    assert body["ok"] is False and body["ast"] is None
    [d] = body["diagnostics"]
    assert (d["start"], d["end"]) == (10, 14)
    assert d["severity"] == "error"
    body = c.post(PARSE, json={"text": "age = 3"}).json()
    assert body["diagnostics"][0]["start"] == 4 and "==" in body["diagnostics"][0]["message"]


def test_parse_typechecks_against_survey(benv):
    c = benv.login("editor@a.example")
    sid = _survey(c)
    body = c.post(PARSE, json={"text": EXAMPLE, "surveyId": sid}).json()
    assert body["ok"] and body["diagnostics"] == []
    body = c.post(PARSE, json={"text": 'gone == 1 and contains(age, "x")', "surveyId": sid}).json()
    codes = {(d["code"], d["questionId"]) for d in body["diagnostics"]}
    assert ("unknown-question", "gone") in codes
    assert any(d["code"] == "contains-non-multi" and d["path"] for d in body["diagnostics"])


def test_parse_in_place_reports_forward_and_deleted_references(benv):
    c = benv.login("editor@a.example")
    sid = _survey(c)
    body = c.post(
        PARSE, json={"text": "answered(q3) or gone > 1", "surveyId": sid, "target": "age"}
    ).json()
    by_code = {d["code"]: d for d in body["diagnostics"]}
    assert by_code["ref.forward"]["questionId"] == "q3"
    assert by_code["ref.unknown"]["questionId"] == "gone"
    ok = c.post(PARSE, json={"text": EXAMPLE, "surveyId": sid, "target": "q4"}).json()
    assert ok["diagnostics"] == []
    bad_target = c.post(PARSE, json={"text": "age > 1", "surveyId": sid, "target": "nope"}).json()
    assert bad_target["ok"] and bad_target["diagnostics"][0]["code"] == "op.not_found"


def test_print_round_trips(benv):
    c = benv.login("editor@a.example")
    ast = c.post(PARSE, json={"text": EXAMPLE}).json()["ast"]
    r = c.post(PRINT, json={"ast": ast})
    assert r.status_code == 200 and r.json() == {"text": CANONICAL, "diagnostics": []}
    bad = c.post(PRINT, json={"ast": {"kind": "nope"}}).json()
    assert bad["text"] is None and bad["diagnostics"][0]["code"] == "invalid-ast"


def test_auth_required_and_survey_access_enforced(benv):
    anon = benv.client()
    assert anon.post(PARSE, json={"text": "a"}).status_code == 401
    assert anon.post(PRINT, json={"ast": {"kind": "null"}}).status_code == 401
    sid = _survey(benv.login("editor@a.example"))
    other = benv.login("owner@b.example")
    r = other.post(PARSE, json={"text": "age > 1", "surveyId": sid})
    assert r.status_code in (403, 404)


def test_csrf_required(benv):
    c = benv.login("editor@a.example")
    del c.headers["X-CSRF-Token"]
    assert c.post(PARSE, json={"text": "a"}).status_code == 403


@pytest.mark.parametrize(
    "text",
    ["", "(" * 500, '"' + "x" * 100, "not " * 200 + "a", "\x00", "contains(", "1..2", "a ==== b"],
)
def test_hostile_text_never_crashes(text):
    res = parse_expression(text, SURVEY, "q4")
    assert res.ok is False or res.ast is not None


@pytest.mark.parametrize(
    "ast",
    [None, [], {}, {"kind": "and", "args": []}, {"kind": "ref", "id": "and"}, "x", 3],
)
def test_hostile_ast_never_crashes(ast):
    assert print_expression(ast).text is None


def test_deep_ast_is_a_diagnostic():
    ast: dict = {"kind": "null"}
    for _ in range(5000):
        ast = {"kind": "not", "arg": ast}
    res = print_expression(ast)
    assert res.text is None or res.text.startswith("not")


def test_matrix_rows_and_sliders_are_typed() -> None:
    """C2c: a matrix row is a single-choice variable `m_r`; a slider has its value type."""
    from osp_api.routes.expressions import _types

    items = [
        {"type": "matrix", "id": "m", "rows": [{"id": "a"}, {"id": "b"}]},
        {"type": "slider", "id": "s1"},
        {"type": "slider", "id": "s2", "valueType": "decimal"},
    ]
    survey = {"blocks": [{"pages": [{"items": items}]}]}
    assert _types(survey) == {"m_a": "single", "m_b": "single", "s1": "integer", "s2": "decimal"}
