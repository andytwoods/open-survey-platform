"""Property schemas (B1): the bundled files load cleanly, cover the model completely, and
every way a schema file can go wrong is a diagnostic, never an exception."""

from __future__ import annotations

import datetime
import json
from collections.abc import Callable
from typing import Any, get_args

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st
from osp_spec import validate
from osp_spec.model import QUESTION_TYPES, Question
from osp_spec.property_schema import (
    ALL_TYPES,
    FAMILIES,
    KINDS,
    PROPERTY_SCHEMA_CODES,
    QUESTION_MODELS,
    Kind,
    TypeSchema,
    _resolve,
    bundled_sources,
    default_question,
    load_property_schemas,
    model_for,
    property_schemas,
    property_schemas_json,
)

# planning/builder-design.md §2: the field editors the builder has.
DESIGN_KINDS = {
    "text", "richtext", "number", "bool", "enum", "choicelist", "rows", "condition", "expression",
}  # fmt: skip


def codes(diags: list) -> set[str]:
    return {d.code for d in diags}


# --- The bundled schemas ----------------------------------------------------------------


def test_bundled_schemas_load_without_diagnostics() -> None:
    schemas, diags = load_property_schemas()
    assert diags == []
    assert set(schemas) == set(ALL_TYPES)


def test_one_file_per_type_named_after_it() -> None:
    for filename, text in bundled_sources().items():
        assert filename == f"{yaml.safe_load(text)['type']}.yaml"


def test_every_model_question_type_has_a_model_entry() -> None:
    union = get_args(Question.__value__)[0]  # Annotated[A | B | ..., discriminator]
    members = {get_args(m.model_fields["type"].annotation)[0] for m in get_args(union)}
    assert set(QUESTION_TYPES) == set(QUESTION_MODELS) == members


@pytest.mark.parametrize("type_", ALL_TYPES)
def test_every_model_field_has_a_property_or_a_hidden_reason(type_: str) -> None:
    schema = property_schemas()[type_]
    model = model_for(schema)
    assert model is not None
    covered = set(schema.properties) | set(schema.hidden)
    for name, info in model.model_fields.items():
        if name in covered:
            continue
        # Otherwise the field is an object whose own fields are each covered by dotted keys.
        assert any(k.startswith(name + ".") for k in covered), (
            f"{type_}: model field {name!r} is neither a property nor hidden"
        )
        for sub_name in info.annotation.model_fields:  # type: ignore[union-attr]
            assert f"{name}.{sub_name}" in covered, f"{type_}: {name}.{sub_name} uncovered"
    assert all(reason.strip() for reason in schema.hidden.values())


@pytest.mark.parametrize("type_", ALL_TYPES)
def test_every_property_maps_to_a_real_model_field(type_: str) -> None:
    schema = property_schemas()[type_]
    model = model_for(schema)
    assert model is not None
    for key in [*schema.properties, *schema.hidden]:
        assert _resolve(model, key) is not None, f"{type_}: {key!r} is no model field"


def test_every_kind_is_allowed() -> None:
    assert set(KINDS) == set(get_args(Kind.__value__)) == DESIGN_KINDS
    for schema in property_schemas().values():
        for key, spec in schema.properties.items():
            assert spec.kind in KINDS, f"{schema.type}.{key}"


def test_question_types_have_a_family_and_others_do_not() -> None:
    for schema in property_schemas().values():
        if schema.entity == "question":
            assert schema.family in FAMILIES
        else:
            assert schema.family is None


@pytest.mark.parametrize("type_", QUESTION_TYPES)
@pytest.mark.parametrize("language", [None, "en"])
def test_default_question_is_a_valid_survey_item(type_: str, language: str | None) -> None:
    q = default_question(type_, "q1", language=language)
    assert q.type == type_
    page = {"id": "p1", "items": [q.model_dump(exclude_none=True)]}
    survey = {
        "specVersion": "osp-survey/0.1",
        "id": "srv",
        "metadata": {"title": "T", "languages": ["en"]},
        "blocks": [{"id": "b1", "pages": [page]}],
        "flow": [{"type": "block", "id": "f1", "block": "b1"}],
    }
    assert [d for d in validate(survey) if d.severity == "error"] == []


def test_default_question_uses_schema_defaults() -> None:
    q = default_question("multi", "q9", language="de")
    assert q.label == {"de": "Untitled question"}
    assert q.required is False
    assert [c.value for c in q.choices] == [1, 2]  # type: ignore[union-attr]
    assert q.choices[0].label == {"de": "Option 1"}  # type: ignore[index]
    assert default_question("integer", "q2").label == "Untitled question"


def test_default_question_rejects_bad_input() -> None:
    for args in [("likert", "q1"), ("page", "q1"), ("integer", "1bad")]:
        with pytest.raises(ValueError):
            default_question(*args)


def test_default_question_does_not_share_mutable_defaults() -> None:
    a = default_question("single", "q1")
    a.choices.append(a.choices[0])  # type: ignore[union-attr]
    assert len(default_question("single", "q2").choices) == 2  # type: ignore[arg-type]


def test_json_export_round_trips() -> None:
    data = json.loads(json.dumps(property_schemas_json()))
    assert data["kinds"] == list(KINDS)
    parsed = [TypeSchema.model_validate(s) for s in data["schemas"]]
    assert {s.type for s in parsed} == set(ALL_TYPES)
    assert parsed == list(property_schemas().values())


# --- Diagnostics for broken files -------------------------------------------------------


def source(type_: str) -> dict[str, Any]:
    return yaml.safe_load(bundled_sources()[f"{type_}.yaml"])


def load_one(data: Any, filename: str = "x.yaml") -> list:
    text = data if isinstance(data, str) else yaml.safe_dump(data, sort_keys=False)
    return load_property_schemas({filename: text})[1]


def mutate(type_: str, fn: Callable[[dict[str, Any]], None]) -> list:
    data = source(type_)
    fn(data)
    return load_one(data)


def test_each_bundled_file_is_clean_alone() -> None:
    for type_ in ALL_TYPES:
        assert mutate(type_, lambda d: None) == []


@pytest.mark.parametrize(
    "text",
    ["type: [unclosed", "a: b: c", "\t- tab", "{", "type: x\n  bad indent: 1\n y: 2"],
)
def test_malformed_yaml_is_a_diagnostic(text: str) -> None:
    diags = load_one(text)
    assert codes(diags) == {"property_schema.yaml"}
    assert diags[0].pointer == "/x.yaml"


@pytest.mark.parametrize("data", ["", "just a string", "- 1\n- 2\n", "42", "null"])
def test_non_mapping_yaml_is_a_diagnostic(data: str) -> None:
    assert codes(load_one(data)) == {"property_schema.invalid"}


def _set_prop(key: str, **changes: Any) -> Callable[[dict[str, Any]], None]:
    def fn(d: dict[str, Any]) -> None:
        d["properties"][key].update(changes)

    return fn


CASES: list[tuple[str, str, Callable[[dict[str, Any]], None]]] = [
    ("integer", "property_schema.invalid", _set_prop("label", kind="slider")),
    ("integer", "property_schema.invalid", _set_prop("label", group="Misc")),
    ("integer", "property_schema.invalid", _set_prop("label", colour="red")),
    ("integer", "property_schema.invalid", _set_prop("required", translatable=True)),
    ("integer", "property_schema.invalid", lambda d: d.pop("family")),
    ("integer", "property_schema.invalid", lambda d: d.update(icon="Not A Lucide Name")),
    ("page", "property_schema.invalid", lambda d: d.update(family="choice")),
    ("page", "property_schema.invalid", _set_prop("itemOrder", options=None)),
    ("page", "property_schema.invalid", _set_prop("itemOrder", optionsFrom="id")),
    (
        "integer",
        "property_schema.invalid",
        _set_prop("label", options=[{"value": 1, "label": "a"}]),
    ),  # fmt: skip
    ("integer", "property_schema.invalid", lambda d: d["hidden"].update(label="dup")),
    (
        "integer",
        "property_schema.invalid",
        _set_prop("label", default=datetime.date(2020, 1, 1)),
    ),  # fmt: skip
    ("integer", "property_schema.unknown_type", lambda d: d.update(type="likert")),
    ("page", "property_schema.unknown_type", lambda d: d.update(type="block")),
    (
        "integer",
        "property_schema.unknown_field",
        lambda d: d["properties"].update(colour={"kind": "text", "label": "c"}),
    ),  # fmt: skip
    (
        "integer",
        "property_schema.unknown_field",
        lambda d: d["hidden"].update(choices="not an integer field"),
    ),  # fmt: skip
    (
        "survey",
        "property_schema.unknown_field",
        lambda d: d["hidden"].update({"metadata.colour": "x"}),
    ),  # fmt: skip
    ("survey", "property_schema.unknown_field", lambda d: d["hidden"].update({"id.deeper": "x"})),
    ("integer", "property_schema.uncovered_field", lambda d: d["hidden"].pop("id")),
    ("single", "property_schema.uncovered_field", lambda d: d["properties"].pop("choiceOrder")),
    ("survey", "property_schema.uncovered_field", lambda d: d["hidden"].pop("metadata.ddi")),
    ("integer", "property_schema.kind_mismatch", _set_prop("required", kind="text", default=None)),
    (
        "integer",
        "property_schema.kind_mismatch",
        _set_prop("label", kind="number", translatable=False, default=None, rich=None),
    ),  # fmt: skip
    # Rich-text levels (RT2): declared exactly when the model takes a tree, matching the
    # validator's level; never on another kind.
    ("integer", "property_schema.invalid", _set_prop("required", rich="stem")),
    ("integer", "property_schema.kind_mismatch", _set_prop("label", rich="block")),
    ("integer", "property_schema.kind_mismatch", _set_prop("label", rich=None)),
    ("integer", "property_schema.kind_mismatch", _set_prop("name", rich="inline")),
    ("survey", "property_schema.kind_mismatch", _set_prop("metadata.title", rich="inline")),
    ("integer", "property_schema.kind_mismatch", _set_prop("showIf", kind="text")),
    ("integer", "property_schema.kind_mismatch", _set_prop("help", translatable=False)),
    ("integer", "property_schema.kind_mismatch", _set_prop("name", translatable=True)),
    ("integer", "property_schema.kind_mismatch", _set_prop("label", required=False)),
    ("integer", "property_schema.kind_mismatch", _set_prop("help", required=True)),
    (
        "single",
        "property_schema.kind_mismatch",
        _set_prop("choiceOrder", options=[{"value": "fixed", "label": "F"}]),
    ),  # fmt: skip
    (
        "survey",
        "property_schema.kind_mismatch",
        _set_prop("metadata.defaultLanguage", optionsFrom="metadata.nope"),
    ),  # fmt: skip
    ("integer", "property_schema.bad_default", _set_prop("required", default="yes")),
    ("integer", "property_schema.bad_default", _set_prop("required", default=True)),
    ("integer", "property_schema.bad_default", _set_prop("required", default=None)),
    ("single", "property_schema.bad_default", _set_prop("choices", default=[])),
    ("single", "property_schema.bad_default", _set_prop("choiceOrder", default="shuffle")),
    ("survey", "property_schema.bad_default", _set_prop("settings.backNavigation", default=False)),
]


@pytest.mark.parametrize(("type_", "code", "fn"), CASES)
def test_broken_entry_is_a_diagnostic(type_: str, code: str, fn: Callable) -> None:
    diags = mutate(type_, fn)
    assert code in codes(diags), [d.message for d in diags]
    assert all(d.pointer.startswith("/x.yaml") for d in diags)


def test_duplicate_and_missing_types() -> None:
    text = bundled_sources()["integer.yaml"]
    schemas, diags = load_property_schemas({"a.yaml": text, "b.yaml": text})
    assert list(schemas) == ["integer"]
    assert codes(diags) == {"property_schema.duplicate_type"}
    assert diags[0].pointer == "/b.yaml/type"


def test_every_code_is_exercised_and_has_a_severity() -> None:
    exercised = {code for _, code, _ in CASES}
    exercised |= {"property_schema.yaml", "property_schema.duplicate_type"}
    untestable = {"property_schema.missing_type", "property_schema.internal"}  # bundled only
    assert exercised | untestable == set(PROPERTY_SCHEMA_CODES)
    assert set(PROPERTY_SCHEMA_CODES.values()) == {"error"}


# --- Fuzz: never an exception -----------------------------------------------------------

json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=8),
    lambda inner: (
        st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=8), inner, max_size=4)
    ),  # fmt: skip
    max_leaves=20,
)


@settings(max_examples=200, deadline=None)
@given(st.text(max_size=200))
def test_fuzz_text_never_raises(text: str) -> None:
    schemas, diags = load_property_schemas({"f.yaml": text})
    assert all(d.code in PROPERTY_SCHEMA_CODES for d in diags)
    assert "property_schema.internal" not in codes(diags)


@settings(max_examples=200, deadline=None)
@given(
    st.sampled_from(ALL_TYPES),
    st.sampled_from(["properties", "hidden", None]),
    st.integers(min_value=0, max_value=12),
    st.text(max_size=12),
    json_values,
)
def test_fuzz_mutated_entry_never_raises(
    type_: str, section: str | None, index: int, new_key: str, value: Any
) -> None:
    data = source(type_)
    target = data if section is None else data[section]
    keys = list(target)
    target[keys[index] if index < len(keys) else new_key] = value  # replace or add
    diags = load_one(yaml.safe_dump(data))
    assert "property_schema.internal" not in codes(diags)
