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
- Fields that must be true/false (`showIf`, `constraint`, branch `if`, quota `when`) are
  typed `Condition`; value expressions (computed `expr`) are `Expression`. Both are the
  same `osp-expr` AST in JSON; the validator type-checks a `Condition` as boolean.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
)

from .expr import Condition, Expression

SPEC_VERSION = "osp-survey/0.1"

type Identifier = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", min_length=1, max_length=64)
]
type LanguageTag = Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")]
type Text = StrictStr | dict[LanguageTag, StrictStr]
type ChoiceValue = StrictInt | StrictStr
type Order = Literal["fixed", "shuffle"]
# A decimal written as text, so no binary float sneaks in (semantics.md §2).
type DecimalText = Annotated[str, StringConstraints(pattern=r"^-?(\d+(\.\d+)?)$", max_length=64)]
# An outcome as `settings.endings` keys it: an identifier, or the built-in `hook-failed`
# (runtime-design.md §7a), which is not one.
type OutcomeKey = Annotated[
    str,
    StringConstraints(
        pattern=r"^(?:[A-Za-z_][A-Za-z0-9_]*|hook-failed)$", min_length=1, max_length=64
    ),
]
type Date = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )


# --- Provenance (planning/question-bank.md §2.3) ----------------------------------------

# A bank item id (a uuid) or a bundled library id ("phq9").
type BankRef = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", min_length=1, max_length=64)
]
type BankLibrary = Literal["lab", "host", "bundled", "file"]
# How an instrument may be used (question-bank.md §2.1, §7). Which classes may be bundled
# with the software is licence-policy.toml `[instruments] allowed`. `free-use`: the holder
# grants free use but says nothing on redistribution or adaptation (not bundle-able).
type LicenceClass = Literal[
    "public-domain",
    "cc0",
    "cc-by-4.0",
    "free-use",
    "author-permission",
    "free-noncommercial",
    "licensed-to-lab",
    "unknown",
]
LICENCE_CLASSES: tuple[str, ...] = (
    "public-domain",
    "cc0",
    "cc-by-4.0",
    "free-use",
    "author-permission",
    "free-noncommercial",
    "licensed-to-lab",
    "unknown",
)
type Checksum = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


class Source(Model):
    """Where an inserted question, page or block came from: which bank item, which version,
    which library. Written only by the bank insert op; the runtime never reads it. A matrix
    row has the source of its matrix; an item without one has its page's, then its block's."""

    bank: BankRef
    version: StrictInt = Field(ge=1)
    library: BankLibrary
    item: Identifier | None = None  # the fragment-local id this object had ("phq9_q3")
    checksum: Checksum | None = None  # of the inserted fragment: "edited since insert"


class InstrumentLicence(Model):
    class_: LicenceClass = Field(alias="class")
    holder: StrictStr | None = None
    statement: StrictStr | None = None
    url: StrictStr | None = None
    evidenceDate: Date | None = None


class InstrumentCitation(Model):
    text: StrictStr
    doi: StrictStr | None = None


class Instrument(Model):
    """One instrument the survey uses (lead decision 1, question-bank.md): derived from the
    `source` fields at publish (`osp_spec.bank.with_instruments`), so a published version
    stays self-describing even if the bank item is later deleted."""

    bank: BankRef
    version: StrictInt = Field(ge=1)
    library: BankLibrary
    title: StrictStr | None = None
    abbreviation: StrictStr | None = None
    licence: InstrumentLicence | None = None
    citation: InstrumentCitation | None = None


# --- Metadata ---------------------------------------------------------------------------


class Metadata(Model):
    title: Text
    description: Text | None = None
    languages: list[LanguageTag] = Field(min_length=1)
    defaultLanguage: LanguageTag | None = None  # first of `languages` when omitted
    license: StrictStr | None = None
    ddi: dict[str, JsonValue] | None = None  # free-form DDI study metadata
    # The instruments used (question-bank.md lead decision 1): derived at publish from the
    # `source` fields, never edited by hand.
    instruments: list[Instrument] | None = None


class Retention(Model):
    """How long participant data is kept (decided 16 Oct 2026: required before publishing,
    no silent default). Maps onto the store's retention policy (`osp_store.retention`):

    - `days-after-close`: delete `days` days after the survey closes;
    - `after-date`: delete after `until` (a calendar date);
    - `indefinite`: keep until the researcher deletes it (an explicit choice).
    """

    kind: Literal["days-after-close", "after-date", "indefinite"]
    days: StrictInt | None = Field(default=None, ge=0)
    until: Date | None = None


class Ending(Model):
    """What the participant sees when the session ends with one outcome (end-of-survey plan
    §4.1, task EN1). `settings.endings` maps an outcome identifier (an end node's `outcome`,
    a quota's `onFull.outcome`, the consent `declineOutcome`, the built-ins `complete` and
    `hook-failed`) to its ending, so the screen, the data and the exports agree.

    - `title`: the heading; None: the app's own translated "Thank you".
    - `body`: the text under it, with piping (`${id}`, variables, built-ins) as on pages
      (semantics.md §8). Rendered as text, never as HTML. An end node's own `message` is
      shown above it.
    - `status`: `auto` shows the app's own truthful line ("Your answers have been sent." when
      a response was recorded, "Nothing was recorded." for a decline); `none` hides it for a
      recorded response. Researcher text never replaces it; a decline always shows it.
    - `summary`: reserved for showing the participant's answers (task EN5); `none` today.
    """

    title: Text | None = None
    body: Text | None = None
    status: Literal["auto", "none"] = "auto"
    summary: Literal["none", "answers"] = "none"


class Settings(Model):
    backNavigation: bool = True  # semantics.md §5
    # semantics.md §5 (R6-5): `every-page` saves to the server on every change; `end-only`
    # sends nothing before the final submit and keeps its copy in `localCopy`.
    saveMode: Literal["every-page", "end-only"] = "every-page"
    localCopy: Literal["browser", "memory"] = "browser"
    # semantics.md §5 (S-1): a resume link stops working after this many idle days.
    resumeExpiryDays: StrictInt = Field(default=30, ge=1, le=3650)
    retention: Retention | None = None  # required at publish (osp_spec.publish_diagnostics)
    # runtime-design §6a: the survey's own theme, as a full inline copy (osp_spec.theme.Theme),
    # not a reference into the lab library. A survey document then says exactly how it looks
    # wherever it goes (exports, repro packages, another lab), and editing or deleting a
    # library theme never changes a survey silently. None: the lab default, else "clean".
    theme: Theme | None = None
    # end-of-survey plan §4.1 (EN1): the ending screen per outcome. An outcome without one
    # gets the app's defaults; an ending for an outcome nothing reaches is a warning.
    endings: dict[OutcomeKey, Ending] = Field(default_factory=dict)


class Consent(Model):
    """The consent page (MVP 12b, semantics.md §11). Survey-level, not a flow node: it is
    always shown first, before any question, at most once, and nothing about the
    participant reaches the server before they agree.

    - `text`: the information and consent statement (translatable; no piping).
    - `agreeLabel` / `declineLabel`: the two buttons.
    - `declineOutcome`: the end code of a decline (`declined`). A decline records no
      response; only `countDeclines` (off by default) keeps an anonymous count.

    The consent version is the checksum of the texts as compiled (`osp_runtime.plan`), so
    any edit to the wording is a new version, recorded with each response.
    """

    text: Text
    agreeLabel: Text = "I agree"
    declineLabel: Text = "I do not agree"
    declineOutcome: Identifier = "declined"
    countDeclines: bool = False


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


# A lab's own properties on a question (planning/property-profiles.md §2.2): plain scalar
# annotations such as the construct an item measures. The runtime never reads them; the
# codebook lists them. Keys are defined by the lab's panel profile (`osp_spec.panel_profile`),
# which the survey does not depend on: any key of this shape is valid here.
type CustomKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
type CustomValue = StrictStr | StrictInt | float | StrictBool
MAX_CUSTOM_PROPERTIES = 40


class _QuestionBase(Model):
    id: Identifier
    label: Text
    help: Text | None = None
    showIf: Condition | None = None
    custom: dict[CustomKey, CustomValue] | None = Field(
        default=None, max_length=MAX_CUSTOM_PROPERTIES
    )
    source: Source | None = None  # question-bank provenance (§2.3)


class _AnswerableBase(_QuestionBase):
    name: Identifier | None = None
    required: bool = False  # only while relevant (semantics.md §4)
    constraint: Condition | None = None  # checked only on answered values
    constraintMessage: Text | None = None


class IntegerQuestion(_AnswerableBase):
    type: Literal["integer"]
    min: StrictInt | None = None  # inclusive; checked only on answered values (§4)
    max: StrictInt | None = None


class DecimalQuestion(_AnswerableBase):
    type: Literal["decimal"]
    min: StrictInt | DecimalText | None = None  # inclusive; checked only on answered values
    max: StrictInt | DecimalText | None = None


class TextQuestion(_AnswerableBase):
    type: Literal["text"]
    # Long text: a multi-line box that keeps line breaks (semantics.md §2 keeps internal
    # whitespace and line breaks either way; this only changes the input shown).
    multiline: bool = False


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


class MatrixRow(Model):
    """One row of a `matrix`: a single-choice sub-question with its own variable
    (semantics.md §2, C2c-1). `id` is unique within its matrix; the row's variable id is
    `<matrix id>_<row id>` and its export name `<matrix name>_<row id>`."""

    id: Identifier
    label: Text
    required: bool | None = None  # None: the matrix's `required`


class MatrixQuestion(_QuestionBase):
    """Rows of single-choice sub-questions sharing one choice list (the columns).

    The matrix itself stores no value: each row is its own variable with its own state
    (semantics.md §2, C2c-1). Exactly one of `choiceList` / `choices` is set, as for choice
    questions. Rows have no `showIf` or `constraint` of their own (C2c-2).
    """

    type: Literal["matrix"]
    name: Identifier | None = None  # export-name prefix of every row (default: the id)
    required: bool = False  # every row, unless the row sets its own `required`
    rows: list[MatrixRow] = Field(min_length=1)
    choiceList: Identifier | None = None
    choices: list[Choice] | None = Field(default=None, min_length=1)


class SliderQuestion(_AnswerableBase):
    """A number picked on a track from `min` to `max` in `step`s. Starts unanswered: no
    value until the participant sets one (runtime-design.md §6; semantics.md §2, C2c-3).
    Stored like an `integer` or `decimal` answer, by `valueType`."""

    type: Literal["slider"]
    valueType: Literal["integer", "decimal"] = "integer"
    min: StrictInt | DecimalText = 0  # inclusive
    max: StrictInt | DecimalText = 100  # inclusive
    step: StrictInt | DecimalText = 1  # > 0; answers lie on min + k * step
    minLabel: Text | None = None  # shown under the `min` end of the track
    maxLabel: Text | None = None


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
    | MatrixQuestion
    | SliderQuestion
    | NoteQuestion,
    Field(discriminator="type"),
]
type AnswerableQuestion = (
    IntegerQuestion
    | DecimalQuestion
    | TextQuestion
    | SingleQuestion
    | MultiQuestion
    | DateQuestion
    | SliderQuestion
)
QUESTION_TYPES = (
    "integer",
    "decimal",
    "text",
    "single",
    "multi",
    "date",
    "matrix",
    "slider",
    "note",
)


def matrix_row_id(matrix_id: str, row_id: str) -> str:
    """The variable id of one matrix row (semantics.md §2, C2c-1): `<matrix id>_<row id>`.
    Conditions and piping refer to a row by this id."""
    return f"{matrix_id}_{row_id}"


def matrix_row_name(matrix: MatrixQuestion, row_id: str) -> str:
    """The export name of one matrix row: `<matrix name>_<row id>` (C2c-1)."""
    return f"{matrix.name or matrix.id}_{row_id}"


def matrix_row_required(matrix: MatrixQuestion, row: MatrixRow) -> bool:
    """A row is required when it says so, else when the matrix is (C2c-1)."""
    return matrix.required if row.required is None else row.required


# --- Pages and blocks -------------------------------------------------------------------


class Page(Model):
    """One screen. Validation runs on page submit (semantics.md §4)."""

    id: Identifier
    title: Text | None = None  # optional heading shown above the page's items
    showIf: Condition | None = None  # false: the page is skipped, its items irrelevant (§6)
    items: list[Question] = Field(min_length=1)
    itemOrder: Order = "fixed"  # realised order fixed at first reach (semantics.md §7)
    source: Source | None = None  # question-bank provenance (§2.3)


class Block(Model):
    """A named run of pages, placed in the flow by a `block` node."""

    id: Identifier
    title: StrictStr | None = None  # builder-only label, never shown to participants
    pages: list[Page] = Field(min_length=1)
    source: Source | None = None  # question-bank provenance (§2.3)


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
    """What happens to a participant who hits a full quota (semantics.md §6): optionally
    show `block` (at most one), then end with `outcome`. There is no `goto`."""

    block: Identifier | None = None
    outcome: Identifier


class Quota(Model):
    id: Identifier
    when: Condition
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
    if_: Condition = Field(alias="if")
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
    consent: Consent | None = None  # shown before the flow (semantics.md §11)
    choiceLists: list[ChoiceList] = Field(default_factory=list)
    variables: list[Variable] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)
    quotas: list[Quota] = Field(default_factory=list)
    flow: list[FlowNode] = Field(default_factory=list)
    # runtime-design §7a: the researcher's hook manifest (osp_spec.hooks.Hooks): script,
    # handled events with their declared reads/writes, URL parameters, redirects, parent
    # messages. Published inside the plan checksum. None: the survey runs no custom code.
    hooks: Hooks | None = None


# Theme and Hooks live in theme.py / hooks.py, which build on this module's `Model`, so they
# are imported last (everything they need is defined by now) and the models that use them
# are rebuilt. `osp_spec/__init__` takes them from here, so this module always loads first.
from .hooks import HOOK_EVENTS, Hooks  # noqa: E402, F401
from .theme import Theme  # noqa: E402

for _m in (BranchNode, RandomiserNode, Settings, Survey):
    _m.model_rebuild()
