"""Property panel profiles (planning/property-profiles.md): a lab's overlay on the stock
property schema. Hide properties, reorder them, rename group headings, set defaults for
new questions and define custom properties (stored under `custom` on questions).

Pure data, no I/O. Three jobs:

- `validate_profile(data)`: the profile document as a `PanelProfile`, or diagnostics;
- `apply_profile(profile)`: the *effective* schemas the builder renders (and the JSON form
  `profile_schemas_json` serves). Whatever part of a profile does not apply is a
  diagnostic and the stock schema stands in for it: a broken profile never breaks the
  panel;
- `check_custom_values(survey, profile)`: whether a survey's custom values fit the lab's
  definitions. Warnings only: a survey must stay valid when its lab edits or deletes the
  profile, or when it moves to another lab.

None of this reaches the runtime: a profile is a view of the schema plus annotations.
"""

from __future__ import annotations

import copy
from typing import Annotated, Any, Literal

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

from .diagnostics import Diagnostic, Severity, pointer
from .model import MAX_CUSTOM_PROPERTIES, CustomKey, CustomValue, Survey, Text
from .property_schema import (
    FAMILIES,
    GROUPS,
    KINDS,
    EnumOption,
    Group,
    PropertyKey,
    PropertySpec,
    TypeSchema,
    accepts,
    property_schemas,
)

PROFILE_VERSION = "osp-panel-profile/0.1"
CUSTOM_PREFIX = "custom."
CUSTOM_KINDS = ("text", "number", "bool", "choice")
MAX_OPTIONS = 50
STAR = "*"

type CustomKind = Literal["text", "number", "bool", "choice"]
type QuestionType = Literal[
    "integer", "decimal", "text", "single", "multi", "date", "matrix", "slider", "note"
]
# "<type>.<key>" or "*.<key>": a property of one type, or of every type that has it.
type PropertyRef = Annotated[
    str,
    StringConstraints(
        pattern=r"^(\*|[a-z]+)\.[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$", max_length=120
    ),
]

# The panel editor each custom kind maps onto (property_schema.KINDS).
EDITOR_KIND: dict[str, str] = {"text": "text", "number": "number", "bool": "bool", "choice": "enum"}
assert set(EDITOR_KIND.values()) <= set(KINDS)

PROFILE_CODES: dict[str, Severity] = {
    "profile.schema": "error",  # the profile document does not validate
    "profile.unknown_type": "warning",  # an entry names no schema type
    "profile.unknown_key": "warning",  # an entry names no property of that type
    "profile.required_hidden": "warning",  # a required property cannot be hidden; kept
    "profile.bad_default": "warning",  # a default the model does not accept; ignored
    "profile.key_clash": "warning",  # a custom key collides with a stock property; skipped
    "profile.custom_kind": "warning",  # a survey value does not fit the lab's definition
    "profile.custom_unknown": "info",  # a survey value has no definition in the profile
    "profile.custom_missing": "warning",  # a required custom property has no value
}


def _diag(code: str, ptr: str, message: str) -> Diagnostic:
    return Diagnostic(severity=PROFILE_CODES[code], code=code, message=message, pointer=ptr)


# --- The format ---------------------------------------------------------------------------


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class CustomOption(_Spec):
    value: StrictStr | StrictInt
    label: Text


class CustomProperty(_Spec):
    """One lab-defined property: an annotation on questions of `types` (default: all)."""

    key: CustomKey
    kind: CustomKind
    label: Text
    help: Text | None = None
    types: list[QuestionType] | None = Field(default=None, min_length=1)
    options: list[CustomOption] | None = Field(default=None, min_length=1, max_length=MAX_OPTIONS)
    default: CustomValue | None = None
    group: Group = "Advanced"
    required: StrictBool = False

    @model_validator(mode="after")
    def _consistent(self) -> CustomProperty:
        if (self.kind == "choice") != (self.options is not None):
            raise ValueError("`options` is required for a choice property and only there")
        if self.options is not None:
            values = [o.value for o in self.options]
            if len(set(values)) != len(values):
                raise ValueError("option values must be unique")
        if self.types is not None and len(set(self.types)) != len(self.types):
            raise ValueError("`types` must not repeat a type")
        if self.default is not None and not fits(self, self.default):
            raise ValueError(f"the default does not fit a {self.kind} property")
        return self

    def applies_to(self, question_type: str) -> bool:
        return self.types is None or question_type in self.types


class PanelProfile(_Spec):
    profileVersion: Literal["osp-panel-profile/0.1"] = PROFILE_VERSION
    hidden: list[PropertyRef] = Field(default_factory=list, max_length=200)
    # type (or "*") -> keys shown first, in this order
    order: dict[str, list[PropertyKey]] = Field(default_factory=dict)
    groups: dict[Group, Text] = Field(default_factory=dict)  # heading overrides
    # question type -> property key -> the value a new question starts with
    defaults: dict[str, dict[PropertyKey, JsonValue]] = Field(default_factory=dict)
    custom: list[CustomProperty] = Field(default_factory=list, max_length=MAX_CUSTOM_PROPERTIES)

    @model_validator(mode="after")
    def _unique_custom_keys(self) -> PanelProfile:
        keys = [c.key for c in self.custom]
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        if dupes:
            raise ValueError(f"custom keys must be unique: {', '.join(dupes)}")
        return self


def fits(prop: CustomProperty, value: Any) -> bool:
    """Whether a stored value fits a custom property's kind (and options)."""
    match prop.kind:
        case "text":
            return isinstance(value, str)
        case "number":
            return isinstance(value, int | float) and not isinstance(value, bool)
        case "bool":
            return isinstance(value, bool)
        case _:
            options = prop.options or []
            return any(o.value == value and type(o.value) is type(value) for o in options)


def validate_profile(data: Any) -> tuple[PanelProfile | None, list[Diagnostic]]:
    """Parse a profile document. Structural problems are `profile.schema` diagnostics
    with a pointer into the document. Never raises."""
    try:
        return PanelProfile.model_validate(data), []
    except ValidationError as exc:
        return None, [
            _diag("profile.schema", pointer(*err["loc"]), err["msg"])
            for err in exc.errors(include_url=False)
        ]
    except Exception as exc:  # never crash (AGENTS.md rule 3)
        return None, [_diag("profile.schema", "", f"not a profile: {type(exc).__name__}")]


# --- Applying a profile to the schemas ----------------------------------------------------


def _custom_spec(c: CustomProperty) -> PropertySpec:
    return PropertySpec(
        kind=EDITOR_KIND[c.kind],  # type: ignore[arg-type]
        label=c.label,
        required=c.required,
        default=c.default,
        group=c.group,
        help=c.help,
        options=(
            [EnumOption(value=o.value, label=o.label) for o in c.options]
            if c.options is not None
            else None
        ),
    )


def apply_profile(
    profile: PanelProfile, schemas: dict[str, TypeSchema] | None = None
) -> tuple[dict[str, TypeSchema], list[Diagnostic]]:
    """The effective schemas: `schemas` (default: the bundled ones) with the profile's
    hidden properties removed, its order applied, its defaults set and its custom
    properties added as `custom.<key>` entries. Returns diagnostics for every part of the
    profile that did not apply. Never raises."""
    try:
        return _apply(profile, property_schemas() if schemas is None else schemas)
    except Exception as exc:  # never crash: the stock schemas stand in
        diag = _diag("profile.schema", "", f"profile could not be applied: {type(exc).__name__}")
        return dict(property_schemas() if schemas is None else schemas), [diag]


def _apply(
    profile: PanelProfile, schemas: dict[str, TypeSchema]
) -> tuple[dict[str, TypeSchema], list[Diagnostic]]:
    diags: list[Diagnostic] = []
    hidden: dict[str, set[str]] = {t: set() for t in schemas}

    for i, ref in enumerate(profile.hidden):
        type_, key = ref.split(".", 1)
        targets = list(schemas) if type_ == STAR else [type_]
        if type_ != STAR and type_ not in schemas:
            diags.append(_diag("profile.unknown_type", pointer("hidden", i), f"no type {type_!r}"))
            continue
        for t in targets:
            spec = schemas[t].properties.get(key)
            if spec is None:
                if type_ != STAR:
                    msg = f"{t} has no property {key!r}"
                    diags.append(_diag("profile.unknown_key", pointer("hidden", i), msg))
                continue
            if spec.required:
                msg = f"{t}.{key} is required and stays visible"
                diags.append(_diag("profile.required_hidden", pointer("hidden", i), msg))
                continue
            hidden[t].add(key)

    for t, keys in profile.order.items():
        if t != STAR and t not in schemas:
            diags.append(_diag("profile.unknown_type", pointer("order", t), f"no type {t!r}"))
            continue
        if t != STAR:
            for i, key in enumerate(keys):
                if key not in schemas[t].properties:
                    msg = f"{t} has no property {key!r}"
                    diags.append(_diag("profile.unknown_key", pointer("order", t, i), msg))

    defaults = effective_defaults(profile, schemas, diags)

    out: dict[str, TypeSchema] = {}
    for t, schema in schemas.items():
        props: dict[str, PropertySpec] = {}
        order = profile.order.get(t, profile.order.get(STAR, []))
        keys = [k for k in order if k in schema.properties]
        keys += [k for k in schema.properties if k not in keys]
        for key in keys:
            if key in hidden[t]:
                continue
            spec = schema.properties[key]
            if key in defaults.get(t, {}):
                spec = spec.model_copy(update={"default": copy.deepcopy(defaults[t][key])})
            props[key] = spec
        if schema.entity == "question":
            for i, c in enumerate(profile.custom):
                if not c.applies_to(t):
                    continue
                if c.key in schema.properties:
                    msg = f"custom key {c.key!r} clashes with a property of {t}"
                    diags.append(_diag("profile.key_clash", pointer("custom", i, "key"), msg))
                    continue
                props[CUSTOM_PREFIX + c.key] = _custom_spec(c)
        out[t] = schema.model_copy(update={"properties": props})
    return out, diags


def effective_defaults(
    profile: PanelProfile,
    schemas: dict[str, TypeSchema] | None = None,
    diags: list[Diagnostic] | None = None,
) -> dict[str, dict[str, JsonValue]]:
    """Per question type, the values a new question starts with because of the profile:
    the profile's defaults the model accepts, plus custom properties' defaults (as
    `custom.<key>`). Problems are appended to `diags` when given."""
    schemas = property_schemas() if schemas is None else schemas
    sink = [] if diags is None else diags
    out: dict[str, dict[str, JsonValue]] = {}
    for t, values in profile.defaults.items():
        schema = schemas.get(t)
        if schema is None or schema.entity != "question":
            msg = f"no question type {t!r}"
            sink.append(_diag("profile.unknown_type", pointer("defaults", t), msg))
            continue
        for key, value in values.items():
            if key not in schema.properties:
                msg = f"{t} has no property {key!r}"
                sink.append(_diag("profile.unknown_key", pointer("defaults", t, key), msg))
            elif value is None or not accepts(schema, key, value):
                msg = f"{t}.{key}: {value!r} is not a valid value"
                sink.append(_diag("profile.bad_default", pointer("defaults", t, key), msg))
            else:
                out.setdefault(t, {})[key] = value
    for c in profile.custom:
        if c.default is None:
            continue
        for t, schema in schemas.items():
            if schema.entity == "question" and c.applies_to(t) and c.key not in schema.properties:
                out.setdefault(t, {})[CUSTOM_PREFIX + c.key] = c.default
    return out


def profile_schemas_json(profile: PanelProfile | None) -> dict[str, Any]:
    """The effective schemas as the builder reads them: the shape of
    `property_schema.property_schemas_json()` plus `groupLabels` (heading overrides),
    `defaults` (per question type, for `add_question`), `profileApplied` and the
    profile's diagnostics. With no profile, the stock document."""
    if profile is None:
        schemas, diags = property_schemas(), []
        defaults: dict[str, dict[str, JsonValue]] = {}
        labels: dict[str, Text] = {}
    else:
        schemas, diags = apply_profile(profile)
        defaults = effective_defaults(profile)
        labels = dict(profile.groups)
    return {
        "kinds": list(KINDS),
        "families": list(FAMILIES),
        "groups": list(GROUPS),
        "groupLabels": labels,
        "defaults": defaults,
        "profileApplied": profile is not None,
        "diagnostics": [d.model_dump(mode="json") for d in diags],
        "schemas": [s.model_dump(mode="json", exclude_none=True) for s in schemas.values()],
    }


# --- Checking a survey's custom values ----------------------------------------------------


def check_custom_values(survey: Survey | Any, profile: PanelProfile) -> list[Diagnostic]:
    """Diagnostics (warnings and info, never errors) about the custom values a survey
    carries, judged by the lab's profile. Accepts a parsed `Survey` or any document; an
    unparseable document yields nothing (the validator reports it). Never raises."""
    try:
        model = survey if isinstance(survey, Survey) else Survey.model_validate(survey)
        return _check(model, profile)
    except Exception:
        return []


def _check(survey: Survey, profile: PanelProfile) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    defs = {c.key: c for c in profile.custom}
    for bi, block in enumerate(survey.blocks):
        for pi, page in enumerate(block.pages):
            for qi, q in enumerate(page.items):
                base = pointer("blocks", bi, "pages", pi, "items", qi, "custom")
                values = q.custom or {}
                for key, value in values.items():
                    c = defs.get(key)
                    if c is None or not c.applies_to(q.type):
                        msg = f"{q.id}: custom property {key!r} is not defined for {q.type}"
                        out.append(_diag("profile.custom_unknown", base + pointer(key), msg))
                    elif not fits(c, value):
                        msg = f"{q.id}: {key!r} should be a {c.kind} value"
                        out.append(_diag("profile.custom_kind", base + pointer(key), msg))
                for c in profile.custom:
                    if c.required and c.applies_to(q.type) and c.key not in values:
                        msg = f"{q.id}: custom property {c.key!r} is required by the lab profile"
                        out.append(_diag("profile.custom_missing", base, msg))
    return out


__all__ = [
    "CUSTOM_KINDS",
    "CUSTOM_PREFIX",
    "EDITOR_KIND",
    "MAX_OPTIONS",
    "PROFILE_CODES",
    "PROFILE_VERSION",
    "CustomOption",
    "CustomProperty",
    "PanelProfile",
    "apply_profile",
    "check_custom_values",
    "effective_defaults",
    "fits",
    "profile_schemas_json",
    "validate_profile",
]
