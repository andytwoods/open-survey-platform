"""The `osp-survey` model (pydantic v2). Pure data, no I/O.

Conventions:
- Every object a survey edit can target has a stable `id`, unique across the whole survey.
  References (conditions, piping `${id}`, `choiceList`, flow `block`/`quota`/`variables`)
  always use ids, so renaming a variable never breaks a reference.
- `name` is the human-readable variable name used in data exports and codebooks. It
  defaults to the `id`. Names are unique across questions and variables.
- Collections are lists of objects carrying their own `id` (not maps keyed by id), so the
  validator can report a duplicate id instead of JSON silently dropping it.
- Translatable strings (`Text`) are a plain string or a `{language: string}` map.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictInt,
    StrictStr,
    StringConstraints,
)

from .expr import Expression

SPEC_VERSION = "osp-survey/0.1"

type Identifier = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", min_length=1, max_length=64)
]
type LanguageTag = Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")]
type Text = StrictStr | dict[LanguageTag, StrictStr]
type ChoiceValue = StrictInt | StrictStr
type Order = Literal["fixed", "shuffle"]


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )


# --- Metadata ---------------------------------------------------------------------------


class Metadata(Model):
    title: Text
    description: Text | None = None
    languages: list[LanguageTag] = Field(min_length=1)
    defaultLanguage: LanguageTag | None = None  # first of `languages` when omitted
    license: StrictStr | None = None
    ddi: dict[str, JsonValue] | None = None  # free-form DDI study metadata


class Settings(Model):
    backNavigation: bool = True  # semantics.md §5


# --- Choices ----------------------------------------------------------------------------


class Choice(Model):
    """One option. `value` is the code stored in data (semantics.md §2) and the option's
    identity within its list."""

    value: ChoiceValue
    label: Text


class ChoiceList(Model):
    """A shared choice list, referenced by questions through `choiceList`."""

    id: Identifier
    choices: list[Choice] = Field(min_length=1)


# --- Questions --------------------------------------------------------------------------


class _QuestionBase(Model):
    id: Identifier
    label: Text
    help: Text | None = None
    showIf: Expression | None = None


class _AnswerableBase(_QuestionBase):
    name: Identifier | None = None
    required: bool = False  # only while relevant (semantics.md §4)
    constraint: Expression | None = None  # checked only on answered values
    constraintMessage: Text | None = None


class IntegerQuestion(_AnswerableBase):
    type: Literal["integer"]


class DecimalQuestion(_AnswerableBase):
    type: Literal["decimal"]


class TextQuestion(_AnswerableBase):
    type: Literal["text"]


class DateQuestion(_AnswerableBase):
    type: Literal["date"]


class _ChoiceQuestionBase(_AnswerableBase):
    """Exactly one of `choiceList` (shared, by id) or `choices` (inline) is set."""

    choiceList: Identifier | None = None
    choices: list[Choice] | None = Field(default=None, min_length=1)
    choiceOrder: Order = "fixed"  # "shuffle": seeded randomize() (semantics.md §7)


class SingleQuestion(_ChoiceQuestionBase):
    type: Literal["single"]


class MultiQuestion(_ChoiceQuestionBase):
    type: Literal["multi"]


class NoteQuestion(_QuestionBase):
    """Display-only text. Stores no value, so it has no `name`, `required` or `constraint`."""

    type: Literal["note"]


type Question = Annotated[
    IntegerQuestion
    | DecimalQuestion
    | TextQuestion
    | SingleQuestion
    | MultiQuestion
    | DateQuestion
    | NoteQuestion,
    Field(discriminator="type"),
]
type AnswerableQuestion = (
    IntegerQuestion | DecimalQuestion | TextQuestion | SingleQuestion | MultiQuestion | DateQuestion
)
QUESTION_TYPES = ("integer", "decimal", "text", "single", "multi", "date", "note")


# --- Pages and blocks -------------------------------------------------------------------


class Page(Model):
    """One screen. Validation runs on page submit (semantics.md §4)."""

    id: Identifier
    items: list[Question] = Field(min_length=1)
    itemOrder: Order = "fixed"  # realised order fixed at first reach (semantics.md §7)


class Block(Model):
    """A named run of pages, placed in the flow by a `block` node."""

    id: Identifier
    title: StrictStr | None = None  # builder-only label, never shown to participants
    pages: list[Page] = Field(min_length=1)


# --- Variables --------------------------------------------------------------------------


class _VariableBase(Model):
    id: Identifier
    name: Identifier | None = None


class EmbeddedVariable(_VariableBase):
    """A value supplied at session start, e.g. from a URL parameter."""

    kind: Literal["embedded"]
    valueType: Literal["text", "integer", "decimal"] = "text"
    source: Literal["url"] = "url"
    param: StrictStr
    default: StrictStr | StrictInt | None = None


class AssignedVariable(_VariableBase):
    """A between-subjects condition, set by an `assign` flow node (semantics.md §7)."""

    kind: Literal["assigned"]
    levels: list[ChoiceValue] = Field(min_length=1)


class ComputedVariable(_VariableBase):
    """A value derived from other answers and variables (XLSForm `calculate`)."""

    kind: Literal["computed"]
    expr: Expression


type Variable = Annotated[
    EmbeddedVariable | AssignedVariable | ComputedVariable, Field(discriminator="kind")
]


# --- Quotas -----------------------------------------------------------------------------


class QuotaFull(Model):
    """What happens to a participant who hits a full quota: optionally show `block`, then
    end with `outcome`."""

    block: Identifier | None = None
    outcome: Identifier


class Quota(Model):
    id: Identifier
    when: Expression
    limit: StrictInt = Field(ge=0)
    countOn: Literal["complete"] = "complete"
    onFull: QuotaFull


# --- Flow -------------------------------------------------------------------------------


class BlockNode(Model):
    type: Literal["block"]
    id: Identifier
    block: Identifier


class BranchNode(Model):
    type: Literal["branch"]
    id: Identifier
    if_: Expression = Field(alias="if")
    then: list[FlowNode]
    else_: list[FlowNode] = Field(default_factory=list, alias="else")


class RandomiserNode(Model):
    """Runs its children in a seeded random order, or `pick` of them (semantics.md §7)."""

    type: Literal["randomiser"]
    id: Identifier
    children: list[FlowNode] = Field(min_length=1)
    pick: StrictInt | None = Field(default=None, ge=1)


class AssignNode(Model):
    """Assigns each listed `assigned` variable one of its levels (semantics.md §7)."""

    type: Literal["assign"]
    id: Identifier
    variables: list[Identifier] = Field(min_length=1)


class QuotaCheckNode(Model):
    type: Literal["quotaCheck"]
    id: Identifier
    quota: Identifier


class EndNode(Model):
    type: Literal["end"]
    id: Identifier
    outcome: Identifier = "complete"
    message: Text | None = None


type FlowNode = Annotated[
    BlockNode | BranchNode | RandomiserNode | AssignNode | QuotaCheckNode | EndNode,
    Field(discriminator="type"),
]
FLOW_NODE_TYPES = ("block", "branch", "randomiser", "assign", "quotaCheck", "end")


# --- Survey -----------------------------------------------------------------------------


class Survey(Model):
    """An `osp-survey` document. Reaching the end of `flow` means `end: complete` (§6)."""

    specVersion: Literal["osp-survey/0.1"]
    id: Identifier
    version: StrictInt | None = Field(default=None, ge=1)  # published version (§9)
    metadata: Metadata
    settings: Settings = Field(default_factory=Settings)
    choiceLists: list[ChoiceList] = Field(default_factory=list)
    variables: list[Variable] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)
    quotas: list[Quota] = Field(default_factory=list)
    flow: list[FlowNode] = Field(default_factory=list)


for _m in (BranchNode, RandomiserNode, Survey):
    _m.model_rebuild()
