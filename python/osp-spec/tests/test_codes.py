"""Small targeted checks for diagnostic codes the fixture cases don't cover, plus a guard
that every registered code is exercised somewhere."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from osp_spec import CODES, RESERVED_NAMES, validate

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


def m_quota_forward(s):
    _add_block(s, "b2", "q3")
    s["quotas"] = [{"id": "qt", "when": answered("q3"), "limit": 5,
                    "onFull": {"outcome": "quotafull"}}]  # fmt: skip
    s["flow"] = [{"type": "block", "id": "f1", "block": "b1"},
                 {"type": "quotaCheck", "id": "f2", "quota": "qt"},
                 {"type": "block", "id": "f3", "block": "b2"}]  # fmt: skip


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
    assert covered <= set(CODES)
    assert set(CODES) - covered == UNTESTABLE


def test_reserved_names_include_the_obvious_ones() -> None:
    assert {"seed", "id", "token", "submitdate", "instanceid"} <= RESERVED_NAMES


def test_validator_does_not_mutate_input() -> None:
    s = base()
    before = copy.deepcopy(s)
    validate(s)
    assert s == before
