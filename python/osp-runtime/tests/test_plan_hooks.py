"""Hook manifests in the runtime plan (runtime-design.md §7a) and the `multiline` item flag.

Plans are checked against contract/runtime-plan.schema.json with a small validator for the
JSON Schema keywords that file uses (no jsonschema dependency in the workspace; the engine
checks the same file with Ajv in web/engine/test/schema.test.ts).
"""

from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path
from typing import Any

import pytest
from osp_runtime.plan import PlanError, checksum, compile_plan, compile_survey, hooks_problem
from osp_spec import parse

REPO = Path(__file__).resolve().parents[3]
SCHEMA = json.loads((REPO / "contract" / "runtime-plan.schema.json").read_text())
VALID = sorted((REPO / "python/osp-spec/tests/cases/valid").glob("*.json"))
FIXTURES = sorted((REPO / "fixtures").glob("*/survey.json"))
WORKED = VALID[0]

# --- A validator for the keywords runtime-plan.schema.json uses ------------------------

_KNOWN = {
    "$schema", "$id", "$defs", "$ref", "title", "description", "type", "enum", "const",
    "properties", "additionalProperties", "required", "propertyNames", "dependentSchemas",
    "items", "minItems", "minLength", "minimum", "maximum", "pattern",
    "anyOf", "allOf", "oneOf", "not", "if", "then", "else",
}  # fmt: skip


def _type_ok(t: str, v: Any) -> bool:
    match t:
        case "object":
            return isinstance(v, dict)
        case "array":
            return isinstance(v, list)
        case "string":
            return isinstance(v, str)
        case "boolean":
            return isinstance(v, bool)
        case "null":
            return v is None
        case "integer":
            return isinstance(v, int) and not isinstance(v, bool)
        case "number":
            return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)
    raise AssertionError(f"unknown type {t}")


def _eq(a: Any, b: Any) -> bool:
    return type(a) is type(b) and a == b if isinstance(a, bool) or isinstance(b, bool) else a == b


def valid(s: Any, v: Any, root: dict = SCHEMA) -> bool:  # noqa: C901, PLR0911, PLR0912
    if s is True:
        return True
    if s is False:
        return False
    assert not set(s) - _KNOWN, set(s) - _KNOWN
    if "$ref" in s:
        target: Any = root
        for part in s["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        if not valid(target, v, root):
            return False
    if "type" in s:
        types = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(_type_ok(t, v) for t in types):
            return False
    if "const" in s and not _eq(s["const"], v):
        return False
    if "enum" in s and not any(_eq(e, v) for e in s["enum"]):
        return False
    if isinstance(v, str):
        if len(v) < s.get("minLength", 0):
            return False
        if "pattern" in s and not re.search(s["pattern"], v):
            return False
    if isinstance(v, int | float) and not isinstance(v, bool):
        if "minimum" in s and v < s["minimum"]:
            return False
        if "maximum" in s and v > s["maximum"]:
            return False
    if isinstance(v, list):
        if len(v) < s.get("minItems", 0):
            return False
        if "items" in s and not all(valid(s["items"], x, root) for x in v):
            return False
    if isinstance(v, dict):
        if not all(k in v for k in s.get("required", [])):
            return False
        props = s.get("properties", {})
        for k, x in v.items():
            if "propertyNames" in s and not valid(s["propertyNames"], k, root):
                return False
            if k in props:
                if not valid(props[k], x, root):
                    return False
            elif "additionalProperties" in s and not valid(s["additionalProperties"], x, root):
                return False
        for k, dep in s.get("dependentSchemas", {}).items():
            if k in v and not valid(dep, v, root):
                return False
    if "anyOf" in s and not any(valid(x, v, root) for x in s["anyOf"]):
        return False
    if "allOf" in s and not all(valid(x, v, root) for x in s["allOf"]):
        return False
    if "oneOf" in s and sum(valid(x, v, root) for x in s["oneOf"]) != 1:
        return False
    if "not" in s and valid(s["not"], v, root):
        return False
    if "if" in s:
        branch = "then" if valid(s["if"], v, root) else "else"
        if branch in s and not valid(s[branch], v, root):
            return False
    return True


def test_validator_rejects_what_it_should() -> None:
    plan, _ = compile_survey(_survey(WORKED))
    assert valid(SCHEMA, plan)
    assert not valid(SCHEMA, {**plan, "planVersion": "osp-runtime-plan/2"})
    assert not valid(SCHEMA, {**plan, "extra": 1})
    bad_item = {"id": "a", "type": "note", "page": "p1", "label": {}, "required": True}
    assert not valid(SCHEMA, {**plan, "items": {"a": bad_item}})


# --- Fixtures --------------------------------------------------------------------------


def _survey(path: Path) -> Any:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("survey", data)


HOOKS: dict[str, Any] = {
    "format": "osp-hooks/1",
    "source": "osp.on('onPageNext', (ctx) => ({ vars: {} }));",
    "handlers": {
        "onPageNext": {"reads": ["age"], "writes": [], "timeoutMs": 1500},
        "onSubmitted": {"reads": [], "writes": []},
    },
    "urlParams": ["PROLIFIC_PID"],
    "redirects": {
        "done": {
            "url": "https://example.org/complete/{code}",
            "params": {"code": {"pattern": "[A-Z0-9]{6}"}},
        }
    },
    "parent": {
        "origin": "https://example.org",
        "messages": {
            "progress": {
                "type": "object",
                "properties": {
                    "page": {"type": "integer", "minimum": 0},
                    "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                },
                "required": ["page"],
            }
        },
    },
    "exportsConfirmedFor": None,
}


# --- multiline -------------------------------------------------------------------------


def test_multiline_only_on_set_text_items() -> None:
    plan, diags = compile_survey(_survey(REPO / "fixtures/04-text-whitespace/survey.json"))
    assert plan is not None, diags
    flagged = {i for i, item in plan["items"].items() if "multiline" in item}
    assert flagged == {"t_lines"}
    assert plan["items"]["t_lines"]["multiline"] is True
    assert valid(SCHEMA, plan)
    # A multiline flag on a non-text item does not validate.
    broken = copy.deepcopy(plan)
    broken["items"]["t_lines"]["type"] = "integer"
    assert not valid(SCHEMA, broken)
    broken["items"]["t_lines"]["type"] = "text"
    broken["items"]["t_lines"]["multiline"] = False  # `true` or absent
    assert not valid(SCHEMA, broken)


def test_multiline_false_is_not_emitted() -> None:
    data = _survey(REPO / "fixtures/04-text-whitespace/survey.json")
    explicit = copy.deepcopy(data)
    for item in _items(explicit):
        if item["id"] == "t_lines":
            item["multiline"] = False
    stripped = copy.deepcopy(explicit)
    for item in _items(stripped):
        item.pop("multiline", None)
    a, _ = compile_survey(explicit)
    b, _ = compile_survey(stripped)
    assert a == b and "multiline" not in a["items"]["t_lines"]


def _items(survey: dict) -> list[dict]:
    return [i for b in survey["blocks"] for p in b["pages"] for i in p["items"]]


@pytest.mark.parametrize("path", [*VALID, *FIXTURES], ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_every_plan_validates_against_the_contract(path: Path) -> None:
    survey = _survey(path)
    plan, diags = compile_survey(survey)
    if plan is None:
        pytest.skip(f"does not compile: {[d.code for d in diags]}")
    assert ("hooks" in plan) == ("hooks" in survey)
    assert valid(SCHEMA, plan)


# --- hooks -----------------------------------------------------------------------------


def test_plan_without_hooks_is_unchanged() -> None:
    data = _survey(WORKED)
    a, _ = compile_survey(data)
    b, _ = compile_survey(data, hooks=None)
    survey, _ = parse(data)
    assert survey is not None
    c = compile_plan(survey)
    assert a == b == c
    assert "hooks" not in a
    assert a["checksum"] == checksum(a)


def test_hooks_are_copied_into_the_plan_and_the_checksum() -> None:
    data = _survey(WORKED)
    without, _ = compile_survey(data)
    hooks = copy.deepcopy(HOOKS)
    plan, diags = compile_survey(data, hooks=hooks)
    assert plan is not None, diags
    assert plan["hooks"] == HOOKS
    assert plan["hooks"] is not hooks  # a copy: later edits to the input don't leak in
    assert plan["checksum"] == checksum(plan) != without["checksum"]
    assert {k: v for k, v in plan.items() if k not in ("hooks", "checksum")} == {
        k: v for k, v in without.items() if k != "checksum"
    }
    survey, _ = parse(data)
    assert survey is not None
    assert compile_plan(survey, hooks=hooks) == plan
    # Any change to the manifest changes the checksum.
    edited = copy.deepcopy(HOOKS)
    edited["source"] += "\n"
    other, _ = compile_survey(data, hooks=edited)
    assert other["checksum"] != plan["checksum"]


def test_plan_with_hooks_validates_against_the_contract() -> None:
    plan, _ = compile_survey(_survey(WORKED), hooks=HOOKS)
    assert valid(SCHEMA, plan)
    minimal = {"format": "osp-hooks/1", "source": "", "handlers": {}}
    plan2, _ = compile_survey(_survey(WORKED), hooks=minimal)
    assert valid(SCHEMA, plan2)
    assert not valid(SCHEMA, {**plan2, "hooks": {**minimal, "handlers": {"onNope": {}}}})


def _with(path: list[str | int], value: Any) -> dict:
    h = copy.deepcopy(HOOKS)
    target: Any = h
    for p in path[:-1]:
        target = target[p]
    target[path[-1]] = value
    return h


def _without(key: str) -> dict:
    h = copy.deepcopy(HOOKS)
    del h[key]
    return h


MALFORMED: list[tuple[str, Any]] = [
    ("not an object", []),
    ("string", "osp.on()"),
    ("unknown key", {**HOOKS, "extra": 1}),
    ("wrong format", _with(["format"], "osp-hooks/2")),
    ("no source", _without("source")),
    ("source not text", _with(["source"], 5)),
    ("huge source", _with(["source"], "x" * (256 * 1024 + 1))),
    ("no handlers", _without("handlers")),
    ("handlers list", _with(["handlers"], [])),
    ("unknown event", _with(["handlers", "onExplode"], {"reads": [], "writes": []})),
    ("handler not object", _with(["handlers", "onStart"], None)),
    ("reads missing", _with(["handlers", "onStart"], {"writes": []})),
    ("reads not ids", _with(["handlers", "onStart"], {"reads": [1], "writes": []})),
    ("extra handler key", _with(["handlers", "onStart"], {"reads": [], "writes": [], "x": 1})),
    ("timeout zero", _with(["handlers", "onPageNext", "timeoutMs"], 0)),
    ("timeout too big", _with(["handlers", "onPageNext", "timeoutMs"], 5001)),
    ("timeout bool", _with(["handlers", "onPageNext", "timeoutMs"], True)),
    ("timeout float", _with(["handlers", "onPageNext", "timeoutMs"], 1.5)),
    ("urlParams str", _with(["urlParams"], "PID")),
    ("redirect no params", _with(["redirects", "done"], {"url": "https://x.org/a"})),
    ("redirect pattern int", _with(["redirects", "done", "params", "code"], {"pattern": 1})),
    ("parent str", _with(["parent"], "https://example.org")),
    ("parent no messages", _with(["parent"], {"origin": "https://example.org"})),
    ("payload bad type", _with(["parent", "messages", "progress"], {"type": "date"})),
    ("payload extra key", _with(["parent", "messages", "progress"], {"type": "null", "x": 1})),
    ("array no maxItems", _with(["parent", "messages", "progress"], {"type": "array",
                                                                    "items": {"type": "null"}})),
    ("payload too deep", _with(["parent", "messages", "progress"], {"type": "array", "maxItems": 1,
        "items": {"type": "array", "maxItems": 1, "items": {"type": "array", "maxItems": 1,
        "items": {"type": "array", "maxItems": 1, "items": {"type": "array", "maxItems": 1,
        "items": {"type": "null"}}}}}})),
    ("confirmed int", _with(["exportsConfirmedFor"], 1)),
    ("bound not finite", _with(["parent", "messages", "progress"], {"type": "number",
                                                                    "minimum": float("nan")})),
]  # fmt: skip


@pytest.mark.parametrize("hooks", [h for _, h in MALFORMED], ids=[n for n, _ in MALFORMED])
def test_malformed_hooks_give_a_diagnostic_not_a_plan(hooks: Any) -> None:
    data = _survey(WORKED)
    assert hooks_problem(hooks) is not None
    plan, diags = compile_survey(data, hooks=hooks)
    assert plan is None
    assert [d.code for d in diags if d.severity == "error"] == ["plan.hooks_invalid"]
    assert diags[-1].pointer.startswith("/hooks")
    survey, _ = parse(data)
    assert survey is not None
    with pytest.raises(PlanError) as err:
        compile_plan(survey, hooks=hooks)
    assert [d.code for d in err.value.diagnostics] == ["plan.hooks_invalid"]


def test_hooks_problem_never_raises_on_junk() -> None:
    junk: list[Any] = [0, True, "x", 1.5, {"format": None}, {1: 2}, {"handlers": {1: 2}}]
    for h in junk:
        assert hooks_problem(h) is not None
        plan, diags = compile_survey(_survey(WORKED), hooks=h)
        assert plan is None and diags[-1].code == "plan.hooks_invalid"
    assert hooks_problem(HOOKS) is None


# --- the survey's own `hooks` field (task R11) -----------------------------------------

HOOKS_CASE = REPO / "python/osp-spec/tests/cases/valid/v12_hooks.json"


def test_the_surveys_own_hooks_are_compiled_into_the_plan() -> None:
    data = _survey(HOOKS_CASE)
    plan, diags = compile_survey(data)
    assert plan is not None, diags
    assert plan["hooks"] == {k: v for k, v in data["hooks"].items() if v is not None}
    assert "exportsConfirmedFor" not in plan["hooks"]  # null is left out for the host
    assert plan["checksum"] == checksum(plan)
    assert valid(SCHEMA, plan)
    without = dict(data)
    del without["hooks"]
    plain, _ = compile_survey(without)
    assert plain["checksum"] != plan["checksum"]
    survey, _ = parse(data)
    assert survey is not None
    assert compile_plan(survey) == plan


def test_a_manifest_given_beside_the_survey_replaces_its_own() -> None:
    data = _survey(HOOKS_CASE)
    other = {"format": "osp-hooks/1", "source": "", "handlers": {}}
    plan, _ = compile_survey(data, hooks=other)
    assert plan["hooks"] == other
    survey, _ = parse(data)
    assert compile_plan(survey, hooks=other) == plan


def test_hook_reference_errors_block_the_plan() -> None:
    data = _survey(HOOKS_CASE)
    data["hooks"]["handlers"]["onPageNext"]["reads"].append("nope")
    plan, diags = compile_survey(data)
    assert plan is None
    assert [(d.code, d.pointer) for d in diags if d.severity == "error"] == [
        ("hooks.unknown_ref", "/hooks/handlers/onPageNext/reads/2")
    ]
    # The same manifest given beside the survey is checked the same way.
    plain = _survey(HOOKS_CASE)
    bad = plain.pop("hooks")
    plan, diags = compile_survey(plain, hooks=data["hooks"])
    assert plan is None and [d.code for d in diags] == ["hooks.unknown_ref"]
    survey, _ = parse(plain)
    assert survey is not None
    with pytest.raises(PlanError) as err:
        compile_plan(survey, hooks=data["hooks"])
    assert [d.code for d in err.value.diagnostics] == ["hooks.unknown_ref"]
    assert bad is not None


def test_malformed_hooks_in_the_survey_itself_are_schema_errors() -> None:
    data = _survey(HOOKS_CASE)
    data["hooks"]["handlers"]["onExplode"] = {"reads": [], "writes": []}
    plan, diags = compile_survey(data)
    assert plan is None
    assert diags[0].code.startswith("schema.") and diags[0].pointer.startswith("/hooks/handlers")
