"""Property panel profiles (task B21): validation, applying a profile to the stock schemas,
checking a survey's custom values, and fuzzing (never an exception)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from osp_spec import parse
from osp_spec.model import MAX_CUSTOM_PROPERTIES
from osp_spec.panel_profile import (
    CUSTOM_PREFIX,
    PROFILE_CODES,
    PanelProfile,
    apply_profile,
    check_custom_values,
    effective_defaults,
    fits,
    profile_schemas_json,
    validate_profile,
)
from osp_spec.property_schema import property_schemas, property_schemas_json

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "01-all-types" / "survey.json"

PROFILE: dict[str, Any] = {
    "hidden": ["*.constraintMessage", "single.choiceOrder"],
    "order": {"*": ["required", "label"], "text": ["multiline", "label"]},
    "groups": {"Logic": {"en": "Conditions"}},
    "defaults": {"single": {"required": True}, "text": {"multiline": True}},
    "custom": [
        {"key": "construct", "kind": "text", "label": {"en": "Construct"}, "group": "Basics"},
        {
            "key": "weight",
            "kind": "number",
            "label": {"en": "Weight"},
            "default": 1,
            "types": ["single", "multi", "slider"],
        },
        {"key": "prereg", "kind": "bool", "label": {"en": "Pre-registered"}, "required": True},
        {
            "key": "scale",
            "kind": "choice",
            "label": {"en": "Scale"},
            "options": [
                {"value": "likert", "label": {"en": "Likert"}},
                {"value": "vas", "label": {"en": "Visual analogue"}},
            ],
        },
    ],
}


def codes(diags: list) -> list[str]:
    return [d.code for d in diags]


def profile(**changes: Any) -> PanelProfile:
    p, diags = validate_profile({**copy.deepcopy(PROFILE), **changes})
    assert p is not None, diags
    return p


def keys(schemas: dict, type_: str) -> list[str]:
    return list(schemas[type_].properties)


# --- Validation -------------------------------------------------------------------------


def test_profile_validates_and_defaults_are_filled() -> None:
    p = profile()
    assert p.profileVersion == "osp-panel-profile/0.1"
    assert p.custom[0].group == "Basics" and p.custom[3].group == "Advanced"
    assert p.custom[1].applies_to("single") and not p.custom[1].applies_to("text")
    assert p.custom[0].applies_to("note")
    empty, diags = validate_profile({})
    assert empty == PanelProfile() and diags == []


@pytest.mark.parametrize(
    ("data", "where"),
    [
        ({"hidden": ["label"]}, "/hidden/0"),  # no type
        ({"hidden": "label"}, "/hidden"),
        ({"order": {"*": ["bad key"]}}, "/order/*/0"),
        ({"groups": {"Nope": {"en": "x"}}}, "/groups/Nope/[key]"),
        ({"custom": [{"key": "Bad", "kind": "text", "label": "x"}]}, "/custom/0/key"),
        ({"custom": [{"key": "k", "kind": "colour", "label": "x"}]}, "/custom/0/kind"),
        ({"custom": [{"key": "k", "kind": "choice", "label": "x"}]}, "/custom/0"),  # no options
        (
            {"custom": [{"key": "k", "kind": "text", "label": "x", "options": []}]},
            "/custom/0/options",
        ),
        ({"custom": [{"key": "k", "kind": "number", "label": "x", "default": "1"}]}, "/custom/0"),
        ({"custom": [{"key": "k", "kind": "bool", "label": "x", "default": 1}]}, "/custom/0"),
        (
            {"custom": [{"key": "k", "kind": "text", "label": "x", "types": ["text", "text"]}]},
            "/custom/0",
        ),
        (
            {
                "custom": [
                    {"key": "k", "kind": "text", "label": "x"},
                    {"key": "k", "kind": "bool", "label": "y"},
                ]
            },
            "",
        ),
        ({"custom": [{"key": "k", "kind": "text", "label": "x", "extra": 1}]}, "/custom/0/extra"),
        ({"profileVersion": "osp-panel-profile/9"}, "/profileVersion"),
        ("not an object", ""),
        (None, ""),
    ],
)
def test_bad_profiles_are_schema_diagnostics(data: Any, where: str) -> None:
    p, diags = validate_profile(data)
    assert p is None and diags
    assert {d.code for d in diags} == {"profile.schema"}
    assert any(d.pointer == where for d in diags), [d.pointer for d in diags]


def test_choice_default_must_be_an_option_of_the_same_type() -> None:
    base = {"key": "k", "kind": "choice", "label": "x", "options": [{"value": 1, "label": "One"}]}
    assert validate_profile({"custom": [{**base, "default": 1}]})[0] is not None
    assert validate_profile({"custom": [{**base, "default": "1"}]})[0] is None
    assert validate_profile({"custom": [{**base, "default": 2}]})[0] is None


def test_fits_is_strict_about_kinds() -> None:
    p = profile()
    text, number, boolean, choice = p.custom
    assert fits(text, "x") and not fits(text, 1)
    assert fits(number, 1) and fits(number, 2.5) and not fits(number, True)
    assert not fits(number, "1")
    assert fits(boolean, False) and not fits(boolean, 0)
    assert fits(choice, "vas") and not fits(choice, "other") and not fits(choice, 1)


# --- Applying ---------------------------------------------------------------------------


def test_apply_hides_orders_defaults_and_adds_custom_properties() -> None:
    schemas, diags = apply_profile(profile())
    assert diags == []
    stock = property_schemas()
    # Hidden: "*" hides on every type that has the key; a typed ref on that type only.
    assert "constraintMessage" not in keys(schemas, "single")
    assert "constraintMessage" not in keys(schemas, "integer")
    assert "choiceOrder" not in keys(schemas, "single")
    assert "choiceOrder" in keys(schemas, "multi")
    # Order: the listed keys first, then the stock order; a typed entry wins over "*".
    single = keys(schemas, "single")
    assert single[:2] == ["required", "label"]
    rest = [k for k in stock["single"].properties if k not in ("required", "label", "choiceOrder")]
    assert [k for k in single if not k.startswith(CUSTOM_PREFIX)][2:] == [
        k for k in rest if k != "constraintMessage"
    ]
    assert keys(schemas, "text")[:2] == ["multiline", "label"]
    # Defaults: replaced for new questions.
    assert schemas["single"].properties["required"].default is True
    assert schemas["text"].properties["multiline"].default is True
    assert schemas["multi"].properties["required"].default is False
    # Custom: `custom.<key>` entries on the types they apply to, with the mapped editor.
    assert schemas["single"].properties["custom.weight"].kind == "number"
    assert "custom.weight" not in keys(schemas, "text")
    assert schemas["note"].properties["custom.construct"].group == "Basics"
    scale = schemas["date"].properties["custom.scale"]
    assert scale.kind == "enum" and [o.value for o in scale.options or []] == ["likert", "vas"]
    assert schemas["integer"].properties["custom.prereg"].required is True
    # Pages, blocks and the survey are untouched by custom properties.
    assert not any(k.startswith(CUSTOM_PREFIX) for k in keys(schemas, "page"))
    # The stock schemas were not mutated.
    assert "constraintMessage" in stock["single"].properties
    assert stock["single"].properties["required"].default is False


def test_problems_are_diagnostics_and_the_stock_schema_stands_in() -> None:
    p = profile(
        hidden=["*.label", "single.nope", "nope.label", "*.nope"],
        order={"single": ["nope", "help"], "nope": ["label"]},
        defaults={"single": {"required": "yes", "nope": 1}, "nope": {"label": "x"}, "page": {}},
        custom=[{"key": "label", "kind": "text", "label": "x"}],
    )
    schemas, diags = apply_profile(p)
    seen = {(d.code, d.pointer) for d in diags}
    assert ("profile.required_hidden", "/hidden/0") in seen
    assert "label" in keys(schemas, "single")
    assert ("profile.unknown_key", "/hidden/1") in seen
    assert ("profile.unknown_type", "/hidden/2") in seen
    assert codes(diags).count("profile.unknown_type") == 4  # hidden, order, defaults, page
    assert ("profile.unknown_key", "/order/single/0") in seen
    assert keys(schemas, "single")[0] == "help"
    assert ("profile.bad_default", "/defaults/single/required") in seen
    assert ("profile.unknown_key", "/defaults/single/nope") in seen
    assert schemas["single"].properties["required"].default is False
    assert ("profile.key_clash", "/custom/0/key") in seen
    assert "custom.label" not in keys(schemas, "single")
    assert all(d.severity != "error" for d in diags)
    assert {d.code for d in diags} <= set(PROFILE_CODES)


def test_star_hidden_skips_types_without_the_key_silently() -> None:
    schemas, diags = apply_profile(profile(hidden=["*.multiline"]))
    assert diags == [] and "multiline" not in keys(schemas, "text")


def test_effective_defaults_include_custom_defaults() -> None:
    d = effective_defaults(profile())
    assert d["single"] == {"required": True, "custom.weight": 1}
    assert d["text"] == {"multiline": True}
    assert "note" not in d
    # Hidden + default: the value is still applied to new questions.
    d = effective_defaults(profile(hidden=["*.required"], defaults={"single": {"required": True}}))
    assert d["single"]["required"] is True


def test_profile_schemas_json_has_the_stock_shape_plus_profile_fields() -> None:
    stock = profile_schemas_json(None)
    plain = property_schemas_json()
    assert stock["schemas"] == plain["schemas"]
    assert stock["groupLabels"] == {} and stock["defaults"] == {}
    assert stock["profileApplied"] is False and stock["diagnostics"] == []
    doc = profile_schemas_json(profile())
    assert doc["profileApplied"] is True
    assert doc["groupLabels"] == {"Logic": {"en": "Conditions"}}
    assert doc["defaults"]["single"] == {"required": True, "custom.weight": 1}
    single = next(s for s in doc["schemas"] if s["type"] == "single")
    assert "custom.scale" in single["properties"]
    json.dumps(doc)  # JSON-ready


# --- Checking a survey ------------------------------------------------------------------


def survey_with(custom: dict[str, dict[str, Any]]) -> dict[str, Any]:
    s = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for b in s["blocks"]:
        for pg in b["pages"]:
            for q in pg["items"]:
                if q["id"] in custom:
                    q["custom"] = custom[q["id"]]
    return s


def test_custom_values_are_part_of_the_model() -> None:
    s = survey_with({"n_int": {"construct": "tea", "weight": 2.5, "prereg": True}})
    model, diags = parse(s)
    assert model is not None and diags == []
    assert parse(survey_with({"n_int": {"Bad": 1}}))[0] is None
    assert parse(survey_with({"n_int": {"k": {"nested": 1}}}))[0] is None
    assert parse(survey_with({"n_int": {"k": None}}))[0] is None
    too_many = {f"k{i}": i for i in range(MAX_CUSTOM_PROPERTIES + 1)}
    assert parse(survey_with({"n_int": too_many}))[0] is None


def test_check_custom_values_reports_fit_unknown_and_missing() -> None:
    p = profile()
    s = survey_with(
        {
            "n_int": {"construct": "tea", "prereg": True, "weight": 1, "scale": "vas"},
            "s_single": {"construct": 5, "prereg": "yes", "scale": "other", "mystery": 1},
        }
    )
    diags = check_custom_values(s, p)
    by = {(d.code, d.pointer): d.message for d in diags}
    items = "/blocks/0/pages/0/items/"
    # n_int (index 1): weight does not apply to integer questions.
    assert ("profile.custom_unknown", items + "1/custom/weight") in by
    # s_single (index 4): wrong kinds, an option that is not listed, an unknown key.
    assert ("profile.custom_kind", items + "4/custom/construct") in by
    assert ("profile.custom_kind", items + "4/custom/prereg") in by
    assert ("profile.custom_kind", items + "4/custom/scale") in by
    assert ("profile.custom_unknown", items + "4/custom/mystery") in by
    # Every other question lacks the required `prereg`.
    missing = [d for d in diags if d.code == "profile.custom_missing"]
    assert len(missing) == 5 and all(d.pointer.endswith("/custom") for d in missing)
    assert all(d.severity in ("warning", "info") for d in diags)
    assert check_custom_values(survey_with({}), PanelProfile()) == []
    assert check_custom_values({"not": "a survey"}, p) == []
    assert check_custom_values(parse(survey_with({}))[0], PanelProfile()) == []


# --- Fuzz: never an exception -----------------------------------------------------------

json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=8),
    lambda inner: (
        st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=8), inner, max_size=4)
    ),  # fmt: skip
    max_leaves=20,
)
TYPES = ["*", "single", "text", "note", "page", "nope", ""]
KEYS = ["label", "required", "help", "nope", "custom.x", "", "a b"]


@settings(max_examples=200, deadline=None)
@given(json_values)
def test_fuzz_validate_never_raises(data: Any) -> None:
    p, diags = validate_profile(data)
    assert (p is None) == bool(diags)
    assert all(d.code == "profile.schema" for d in diags)


@settings(max_examples=200, deadline=None)
@given(
    st.lists(st.tuples(st.sampled_from(TYPES), st.sampled_from(KEYS)), max_size=4),
    st.dictionaries(
        st.sampled_from(TYPES), st.lists(st.sampled_from(KEYS), max_size=3), max_size=3
    ),
    st.dictionaries(
        st.sampled_from(TYPES),
        st.dictionaries(st.sampled_from(KEYS), json_values, max_size=3),
        max_size=3,
    ),
    st.lists(
        st.fixed_dictionaries(
            {
                "key": st.sampled_from(["construct", "label", "x1", "required"]),
                "kind": st.sampled_from(["text", "number", "bool", "choice"]),
                "label": st.just("x"),
            },
            optional={
                "default": json_values,
                "types": st.lists(st.sampled_from(TYPES), max_size=2),
                "options": st.lists(
                    st.fixed_dictionaries(
                        {"value": st.integers() | st.text(max_size=3), "label": st.just("o")}
                    ),
                    max_size=3,
                ),
            },
        ),
        max_size=3,
    ),
)
def test_fuzz_apply_and_check_never_raise(
    hidden: list[tuple[str, str]], order: Any, defaults: Any, custom: Any
) -> None:
    data = {
        "hidden": [f"{t}.{k}" for t, k in hidden],
        "order": order,
        "defaults": defaults,
        "custom": custom,
    }
    p, diags = validate_profile(data)
    if p is None:
        assert diags
        return
    schemas, diags = apply_profile(p)
    assert set(schemas) == set(property_schemas())
    assert all(d.code in PROFILE_CODES and d.severity != "error" for d in diags)
    profile_schemas_json(p)
    survey = survey_with({"n_int": {"construct": 1, "x1": "a"}})
    assert all(d.severity != "error" for d in check_custom_values(survey, p))
