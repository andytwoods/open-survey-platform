"""Property schemas: each question type (and pages, blocks, survey settings) described once,
as data (planning/builder-design.md §1).

The data lives in `osp_spec/properties/<type>.yaml`. The builder renders property panels
from it, picking a field editor by `kind`; `add_question` takes its defaults from it.

- `load_property_schemas()` parses and checks the files. It never raises: malformed YAML,
  a bad entry or a mismatch with the `osp-survey` model becomes a `Diagnostic`.
- `property_schemas_json()` is the JSON form `osp-api` serves.
- `default_question(type, id)` builds a new question from the schema defaults.

Checks against the model (all reported as diagnostics):
- every property and hidden key names a real model field (dotted keys such as
  `metadata.title` reach into nested objects);
- every model field is a property or is listed under `hidden` with a reason;
- each `kind` fits the field's type (a sample value of that kind validates, `translatable`
  matches whether the field accepts a `{language: text}` map, `enum` options equal the
  field's literal values, `required` matches the model);
- `default` values validate against the model and agree with the model's own defaults.

Reading the bundled files is the only I/O; it is read-only package data.
"""

from __future__ import annotations

import copy
import functools
import types
from collections.abc import Mapping
from importlib import resources
from typing import Annotated, Any, Literal, TypeAliasType, Union, get_args, get_origin

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)
from pydantic_core import PydanticUndefined

from .diagnostics import Diagnostic, Severity, pointer
from .model import (
    QUESTION_TYPES,
    SPEC_VERSION,
    Block,
    DateQuestion,
    DecimalQuestion,
    IntegerQuestion,
    MatrixQuestion,
    MultiQuestion,
    NoteQuestion,
    Page,
    PlainText,
    Question,
    SingleQuestion,
    SliderQuestion,
    Survey,
    TextQuestion,
)
from .richtext import Level, text_level

# A formatting-free paragraph: what a field must take to be rich at all.
_RICH_SAMPLE = {"type": "rich", "blocks": [{"type": "p", "content": [{"text": "x"}]}]}

KINDS = (
    "text",
    "richtext",
    "number",
    "bool",
    "enum",
    "choicelist",
    "rows",
    "condition",
    "expression",
)
FAMILIES = ("choice", "text", "number", "matrix", "scale", "note")
GROUPS = ("Basics", "Choices", "Logic", "Validation", "Advanced")
ENTITIES = ("question", "page", "block", "survey")

type Kind = Literal[
    "text", "richtext", "number", "bool", "enum", "choicelist", "rows", "condition", "expression"
]
type Family = Literal["choice", "text", "number", "matrix", "scale", "note"]
type Group = Literal["Basics", "Choices", "Logic", "Validation", "Advanced"]
type Entity = Literal["question", "page", "block", "survey"]
type PropertyKey = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
]
type LucideName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]

# Diagnostic codes this module emits (all errors). Separate from the survey validator's
# `CODES`: these describe the property schema files, not a survey.
PROPERTY_SCHEMA_CODES: dict[str, Severity] = {
    "property_schema.yaml": "error",  # not parseable YAML
    "property_schema.invalid": "error",  # YAML parses but the entry is malformed
    "property_schema.unknown_type": "error",  # `type` is no model type for its `entity`
    "property_schema.duplicate_type": "error",
    "property_schema.missing_type": "error",  # a model type has no schema file
    "property_schema.unknown_field": "error",  # a key names no model field
    "property_schema.uncovered_field": "error",  # a model field is neither shown nor hidden
    "property_schema.kind_mismatch": "error",  # kind/translatable/required/options vs model
    "property_schema.bad_default": "error",  # defaults don't validate or disagree with model
    "property_schema.internal": "error",  # the loader itself failed; never expected
}

QUESTION_MODELS: dict[str, type[BaseModel]] = {
    "integer": IntegerQuestion,
    "decimal": DecimalQuestion,
    "text": TextQuestion,
    "single": SingleQuestion,
    "multi": MultiQuestion,
    "date": DateQuestion,
    "matrix": MatrixQuestion,
    "slider": SliderQuestion,
    "note": NoteQuestion,
}
OTHER_MODELS: dict[str, type[BaseModel]] = {"page": Page, "block": Block, "survey": Survey}
ALL_TYPES = (*QUESTION_TYPES, *OTHER_MODELS)


# --- The format -------------------------------------------------------------------------


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class EnumOption(_Spec):
    value: StrictStr | StrictInt
    label: PlainText


class PropertySpec(_Spec):
    """One editable field: which editor (`kind`), where (`group`) and how it starts."""

    kind: Kind
    label: PlainText
    required: StrictBool = False
    default: JsonValue = None  # None: no default
    translatable: StrictBool = False
    group: Group = "Basics"
    help: PlainText | None = None
    options: list[EnumOption] | None = Field(default=None, min_length=1)  # enum only
    optionsFrom: PropertyKey | None = None  # enum only: options are another field's values
    # text / richtext only: the rich-text level the field takes (planning/rich-text.md
    # §3.1): which blocks the editor offers and the character limit it shows. Must agree
    # with the validator's level for the field (`osp_spec.richtext.text_level`); absent
    # for a plain field.
    rich: Level | None = None

    @model_validator(mode="after")
    def _enum_options(self) -> PropertySpec:
        if self.rich is not None and self.kind not in ("text", "richtext"):
            raise ValueError("`rich` is only for text and richtext properties")
        has_static, has_dynamic = self.options is not None, self.optionsFrom is not None
        if self.kind == "enum" and has_static == has_dynamic:
            raise ValueError("an enum property needs exactly one of `options` or `optionsFrom`")
        if self.kind != "enum" and (has_static or has_dynamic):
            raise ValueError("`options` and `optionsFrom` are only for enum properties")
        if self.options is not None:
            values = [o.value for o in self.options]
            if len(set(values)) != len(values):
                raise ValueError("enum option values must be unique")
        if self.translatable and self.kind not in ("text", "richtext", "choicelist", "rows"):
            raise ValueError(f"a {self.kind} property cannot be translatable")
        return self


class TypeSchema(_Spec):
    """The property schema of one question type, or of pages, blocks or the survey."""

    type: StrictStr
    entity: Entity
    family: Family | None = None  # question types only: picks the canvas card
    label: PlainText
    icon: LucideName
    properties: dict[PropertyKey, PropertySpec]
    hidden: dict[PropertyKey, Annotated[str, StringConstraints(min_length=1)]] = Field(
        default_factory=dict
    )  # field -> why it has no property editor

    @model_validator(mode="after")
    def _shape(self) -> TypeSchema:
        if (self.entity == "question") != (self.family is not None):
            raise ValueError("`family` is required for question types and only for them")
        both = sorted(set(self.properties) & set(self.hidden))
        if both:
            raise ValueError(f"listed as both property and hidden: {', '.join(both)}")
        return self


# --- Loading ----------------------------------------------------------------------------


def _diag(code: str, ptr: str, message: str) -> Diagnostic:
    return Diagnostic(severity=PROPERTY_SCHEMA_CODES[code], code=code, message=message, pointer=ptr)


def bundled_sources() -> dict[str, str]:
    """The shipped schema files, `{filename: YAML text}`."""
    root = resources.files("osp_spec") / "properties"
    return {
        f.name: f.read_text(encoding="utf-8")
        for f in sorted(root.iterdir(), key=lambda f: f.name)
        if f.name.endswith(".yaml")
    }


def load_property_schemas(
    sources: Mapping[str, str] | None = None,
) -> tuple[dict[str, TypeSchema], list[Diagnostic]]:
    """Parse and check property schemas. Never raises.

    `sources` maps filenames to YAML text (default: the bundled files). Returns the schemas
    that parsed, by `type`, and diagnostics whose pointers start with `/<filename>`. Entries
    with model mismatches are still returned; callers decide via the diagnostics.
    """
    try:
        return _load(bundled_sources() if sources is None else sources, check_all=sources is None)
    except Exception as exc:  # never crash (AGENTS.md rule 3)
        return {}, [_diag("property_schema.internal", "", f"loader failed: {type(exc).__name__}")]


def _load(
    sources: Mapping[str, str], *, check_all: bool
) -> tuple[dict[str, TypeSchema], list[Diagnostic]]:
    out: dict[str, TypeSchema] = {}
    diags: list[Diagnostic] = []
    for filename, text in sources.items():
        root = pointer(filename)
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            where = getattr(exc, "problem_mark", None)
            at = f" at line {where.line + 1}, column {where.column + 1}" if where else ""
            problem = getattr(exc, "problem", None) or "invalid YAML"
            diags.append(_diag("property_schema.yaml", root, f"{filename}: {problem}{at}"))
            continue
        try:
            schema = TypeSchema.model_validate(data)
        except ValidationError as exc:
            for err in exc.errors(include_url=False):
                msg = f"{filename}: {err['msg']}"
                diags.append(_diag("property_schema.invalid", root + pointer(*err["loc"]), msg))
            continue
        if schema.type in out:
            msg = f"{filename}: type {schema.type!r} is already defined"
            diags.append(_diag("property_schema.duplicate_type", pointer(filename, "type"), msg))
            continue
        model_diags = _check_against_model(schema, filename)
        diags.extend(model_diags)
        if not any(d.code == "property_schema.unknown_type" for d in model_diags):
            out[schema.type] = schema
    if check_all:
        for t in ALL_TYPES:
            if t not in out:
                diags.append(_diag("property_schema.missing_type", "", f"no schema for {t!r}"))
    return out, diags


# --- Checks against the model -----------------------------------------------------------


def model_for(schema: TypeSchema) -> type[BaseModel] | None:
    """The model class a schema describes, or None if its `type` fits no model."""
    if schema.entity == "question":
        return QUESTION_MODELS.get(schema.type)
    if schema.type == schema.entity:
        return OTHER_MODELS[schema.entity]
    return None


def _unalias(tp: Any) -> Any:
    while isinstance(tp, TypeAliasType):
        tp = tp.__value__
    return tp


def _submodel(tp: Any) -> type[BaseModel] | None:
    """The model class inside `tp` (`Settings`, `Metadata | None`), if exactly one."""
    tp = _unalias(tp)
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        return tp
    if get_origin(tp) in (Union, types.UnionType):
        models = [a for a in get_args(tp) if isinstance(a, type) and issubclass(a, BaseModel)]
        return models[0] if len(models) == 1 else None
    return None


def _owner(model: type[BaseModel], key: str) -> tuple[type[BaseModel], str] | None:
    """The model class that directly holds the field a dotted key names, and the field."""
    *parents, last = key.split(".")
    for part in parents:
        info = model.model_fields.get(part)
        sub = _submodel(info.annotation) if info else None
        if sub is None:
            return None
        model = sub
    return (model, last) if last in model.model_fields else None


def _resolve(model: type[BaseModel], key: str) -> Any | None:
    """The pydantic FieldInfo a dotted key names, or None."""
    found = _owner(model, key)
    return found[0].model_fields[found[1]] if found else None


def _literal_values(tp: Any) -> set[Any] | None:
    tp = _unalias(tp)
    if get_origin(tp) is Literal:
        return set(get_args(tp))
    return None


def _skeleton(schema: TypeSchema) -> dict[str, Any]:
    """The smallest valid instance, before any property is set."""
    note = {"id": "q0", "type": "note", "label": "x"}
    page = {"id": "p0", "items": [note]}
    match schema.entity:
        case "question":
            # A matrix needs at least one row to validate (model.MatrixQuestion).
            extra = {"rows": [{"id": "r0", "label": "x"}]} if schema.type == "matrix" else {}
            return {"id": "q0", "type": schema.type, "label": "x", **extra}
        case "page":
            return page
        case "block":
            return {"id": "b0", "pages": [page]}
        case _:
            metadata = {"title": "x", "languages": ["en"]}
            return {"specVersion": SPEC_VERSION, "id": "s0", "metadata": metadata}


def _set(data: dict[str, Any], key: str, value: Any) -> None:
    *parents, last = key.split(".")
    for part in parents:
        data = data.setdefault(part, {})
    data[last] = value


def _accepts(model: type[BaseModel], schema: TypeSchema, key: str, value: Any) -> bool:
    data = _skeleton(schema)
    _set(data, key, value)
    try:
        model.model_validate(data)
    except ValidationError:
        return False
    return True


def accepts(schema: TypeSchema, key: str, value: Any) -> bool:
    """Whether the model behind `schema` takes `value` for property `key` (on an otherwise
    minimal object). False for a schema that fits no model. Never raises."""
    model = model_for(schema)
    if model is None:
        return False
    try:
        return _accepts(model, schema, key, value)
    except Exception:
        return False


_EXPR = {"kind": "answered", "ref": {"kind": "ref", "id": "q0"}}


def _samples(spec: PropertySpec, translated: bool) -> list[Any]:
    """Values a field of this kind must accept (`translated`: as `{language: text}`)."""
    text: Any = {"en": "x"} if translated else "x"
    match spec.kind:
        case "text" | "richtext":
            return [text]
        case "number":
            return [1]
        case "bool":
            return [True, False]
        case "enum":
            return [o.value for o in spec.options] if spec.options else ["en"]
        case "choicelist":
            return [[{"value": 1, "label": text}]]
        case "rows":
            return [[{"id": "r1", "label": text}]]
        case _:  # condition, expression
            return [_EXPR]


def _check_against_model(schema: TypeSchema, filename: str) -> list[Diagnostic]:
    model = model_for(schema)
    if model is None:
        msg = f"{filename}: {schema.type!r} is not a {schema.entity} type"
        return [_diag("property_schema.unknown_type", pointer(filename, "type"), msg)]
    diags: list[Diagnostic] = []

    def report(code: str, *parts: str, msg: str) -> None:
        diags.append(_diag(code, pointer(filename, *parts), f"{filename}: {msg}"))

    for section in ("properties", "hidden"):
        for key in getattr(schema, section):
            if _resolve(model, key) is None:
                report("property_schema.unknown_field", section, key, msg=f"no model field {key!r}")

    # Coverage: walk every model field, descending into objects reached by dotted keys.
    covered = set(schema.properties) | set(schema.hidden)

    def walk(m: type[BaseModel], prefix: str) -> None:
        for name, info in m.model_fields.items():
            key = prefix + name
            if key in covered:
                continue
            sub = _submodel(info.annotation)
            if sub is not None and any(c.startswith(key + ".") for c in covered):
                walk(sub, key + ".")
            else:
                msg = f"model field {key!r} has no property entry and is not listed as hidden"
                report("property_schema.uncovered_field", "properties", msg=msg)

    walk(model, "")

    for key, spec in schema.properties.items():
        info = _resolve(model, key)
        if info is None:
            continue
        mismatch = []
        if not all(_accepts(model, schema, key, v) for v in _samples(spec, spec.translatable)):
            mismatch.append(f"the field does not take {spec.kind} values")
        if not spec.translatable and spec.kind in ("text", "richtext", "choicelist", "rows"):
            if _accepts(model, schema, key, _samples(spec, True)[0]):
                mismatch.append("the field accepts translations but translatable is false")
        if spec.options is not None:
            literal = _literal_values(info.annotation)
            if literal is not None and literal != {o.value for o in spec.options}:
                mismatch.append(f"options differ from the model's values {sorted(literal)}")
        if spec.optionsFrom is not None and _resolve(model, spec.optionsFrom) is None:
            mismatch.append(f"optionsFrom names no model field {spec.optionsFrom!r}")
        if spec.required != info.is_required():
            mismatch.append(f"required should be {info.is_required()} to match the model")
        if spec.kind in ("text", "richtext"):
            # Rich-text level (planning/rich-text.md §3.1): declared exactly when the model
            # takes a tree, and the same level the validator applies to the field.
            owner = _owner(model, key)
            expected = text_level(owner[0], owner[1]) if owner else None
            takes_rich = _accepts(model, schema, key, _RICH_SAMPLE)
            if takes_rich and spec.rich is None:
                mismatch.append(f"the field takes rich text: declare rich: {expected}")
            elif not takes_rich and spec.rich is not None:
                mismatch.append("the field is plain text (no rich: level)")
            elif takes_rich and spec.rich != expected:
                mismatch.append(f"rich should be {expected!r}, the validator's level")
        for m in mismatch:
            report("property_schema.kind_mismatch", "properties", key, msg=f"{key}: {m}")

        if spec.default is not None:
            if not _accepts(model, schema, key, spec.default):
                msg = f"{key}: default {spec.default!r} is not a valid value"
                report("property_schema.bad_default", "properties", key, "default", msg=msg)
        model_default = info.default
        if model_default is not PydanticUndefined and model_default is not None:
            if spec.default != model_default:
                msg = f"{key}: default should be {model_default!r}, the model's default"
                report("property_schema.bad_default", "properties", key, "default", msg=msg)

    if not diags:  # all defaults together
        data = _skeleton(schema)
        for key, spec in schema.properties.items():
            if spec.default is not None:
                _set(data, key, copy.deepcopy(spec.default))
        try:
            model.model_validate(data)
        except ValidationError as exc:
            msg = f"defaults do not validate together: {exc.error_count()} error(s)"
            report("property_schema.bad_default", "properties", msg=msg)
    return diags


# --- Public helpers ---------------------------------------------------------------------


@functools.cache
def _bundled() -> tuple[dict[str, TypeSchema], tuple[Diagnostic, ...]]:
    schemas, diags = load_property_schemas()
    return schemas, tuple(diags)


def property_schemas() -> dict[str, TypeSchema]:
    """The bundled schemas by type (cached). Tests keep them free of diagnostics."""
    return _bundled()[0]


def property_schemas_json() -> dict[str, Any]:
    """The bundled schemas as JSON-ready data, for `osp-api` to serve."""
    return {
        "kinds": list(KINDS),
        "families": list(FAMILIES),
        "groups": list(GROUPS),
        "schemas": [
            s.model_dump(mode="json", exclude_none=True) for s in property_schemas().values()
        ],
    }


def _localise(value: Any, language: str) -> Any:
    if isinstance(value, str):
        return {language: value}
    if isinstance(value, list):  # choicelist / rows: translate each label
        return [
            {**c, "label": _localise(c["label"], language)} if isinstance(c, dict) else c
            for c in value
        ]
    return value


def default_question(type: str, id: str, *, language: str | None = None) -> Question:
    """A new question of `type` with id `id`, built from the schema defaults.

    With `language`, translatable plain-string defaults become `{language: text}`.
    Raises `ValueError` for an unknown type or an invalid id (callers such as the
    `add_question` op validate params first and report a diagnostic instead).
    """
    schema = property_schemas().get(type)
    if schema is None or schema.entity != "question":
        raise ValueError(f"unknown question type {type!r}")
    data: dict[str, Any] = {"id": id, "type": type}
    for key, spec in schema.properties.items():
        if spec.default is None:
            continue
        value = copy.deepcopy(spec.default)
        if language is not None and spec.translatable:
            value = _localise(value, language)
        _set(data, key, value)
    try:
        return QUESTION_MODELS[type].model_validate(data)  # type: ignore[return-value]
    except ValidationError as exc:
        raise ValueError(f"invalid question: {exc.error_count()} error(s)") from exc
