"""Small targeted checks for diagnostic codes the fixture cases don't cover, plus a guard
that every registered code is exercised somewhere."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from osp_spec import CODES, RESERVED_NAMES, publish_diagnostics, validate

CASES = Path(__file__).parent / "cases"
P0 = "/blocks/0/pages/0/items"
UNTESTABLE = {
    "expr.type",  # needs osp_expr.static (C1); covered by test_expr.py once merged
    "internal.error",  # the safety net; fuzz tests assert it never fires
}


def base() -> dict[str, Any]:
    return {
        "specVersion": "osp-survey/0.1",
        "id": "srv",
        "metadata": {"title": "T", "languages": ["en"]},
        "blocks": [
            {"id": "b1", "pages": [{"id": "p1", "items": [
                {"id": "q1", "type": "integer", "label": "Q1"},
                {"id": "q2", "type": "integer", "label": "Q2"},
            ]}]},
        ],
        "flow": [{"type": "block", "id": "f1", "block": "b1"}],
    }  # fmt: skip


def answered(qid: str) -> dict:
    """`answered(qid)` as C1 AST JSON."""
    return {"kind": "answered", "ref": {"kind": "ref", "id": qid}}


def _items(s: dict) -> list:
    return s["blocks"][0]["pages"][0]["items"]


def _add_block(s: dict, bid: str, qid: str) -> None:
    s["blocks"].append(
        {"id": bid, "pages": [{"id": f"p_{bid}", "items": [
            {"id": qid, "type": "integer", "label": qid}]}]}
    )  # fmt: skip


def m_lang_dup(s):
    s["metadata"]["languages"] = ["en", "en"]


def m_lang_default(s):
    s["metadata"]["defaultLanguage"] = "de"


def m_case_collision(s):
    _items(s)[1]["name"] = "Q1"


def m_mixed(s):
    choices = [{"value": 1, "label": "A"}, {"value": "b", "label": "B"}]
    _items(s)[0] = {"id": "q1", "type": "single", "label": "Q1", "choices": choices}


def m_unused_list(s):
    s["choiceLists"] = [{"id": "yn", "choices": [{"value": 1, "label": "Y"}]}]


def m_unknown_var(s):
    s["flow"].append({"type": "assign", "id": "f2", "variables": ["nope"]})


def m_not_in_flow(s):
    _add_block(s, "b2", "q3")
    _items(s)[0]["showIf"] = answered("q3")


def m_other_branch(s):
    _add_block(s, "b2", "qa")
    _add_block(s, "b3", "qb")
    s["blocks"][2]["pages"][0]["items"][0]["showIf"] = answered("qa")
    s["flow"].append({"type": "branch", "id": "f2", "if": answered("q1"),
                      "then": [{"type": "block", "id": "f3", "block": "b2"}],
                      "else": [{"type": "block", "id": "f4", "block": "b3"}]})  # fmt: skip


def m_pipe_invalid(s):
    _items(s)[1]["label"] = "You said ${q 1}"


def m_flow_empty(s):
    s["flow"] = []


def m_empty_branch(s):
    s["flow"].append({"type": "branch", "id": "f2", "if": answered("q1"), "then": []})


def m_reassigned(s):
    s["variables"] = [{"kind": "assigned", "id": "grp", "levels": ["a", "b"]}]
    s["flow"] += [{"type": "assign", "id": "f2", "variables": ["grp"]},
                  {"type": "assign", "id": "f3", "variables": ["grp"]}]  # fmt: skip


def m_never_assigned(s):
    s["variables"] = [{"kind": "assigned", "id": "grp", "levels": ["a", "b"]}]


def m_dup_level(s):
    s["variables"] = [{"kind": "assigned", "id": "grp", "levels": ["a", "a"]}]
    s["flow"].append({"type": "assign", "id": "f2", "variables": ["grp"]})


def m_default_type(s):
    s["variables"] = [{"kind": "embedded", "id": "n", "valueType": "integer",
                       "param": "n", "default": "ten"}]  # fmt: skip


def m_block_unused(s):
    _add_block(s, "b2", "q3")


def m_quota_unused(s):
    s["quotas"] = [{"id": "qt", "when": answered("q1"), "limit": 5,
                    "onFull": {"outcome": "quotafull"}}]  # fmt: skip


def m_quota_block(s):
    m_quota_unused(s)
    s["quotas"][0]["onFull"]["block"] = "nope"
    s["flow"].append({"type": "quotaCheck", "id": "f2", "quota": "qt"})


def m_schema_value(s):
    s["metadata"]["languages"] = []


def m_reserved_suffix(s):
    _items(s)[0]["name"] = "age__state"


def m_reserved_prefix(s):
    _items(s)[0]["name"] = "_order"


def gt(qid: str, n: int) -> dict:
    return {"kind": "compare", "op": ">", "left": {"kind": "ref", "id": qid},
            "right": {"kind": "int", "value": n}}  # fmt: skip


def m_same_page_cycle(s):
    _items(s)[0]["showIf"] = gt("q2", 1)
    _items(s)[1]["showIf"] = gt("q1", 1)


def m_bounds(s):
    _items(s)[0].update({"min": 5, "max": 1})


def m_decimal_bound_too_long(s):
    _items(s)[1] = {"id": "q2", "type": "decimal", "label": "Q2",
                    "max": "12345678901234567890.123456789"}  # fmt: skip


def m_retention(s):
    s["settings"] = {"retention": {"kind": "after-date"}}


def m_page_showif_own_item(s):
    s["blocks"][0]["pages"][0]["showIf"] = answered("q1")


def m_quota_forward(s):
    _add_block(s, "b2", "q3")
    s["quotas"] = [{"id": "qt", "when": answered("q3"), "limit": 5,
                    "onFull": {"outcome": "quotafull"}}]  # fmt: skip
    s["flow"] = [{"type": "block", "id": "f1", "block": "b1"},
                 {"type": "quotaCheck", "id": "f2", "quota": "qt"},
                 {"type": "block", "id": "f3", "block": "b2"}]  # fmt: skip


def m_consent_pipe(s: dict) -> None:
    s["consent"] = {"text": "Consent?", "agreeLabel": "Yes, ${q1}"}


def m_consent_outcome(s: dict) -> None:
    s["consent"] = {"text": "Consent?", "declineOutcome": "complete"}


def m_ending_unreachable(s: dict) -> None:
    s["settings"] = {"endings": {"complete": {"body": "Thanks"}, "screened_out": {"body": "No"}}}


def m_ending_declined_summary(s: dict) -> None:
    s["consent"] = {"text": "Consent?"}
    s["settings"] = {"endings": {"declined": {"summary": "answers"}}}


def m_ending_summary_ok(s: dict) -> None:
    # EN5: showing the answers is allowed for any recorded outcome.
    s["settings"] = {"endings": {"complete": {"summary": "answers"}}}


def m_ending_pipe(s: dict) -> None:
    s["settings"] = {"endings": {"complete": {"title": "${q2}", "body": "You said ${nope}"}}}


PROLIFIC = {"url": "https://app.prolific.com/submissions/complete?cc={cc}",
            "params": {"cc": {"pattern": "[A-Z0-9]{4,8}"}}}  # fmt: skip


def m_redirect_ok(s: dict) -> None:
    """A clean redirect (EN2): literal and piped params, ending built-ins, link mode."""
    s["variables"] = [{"kind": "embedded", "id": "pid", "param": "PROLIFIC_PID"}]
    s["settings"] = {
        "redirectTemplates": {
            "prolific": PROLIFIC,
            "lab": {"url": "https://lab.example.org/done/{sid}?o={out}&p={pid}",
                    "params": {"sid": {}, "out": {}, "pid": {}}},
        },
        "endings": {"complete": {
            "body": "Your response id is ${$response.id}.",
            "redirect": {"template": "lab", "mode": "link", "label": "Back to the lab",
                         "params": {"sid": "${$session.id}", "out": "${$outcome}",
                                    "pid": "${pid}"}},
        }},
    }  # fmt: skip


def m_redirect_template(s: dict) -> None:
    s["settings"] = {"redirectTemplates": {
        "http": {"url": "http://x.org/done/{code}", "params": {"code": {}}},
        "origin": {"url": "https://{host}/done", "params": {"host": {}}},
        "scheme": {"url": "javascript:alert(1)//{code}", "params": {"code": {}}},
        "bare": {"url": "https://x.org", "params": {}},
    }}  # fmt: skip


def m_redirect_clash(s: dict) -> None:
    s["hooks"] = _hooks(redirects={"done": PROLIFIC})
    s["settings"] = {"redirectTemplates": {"done": PROLIFIC}}


def m_redirect_unknown_template(s: dict) -> None:
    s["settings"] = {"endings": {"complete": {"redirect": {"template": "nope"}}}}


def m_redirect_params(s: dict) -> None:
    s["settings"] = {
        "redirectTemplates": {"prolific": PROLIFIC},
        "endings": {"complete": {"redirect": {"template": "prolific",
                                              "params": {"cc": "C1AB2", "extra": "x"}}}},
    }  # fmt: skip


def m_redirect_param_literal(s: dict) -> None:
    s["settings"] = {
        "redirectTemplates": {"prolific": PROLIFIC},
        "endings": {"complete": {"redirect": {"template": "prolific",
                                              "params": {"cc": "../evil"}}}},
    }  # fmt: skip


def m_redirect_param_question(s: dict) -> None:
    s["settings"] = {
        "redirectTemplates": {"prolific": PROLIFIC},
        "endings": {"complete": {"redirect": {"template": "prolific",
                                              "params": {"cc": "${q1}"}}}},
    }  # fmt: skip


def m_redirect_param_unknown(s: dict) -> None:
    s["settings"] = {
        "redirectTemplates": {"prolific": PROLIFIC},
        "endings": {"complete": {"redirect": {"template": "prolific",
                                              "params": {"cc": "${nope}"}}}},
    }  # fmt: skip


def m_redirect_declined_response_id(s: dict) -> None:
    s["consent"] = {"text": "Consent?"}
    s["settings"] = {
        "redirectTemplates": {"prolific": PROLIFIC},
        "endings": {"declined": {"redirect": {"template": "prolific",
                                              "params": {"cc": "${$response.id}"}}}},
    }  # fmt: skip


def m_redirect_immediate(s: dict) -> None:
    s["settings"] = {
        "redirectTemplates": {"prolific": PROLIFIC},
        "endings": {"complete": {"body": "Unseen", "redirect": {
            "template": "prolific", "delay": 0, "params": {"cc": "C1AB2"}}}},
    }  # fmt: skip


def m_redirect_builtins_elsewhere(s: dict) -> None:
    """The ending built-ins are not available on pages."""
    _items(s)[0]["label"] = "Id ${$response.id}"


# --- External task step (task EX2) -----------------------------------------------------
JSPSYCH = {"url": "https://run.pavlovia.org/lab/exp?pid={pid}", "params": {"pid": {}}}


def _external(s: dict, node: dict, template: dict | None = JSPSYCH) -> None:
    if template is not None:
        s.setdefault("settings", {})["redirectTemplates"] = {"task": template}
    s["flow"].append({"type": "externalTask", "id": "et1", **node})


def m_external_unknown_template(s: dict) -> None:
    _external(s, {"template": "nope", "params": {}}, template=None)


def m_external_params(s: dict) -> None:
    _external(s, {"template": "task", "params": {}})


def m_external_param_literal(s: dict) -> None:
    _external(s, {"template": "task", "params": {"pid": "bad value"}})


def m_external_param_question(s: dict) -> None:
    _external(s, {"template": "task", "params": {"pid": "${q1}"}})


def m_external_reserved(s: dict) -> None:
    tmpl = {"url": "https://run.pavlovia.org/e?t={osp_token}", "params": {"osp_token": {}}}
    _external(s, {"template": "task", "params": {"osp_token": "x"}}, template=tmpl)


def m_external_return_target(s: dict) -> None:
    _external(s, {"template": "task", "params": {"pid": "p"}, "returns": ["q1"]})


def _matrix(rows: list[dict] | None = None) -> dict:
    rows = rows if rows is not None else [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]
    return {"id": "m", "type": "matrix", "label": "M", "rows": rows,
            "choices": [{"value": 1, "label": "Yes"}, {"value": 2, "label": "No"}]}  # fmt: skip


def m_matrix_duplicate_row(s):
    _items(s)[1] = _matrix([{"id": "a", "label": "A"}, {"id": "a", "label": "A again"}])


def m_matrix_row_id(s):
    _items(s)[1] = _matrix([{"id": "r" * 63, "label": "Long"}])


def m_matrix_row_clash(s):
    _items(s)[0]["id"] = "m_a"  # the id of row `a` of matrix `m`
    _items(s)[1] = _matrix()


def m_matrix_ref(s):
    _items(s)[0]["showIf"] = answered("m")
    _items(s)[1] = _matrix()


def _hooks(**extra: Any) -> dict:
    return {"format": "osp-hooks/1", "source": "osp.on('onStart', function () {});",
            "handlers": {"onStart": {"reads": ["q1"], "writes": []}}, **extra}  # fmt: skip


def m_hooks_unknown_ref(s):
    s["hooks"] = _hooks()
    s["hooks"]["handlers"]["onPageNext"] = {"reads": ["q1", "nope"], "writes": []}


def m_hooks_read_matrix(s):
    _items(s)[1] = _matrix()  # a matrix has no value of its own: read its rows
    s["hooks"] = _hooks()
    s["hooks"]["handlers"]["onStart"]["reads"] = ["m", "m_a"]


def m_hooks_write_target(s):
    s["hooks"] = _hooks()
    s["hooks"]["handlers"]["onStart"]["writes"] = ["q2"]


def m_hooks_write_on_submitted(s):
    s["hooks"] = _hooks()
    s["hooks"]["handlers"]["onSubmitted"] = {"reads": [], "writes": ["q2"]}


def m_hooks_redirect(s):
    s["hooks"] = _hooks(redirects={
        "ok": {"url": "https://x.org/done/{code}", "params": {"code": {}}},
        "http": {"url": "http://x.org/done/{code}", "params": {"code": {}}},
        "origin": {"url": "https://{host}/done", "params": {"host": {}}},
        "dup": {"url": "https://x.org/{a}/{a}", "params": {"a": {}}},
        "params": {"url": "https://x.org/{a}", "params": {"b": {}}},
        "pattern": {"url": "https://x.org/{a}", "params": {"a": {"pattern": "("}}},
        "bare": {"url": "https://x.org", "params": {}},
        "junk": {"url": "not a url", "params": {}},
    })  # fmt: skip


def m_hooks_parent_origin(s):
    s["hooks"] = _hooks(parent={"origin": "https://x.org/", "messages": {}})


def m_slider_range(s):
    _items(s)[1] = {"id": "q2", "type": "slider", "label": "S", "min": 5, "max": 5}


def m_slider_grid(s):
    _items(s)[1] = {"id": "q2", "type": "slider", "label": "S", "min": 0, "max": 10, "step": 3}


def m_slider_integer_step(s):
    _items(s)[1] = {"id": "q2", "type": "slider", "label": "S", "max": 10, "step": "0.5"}


TABLE: list[tuple[Callable[[dict], None], list[tuple[str, str]]]] = [
    (m_lang_dup, [("lang.duplicate", "/metadata/languages/1")]),
    (m_lang_default, [("lang.unknown_default", "/metadata/defaultLanguage")]),
    (m_case_collision, [("name.case_collision", f"{P0}/1/name")]),
    (m_mixed, [("choice.mixed_types", f"{P0}/0/choices")]),
    (m_unused_list, [("choicelist.unused", "/choiceLists/0")]),
    (m_unknown_var, [("ref.unknown_variable", "/flow/1/variables/0")]),
    (m_not_in_flow, [("block.unused", "/blocks/1"), ("ref.not_in_flow", f"{P0}/0/showIf")]),
    (m_other_branch, [("ref.other_branch", "/blocks/2/pages/0/items/0/showIf")]),
    (m_pipe_invalid, [("pipe.invalid", f"{P0}/1/label")]),
    (m_flow_empty, [("flow.empty", "/flow"), ("block.unused", "/blocks/0")]),
    (m_empty_branch, [("flow.empty_branch", "/flow/1/then")]),
    (m_reassigned, [("flow.variable_reassigned", "/flow/2/variables/0")]),
    (m_never_assigned, [("variable.never_assigned", "/variables/0")]),
    (m_dup_level, [("variable.duplicate_level", "/variables/0/levels/1")]),
    (m_default_type, [("variable.default_type", "/variables/0/default")]),
    (m_block_unused, [("block.unused", "/blocks/1")]),
    (m_quota_unused, [("quota.unused", "/quotas/0")]),
    (m_quota_block, [("ref.unknown_block", "/quotas/0/onFull/block")]),
    (m_schema_value, [("schema.value", "/metadata/languages")]),
    (m_reserved_suffix, [("name.reserved", f"{P0}/0/name")]),
    (m_reserved_prefix, [("name.reserved", f"{P0}/0/name")]),
    (m_quota_forward, [("ref.forward", "/quotas/0/when")]),
    (m_same_page_cycle, [("ref.cycle", f"{P0}/0/showIf")]),
    (m_bounds, [("question.bounds", f"{P0}/0/min")]),
    (m_decimal_bound_too_long, [("question.bounds", f"{P0}/1/max")]),
    (m_retention, [("settings.retention", "/settings/retention")]),
    (m_page_showif_own_item, [("ref.forward", "/blocks/0/pages/0/showIf")]),
    (m_consent_pipe, [("consent.pipe", "/consent/agreeLabel")]),
    (m_consent_outcome, [("consent.outcome", "/consent/declineOutcome")]),
    (m_ending_unreachable, [("ending.unreachable", "/settings/endings/screened_out")]),
    (
        m_ending_declined_summary,
        [("ending.declined_summary", "/settings/endings/declined/summary")],
    ),
    (m_ending_summary_ok, []),
    (m_ending_pipe, [("ref.unknown", "/settings/endings/complete/body")]),
    (m_redirect_ok, []),
    (
        m_redirect_template,
        [
            ("redirect.template", f"/settings/redirectTemplates/{k}")
            for k in ("http", "origin", "scheme", "bare")
        ],
    ),  # fmt: skip
    (m_redirect_clash, [("redirect.template_clash", "/settings/redirectTemplates/done")]),
    (
        m_redirect_unknown_template,
        [("redirect.unknown_template", "/settings/endings/complete/redirect/template")],
    ),
    (m_redirect_params, [("redirect.params", "/settings/endings/complete/redirect/params")]),
    (
        m_redirect_param_literal,
        [("redirect.param_literal", "/settings/endings/complete/redirect/params/cc")],
    ),
    (
        m_redirect_param_question,
        [("redirect.param_question", "/settings/endings/complete/redirect/params/cc")],
    ),
    (m_redirect_param_unknown, [("ref.unknown", "/settings/endings/complete/redirect/params/cc")]),
    (
        m_redirect_declined_response_id,
        [("redirect.params", "/settings/endings/declined/redirect/params/cc")],
    ),
    (m_redirect_immediate, [("redirect.immediate", "/settings/endings/complete/redirect/delay")]),
    (m_redirect_builtins_elsewhere, [("pipe.invalid", f"{P0}/0/label")]),
    (m_external_unknown_template, [("external.unknown_template", "/flow/1/template")]),
    (m_external_params, [("external.params", "/flow/1/params")]),
    (m_external_param_literal, [("external.param_literal", "/flow/1/params/pid")]),
    (m_external_param_question, [("external.param_question", "/flow/1/params/pid")]),
    (m_external_reserved, [("external.reserved_param", "/flow/1/template")]),
    (m_external_return_target, [("external.return_target", "/flow/1/returns/0")]),
    (m_matrix_duplicate_row, [("matrix.duplicate_row", f"{P0}/1/rows/1/id")]),
    (m_matrix_row_id, [("matrix.row_id", f"{P0}/1/rows/0/id")]),
    (m_matrix_row_clash, [("id.duplicate", f"{P0}/1/rows/0/id")]),
    (m_matrix_ref, [("ref.no_value", f"{P0}/0/showIf")]),
    (m_slider_range, [("question.slider", f"{P0}/1/min")]),
    (m_slider_grid, [("question.slider", f"{P0}/1/step")]),
    (m_slider_integer_step, [("question.slider", f"{P0}/1/step")]),
    (m_hooks_unknown_ref, [("hooks.unknown_ref", "/hooks/handlers/onPageNext/reads/1")]),
    (m_hooks_read_matrix, [("hooks.unknown_ref", "/hooks/handlers/onStart/reads/0")]),
    (m_hooks_write_target, [("hooks.write_target", "/hooks/handlers/onStart/writes/0")]),
    (m_hooks_write_on_submitted, [("hooks.write_target", "/hooks/handlers/onSubmitted/writes/0")]),
    (
        m_hooks_redirect,
        [
            ("hooks.redirect", f"/hooks/redirects/{k}")
            for k in ("http", "origin", "dup", "params", "pattern", "bare", "junk")
        ],
    ),  # fmt: skip
    (m_hooks_parent_origin, [("hooks.parent_origin", "/hooks/parent/origin")]),
]


@pytest.mark.parametrize(("mutate", "expected"), TABLE, ids=[m.__name__ for m, _ in TABLE])
def test_code(mutate: Callable[[dict], None], expected: list[tuple[str, str]]) -> None:
    s = base()
    mutate(s)
    got = sorted((d.code, d.pointer) for d in validate(s))
    assert got == sorted(expected)


def test_base_is_clean() -> None:
    assert validate(base()) == []


def test_every_code_is_exercised() -> None:
    covered = {code for _, exp in TABLE for code, _ in exp}
    for path in CASES.glob("*/*.json"):
        covered |= {e["code"] for e in json.loads(path.read_text(encoding="utf-8"))["expect"]}
    covered.add("publish.retention_required")  # test_publish_needs_a_retention_policy
    covered.add("publish.consent_missing")  # test_publish_warns_without_consent
    assert covered <= set(CODES)
    assert set(CODES) - covered == UNTESTABLE


def test_same_page_references_go_either_way() -> None:
    s = base()
    _items(s)[0]["showIf"] = gt("q2", 1)  # a later item on the same page (C2-1)
    _items(s)[1]["label"] = "You said ${q1}"
    assert validate(s) == []


def test_builtin_pipes_are_valid() -> None:
    s = base()
    _items(s)[0]["label"] = "Trial ${$trial}, ${$position.index} of ${$position.of}"
    assert validate(s) == []


def test_case_collision_is_an_error() -> None:
    assert CODES["name.case_collision"] == "error"


def test_publish_needs_a_retention_policy() -> None:
    s = base()
    errors = [d for d in publish_diagnostics(s) if d.severity == "error"]
    assert [d.code for d in errors] == ["publish.retention_required"]
    s["settings"] = {"retention": {"kind": "days-after-close", "days": 365}}
    assert [d for d in publish_diagnostics(s) if d.severity == "error"] == []
    s["settings"] = {"retention": {"kind": "indefinite"}}
    assert [d for d in publish_diagnostics(s) if d.severity == "error"] == [] == validate(s)


def test_reserved_names_include_the_obvious_ones() -> None:
    assert {"seed", "id", "token", "submitdate", "instanceid"} <= RESERVED_NAMES


def test_validator_does_not_mutate_input() -> None:
    s = base()
    before = copy.deepcopy(s)
    validate(s)
    assert s == before


def test_publish_warns_without_consent() -> None:
    s = base()
    s["settings"] = {"retention": {"kind": "indefinite"}}
    got = publish_diagnostics(s)
    assert [(d.code, d.severity, d.pointer) for d in got] == [
        ("publish.consent_missing", "warning", "/consent")
    ]
    s["consent"] = {"text": "Do you agree?"}
    assert publish_diagnostics(s) == []
