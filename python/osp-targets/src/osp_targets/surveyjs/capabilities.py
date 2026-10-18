"""SurveyJS survey JSON capability table (task XP1).

One row per ``osp-survey`` schema field (``"<SchemaDef>.<field>"``), plus value refinements
(``"<SchemaDef>.<field>=<value>"``) and target behaviours that are not a single field
(``"$<name>"``), in the same shape as the XLSForm and LimeSurvey tables.
``tests/test_surveyjs_capabilities.py`` runs the same completeness guard. The exporter
looks levels up here, so every diagnostic it emits carries the level written in this table.

Sources (clean-room): the public SurveyJS documentation of the survey JSON (``pages`` of
``elements``, question types and properties, localisable strings, expressions,
``calculatedValues``, ``completedHtmlOnCondition``, ``navigateToUrlOnCondition``) and our
own importer (``osp_targets/imports/surveyjs.py``). No SurveyJS code.
"""

from __future__ import annotations

from ..capabilities.base import Capability, Level

_ROWS: list[tuple[str, Level, str]] = []


def _row(key: str, level: Level, note: str) -> None:
    _ROWS.append((key, level, note))


def _rows(defs: tuple[str, ...], field: str, level: Level, note: str) -> None:
    for d in defs:
        _row(f"{d}.{field}", level, note)


ANSWERABLE = (
    "SliderQuestion",
    "IntegerQuestion",
    "DecimalQuestion",
    "TextQuestion",
    "SingleQuestion",
    "MultiQuestion",
    "DateQuestion",
)
QUESTIONS = (*ANSWERABLE, "NoteQuestion")
CHOICE_QUESTIONS = ("SingleQuestion", "MultiQuestion")
VARIABLES = ("EmbeddedVariable", "AssignedVariable", "ComputedVariable")

_UNSEEDED = (
    "SurveyJS draws its own random order in the browser: our seed is not reproduced and the "
    "realised order is not stored in the response, so the run cannot be replayed."
)
_PLAIN_TITLES = (
    "SurveyJS shows titles, descriptions and choice texts as plain text, so formatting is "
    "kept only in notes (`html` elements) and the completion texts."
)

# --- Survey root -------------------------------------------------------------------------
_row("Survey.specVersion", "native", "Not written: the JSON has no format version.")
_row("Survey.id", "native", "Not written: a SurveyJS survey is identified by its host.")
_row("Survey.version", "unsupported", "No survey version field in SurveyJS; dropped.")
_row("Survey.metadata", "native", "Container; see Metadata.*.")
_row("Survey.settings", "native", "Container; see Settings.*.")
_row("Survey.choiceLists", "lowered", "Copied into each question's `choices`.")
_row("Survey.variables", "native", "Container; see the variable kinds.")
_row("Survey.blocks", "lowered", "Each page of a block in the flow becomes a SurveyJS page.")
_row("Survey.quotas", "unsupported", "SurveyJS has no quotas (they need a server); dropped.")
_row("Survey.flow", "lowered", "The flow tree becomes page `visibleIf` conditions.")

# --- Metadata and settings ---------------------------------------------------------------
_row("Metadata.title", "native", "`title`.")
_row("Metadata.description", "native", "`description`.")
_row(
    "Metadata.languages",
    "native",
    'Every text is a localisable string `{"default": …, "<lang>": …}` when the survey has '
    "more than one language; a missing translation falls back to the default.",
)
_row("Metadata.defaultLanguage", "native", "The `default` texts; `locale` when it is not `en`.")
_row("Metadata.license", "unsupported", "No licence field in SurveyJS; dropped.")
_row("Metadata.ddi", "unsupported", "No study-metadata block in SurveyJS; dropped.")
_row("Settings.backNavigation", "native", "`showPrevButton`.")
_row("Settings.saveMode", "unsupported", "Our runtime's save mode; SurveyJS saving is the host's.")
_row("Settings.localCopy", "unsupported", "Our runtime's device copy; not in SurveyJS.")
_row("Settings.resumeExpiryDays", "unsupported", "Our resume links; not in SurveyJS.")
_row("Settings.retention", "unsupported", "Data retention is a platform policy, not the survey's.")
for _f in ("kind", "days", "until"):
    _row(f"Retention.{_f}", "unsupported", "See Settings.retention.")
_row("Settings.theme", "unsupported", "Our design tokens; SurveyJS themes are separate JSON.")
for _key in (
    "Colours.dark",
    "Colours.light",
    *(
        f"Palette.{f}"
        for f in ("accent", "background", "error", "focus", "muted", "surface", "text")
    ),
    *(
        f"Theme.{f}"
        for f in (
            "baseSize",
            "buttonStyle",
            "choiceStyle",
            "colours",
            "density",
            "font",
            "headerText",
            "lineSpacing",
            "logoAssetId",
            "mode",
            "preset",
            "radius",
            "themeVersion",
        )
    ),
):
    _row(_key, "unsupported", "See Settings.theme.")
_row(
    "Survey.consent",
    "unsupported",
    "Our runtime's consent page (no data before agreement); not written, so the exported "
    "survey has no consent gate. Add an equivalent first question by hand.",
)
for _f in ("text", "agreeLabel", "declineLabel", "declineOutcome", "countDeclines"):
    _row(f"Consent.{_f}", "unsupported", "See Survey.consent.")
_row(
    "Settings.endings",
    "approximated",
    "Each outcome's ending becomes a completion text (`completedHtml`, or an entry of "
    "`completedHtmlOnCondition` for the path that reaches it); the app's own status line is "
    "not shown.",
)
_row("Ending.title", "lowered", "A heading at the top of the completion text.")
_row("Ending.body", "lowered", "The completion text under the title; pipes become `{name}`.")
_row(
    "Ending.status",
    "approximated",
    "SurveyJS shows no 'Your answers have been sent' line of its own; the host decides.",
)
_row("Ending.summary", "unsupported", "SurveyJS has no answer summary on the completion page.")
_row(
    "Ending.redirect",
    "approximated",
    "`navigateToUrl` (or `navigateToUrlOnCondition` for that path): SurveyJS goes there at "
    "once, with no countdown or button.",
)
_row("EndRedirect.template", "lowered", "The template URL with its literal params filled in.")
_row(
    "EndRedirect.params",
    "approximated",
    "Literal values are percent-encoded into the URL; a piped value is a loss ($redirect.piped).",
)
_row("EndRedirect.delay", "unsupported", "SurveyJS navigates at once; the delay is dropped.")
_row("EndRedirect.mode", "approximated", "Both modes navigate at once (no 'Stay on this page').")
_row("EndRedirect.label", "unsupported", "No button: SurveyJS navigates without one.")
_row("Settings.redirectTemplates", "lowered", "Not written: each redirect is a filled URL.")
_row("RedirectTemplate.url", "lowered", "See Settings.redirectTemplates.")
_row("RedirectTemplate.params", "lowered", "See Settings.redirectTemplates.")
_row(
    "RedirectParam.pattern",
    "approximated",
    "Checked against the literal value at export; nothing re-checks it in SurveyJS.",
)
_row(
    "Survey.hooks",
    "unsupported",
    "Our sandboxed researcher hooks; SurveyJS custom code is the host page's JavaScript.",
)
for _def, _fields in (
    ("Hooks", ("format", "source", "handlers", "urlParams", "redirects", "parent",
               "exportsConfirmedFor")),
    ("HookHandler", ("reads", "writes", "timeoutMs")),
    ("HookParent", ("origin", "messages")),
    ("HookStringSchema", ("type", "maxLength", "pattern", "enum")),
    ("HookNumberSchema", ("type", "minimum", "maximum")),
    ("HookBooleanSchema", ("type",)),
    ("HookNullSchema", ("type",)),
    ("HookObjectSchema", ("type", "properties", "required")),
    ("HookArraySchema", ("type", "items", "maxItems")),
):  # fmt: skip
    for _f in _fields:
        _row(f"{_def}.{_f}", "unsupported", "See Survey.hooks.")

# --- Choices -----------------------------------------------------------------------------
_row("ChoiceList.id", "native", "Not written: each question gets its own `choices`.")
_row("ChoiceList.choices", "native", "The question's `choices` (or a matrix's `columns`).")
_row("Choice.value", "native", "The item `value`: a JSON number or string, as ours.")
_row("Choice.label", "native", "The item `text`. " + _PLAIN_TITLES)

# --- Questions ---------------------------------------------------------------------------
_rows(QUESTIONS, "id", "native", "The element `name` when `name` is unset.")
_rows(QUESTIONS, "label", "native", "`title` (`html` for a note). " + _PLAIN_TITLES)
_rows(QUESTIONS, "help", "native", "`description`.")
_rows(
    QUESTIONS,
    "custom",
    "unsupported",
    "Lab annotations (panel profiles) are not part of the form; they stay in the survey "
    "document and the codebook.",
)
_rows(QUESTIONS, "showIf", "native", "`visibleIf`; see the expression rows.")
_rows(ANSWERABLE, "name", "native", "The element `name` (the data key).")
_rows(ANSWERABLE, "required", "native", "`isRequired`; SurveyJS checks only visible questions.")
_rows(
    ANSWERABLE,
    "constraint",
    "lowered",
    "An `expression` validator `{q} empty or (…)`, so it is checked only on answered values.",
)
_rows(
    ("IntegerQuestion", "DecimalQuestion"),
    "min",
    "lowered",
    "`min` and a `numeric` validator's `minValue`.",
)
_rows(
    ("IntegerQuestion", "DecimalQuestion"),
    "max",
    "lowered",
    "`max` and a `numeric` validator's `maxValue`.",
)
_rows(ANSWERABLE, "constraintMessage", "native", "The validator's `text`, per language.")
_row(
    "IntegerQuestion.type",
    "lowered",
    'A `text` element with `inputType: "number"`, `step: 1` and a `regex` validator for '
    "whole numbers.",
)
_row(
    "DecimalQuestion.type",
    "approximated",
    'A `text` element with `inputType: "number"`: SurveyJS stores a JavaScript number, so '
    "a value with more than about 15 significant digits loses precision.",
)
_row("TextQuestion.type", "native", "A `text` element.")
_row("TextQuestion.multiline", "native", "A `comment` element (multi-line box).")
_row("SingleQuestion.type", "native", "A `radiogroup` element.")
_row("MultiQuestion.type", "native", "A `checkbox` element; the answer is an array of values.")
_row("DateQuestion.type", "native", 'A `text` element with `inputType: "date"` (YYYY-MM-DD).')

# --- Matrix and slider (C2c; semantics.md §2) ---------------------------------------------
_row(
    "MatrixQuestion.type",
    "native",
    "A `matrix` element; the answer is an object {row value: column value}, and a row is "
    "read as `{grid.row}`.",
)
_row("MatrixQuestion.id", "native", "The element `name` when `name` is unset.")
_row("MatrixQuestion.label", "native", "`title`. " + _PLAIN_TITLES)
_row("MatrixQuestion.help", "native", "`description`.")
_row("MatrixQuestion.custom", "unsupported", "Lab annotations; see the other question types.")
_row("MatrixQuestion.showIf", "native", "`visibleIf`.")
_row(
    "MatrixQuestion.name",
    "native",
    "The element `name`; our row variable `<name>_<row>` is the row `<row>` of its answer.",
)
_row(
    "MatrixQuestion.required",
    "native",
    "`isAllRowRequired` when every row is required; see $matrix.someRowsRequired.",
)
_row("MatrixQuestion.rows", "native", "`rows`, each `{value: <row id>, text}`.")
_row("MatrixQuestion.choiceList", "lowered", "The shared list is copied into the `columns`.")
_row("MatrixQuestion.choices", "native", "`columns`.")
_row("MatrixRow.id", "native", "The row `value`.")
_row("MatrixRow.label", "native", "The row `text`.")
_row("MatrixRow.required", "native", "See MatrixQuestion.required.")
_row(
    "$matrix.someRowsRequired",
    "lowered",
    "Only some rows required: an `expression` validator that those rows are answered.",
)
_row(
    "SliderQuestion.type",
    "approximated",
    "A `slider` element (SurveyJS 2.3 and later; older versions need the nouislider "
    "widget). It may start at a value rather than unanswered.",
)
_row("SliderQuestion.valueType", "native", "`integer`: whole-number `min`, `max` and `step`.")
_row("SliderQuestion.min", "native", "`min`.")
_row("SliderQuestion.max", "native", "`max`.")
_row("SliderQuestion.step", "native", "`step`.")
_row("SliderQuestion.minLabel", "unsupported", "No end labels are written; dropped.")
_row("SliderQuestion.maxLabel", "unsupported", "No end labels are written; dropped.")
_row("NoteQuestion.type", "native", "An `html` element.")
_rows(CHOICE_QUESTIONS, "choiceList", "lowered", "The shared list is copied into the question.")
_rows(CHOICE_QUESTIONS, "choices", "native", "`choices`.")
_rows(CHOICE_QUESTIONS, "choiceOrder", "native", "`fixed`: choices in written order.")
for _d in CHOICE_QUESTIONS:
    _row(
        f"{_d}.choiceOrder=shuffle",
        "approximated",
        '`choicesOrder: "random"`. ' + _UNSEEDED,
    )

# --- Pages and blocks --------------------------------------------------------------------
_row("Page.id", "native", "The page `name`.")
_row("Page.items", "native", "The page's `elements`, in order.")
_row("Page.title", "native", "The page `title`. " + _PLAIN_TITLES)
_row("Page.itemOrder", "native", "`fixed`: elements in written order.")
_row("Page.showIf", "native", "Joined into the page's `visibleIf`.")
_row("Page.itemOrder=shuffle", "approximated", '`questionsOrder: "random"`. ' + _UNSEEDED)
_row("Block.id", "lowered", "Not written: its pages become consecutive pages.")
_row("Block.title", "native", "Builder-only label; not exported, as in our runtime.")
_row("Block.pages", "lowered", "Consecutive pages sharing the block's `visibleIf`.")

# --- Variables ---------------------------------------------------------------------------
_rows(VARIABLES, "id", "native", "The variable name when `name` is unset.")
_rows(VARIABLES, "name", "native", "The variable name, read as `{name}`.")
_row(
    "EmbeddedVariable.kind",
    "approximated",
    "Not written: SurveyJS reads `{name}` as a survey variable, which the host page must "
    "set (from the URL) before the survey starts.",
)
_row("EmbeddedVariable.valueType", "approximated", "See EmbeddedVariable.kind.")
_row("EmbeddedVariable.source", "approximated", "See EmbeddedVariable.kind.")
_row("EmbeddedVariable.param", "approximated", "See EmbeddedVariable.kind.")
_row("EmbeddedVariable.default", "unsupported", "No default for a host-set variable; dropped.")
_row(
    "AssignedVariable.kind",
    "unsupported",
    "A between-subjects condition fixed by our server at session start; SurveyJS has no "
    "server-side assignment, so the variable and the conditions on it are dropped.",
)
_row("AssignedVariable.levels", "unsupported", "See AssignedVariable.kind.")
_row("ComputedVariable.kind", "lowered", "A `calculatedValues` entry (`includeIntoResult`).")
_row(
    "ComputedVariable.expr",
    "approximated",
    "The SurveyJS expression; an unanswered input may read as empty or 0 rather than giving "
    "null, and division by zero is not null.",
)

# --- Quotas ------------------------------------------------------------------------------
_row("Quota.id", "unsupported", "See Survey.quotas.")
_row("Quota.when", "unsupported", "See Survey.quotas.")
_row("Quota.limit", "unsupported", "See Survey.quotas.")
_row("Quota.countOn", "unsupported", "See Survey.quotas.")
_row("Quota.onFull", "unsupported", "See Survey.quotas.")
_row("QuotaFull.block", "unsupported", "See Survey.quotas.")
_row("QuotaFull.outcome", "unsupported", "See Survey.quotas.")

# --- Flow --------------------------------------------------------------------------------
for _d in (
    "BlockNode",
    "BranchNode",
    "RandomiserNode",
    "AssignNode",
    "QuotaCheckNode",
    "ExternalTaskNode",
    "EndNode",
):
    _row(f"{_d}.id", "native", "Not written.")
_row("BlockNode.type", "lowered", "Page `visibleIf` is the flow path to the node.")
_row("BlockNode.block", "native", "The referenced block's pages are emitted at this point.")
_row("BranchNode.type", "lowered", "Branch arms become page `visibleIf` conditions.")
_row("BranchNode.if", "lowered", "ANDed into the `then` pages; its negation into the `else` pages.")
_row("BranchNode.then", "lowered", "Emitted in place with the branch condition.")
_row("BranchNode.else", "lowered", "Emitted in place with the negated condition.")
_row(
    "RandomiserNode.type",
    "approximated",
    "SurveyJS has no random order of pages or blocks we can seed: every child is shown, "
    "in written order.",
)
_row("RandomiserNode.children", "approximated", "See RandomiserNode.type.")
_row(
    "RandomiserNode.pick",
    "approximated",
    "See RandomiserNode.type: all children are shown, not `pick` of them.",
)
_row("AssignNode.type", "unsupported", "See AssignedVariable.kind.")
_row("AssignNode.variables", "unsupported", "See AssignedVariable.kind.")
_row("QuotaCheckNode.type", "unsupported", "See Survey.quotas.")
_row("QuotaCheckNode.quota", "unsupported", "See Survey.quotas.")
for _f in ("type", "template", "params", "returns"):
    _row(
        f"ExternalTaskNode.{_f}",
        "unsupported",
        "SurveyJS cannot leave the survey to run an external task and resume; the hop is dropped.",
    )
_row(
    "EndNode.type",
    "approximated",
    "SurveyJS ends after its last visible page: pages after an end on that path are hidden, "
    "and the participant still presses Complete.",
)
_row(
    "EndNode.outcome",
    "lowered",
    "Recorded in the calculated value `osp_outcome` when any end has another outcome.",
)
_row(
    "EndNode.message",
    "lowered",
    "The completion text of that path (`completedHtmlOnCondition`), above its ending.",
)

# --- Expressions (osp-expr AST) ----------------------------------------------------------
_row("IntLit.kind", "native", "Number.")
_row("IntLit.value", "native", "Written as digits.")
_row(
    "DecLit.kind",
    "approximated",
    "A JavaScript number: more than about 15 significant digits lose precision.",
)
_row("DecLit.value", "native", "Written in plain notation (no exponent).")
_row("TextLit.kind", "native", "String literal in single quotes.")
_row("TextLit.value", "native", "Quotes and backslashes escaped with a backslash.")
_row("BoolLit.kind", "native", "`true` / `false`.")
_row("BoolLit.value", "native", "See BoolLit.kind.")
_row("NullLit.kind", "approximated", "`null`; SurveyJS may treat it as empty rather than missing.")
_row("Ref.kind", "native", "`{name}`; a matrix row is `{grid.row}`.")
_row("Ref.id", "native", "Rewritten to the element or variable name.")
_row(
    "Compare.kind",
    "lowered",
    "Comparisons other than `==` with a literal are guarded with `{q} notempty`, so a "
    "comparison with a missing value is false (semantics.md §3).",
)
_row("Compare.op", "native", "`= <> < <= > >=`.")
_row("Compare.left", "native", "Operand.")
_row("Compare.right", "native", "Operand.")
_row(
    "Arith.kind",
    "approximated",
    "`+ - * /`; arithmetic with an empty value or a division by zero does not give null.",
)
_row("Arith.op", "native", "`+ - * /`.")
_row("Arith.left", "native", "Operand.")
_row("Arith.right", "native", "Operand.")
_row("And.kind", "native", "`and`.")
_row("And.args", "native", "Operands.")
_row("Or.kind", "native", "`or`.")
_row("Or.args", "native", "Operands.")
_row("Not.kind", "native", "`!`.")
_row("Not.arg", "native", "Operand.")
_row("Answered.kind", "native", "`{q} notempty`.")
_row("Answered.ref", "native", "The element name.")
_row("If.kind", "native", "`iif(cond, a, b)`.")
_row("If.cond", "native", "The condition.")
_row("If.then", "native", "The value.")
_row("If.else", "native", "The value.")
_row("Contains.kind", "native", "`{q} contains <value>` on the checkbox's array.")
_row("Contains.ref", "native", "The element name.")
_row("Contains.value", "native", "The choice value.")

# --- Rich text (planning/rich-text.md §3 and §8, tasks RT2 and RT4) -----------------------
_row("RichText.type", "native", "HTML in notes and completion texts; see $rich.* elsewhere.")
_row("RichText.blocks", "native", "See RichText.type.")
_row("Paragraph.type", "native", "`<p>` (none around a lone paragraph).")
_row("Paragraph.content", "native", "The paragraph's runs.")
_row("Heading.type", "lowered", "`<h3>`–`<h5>` (under the page's own heading).")
_row("Heading.level", "native", "See Heading.type.")
_row("Heading.content", "native", "The heading's runs.")
_row("RichList.type", "native", "`<ul>` or `<ol>` of `<li>` items.")
_row("RichList.items", "native", "See RichList.type.")
_row("TextRun.text", "native", "The run's text, HTML-escaped in HTML texts.")
_row("TextRun.marks", "native", "`<strong>` / `<em>` in HTML texts; see $rich.bold elsewhere.")
_row("TextRun.href", "native", "`<a href …>` in HTML texts; see $rich.link elsewhere.")
_row("TextRun.lang", "native", '`<span lang="…">` in HTML texts; see $rich.lang elsewhere.')
_row("PipeRun.pipe", "native", "A pipe node is written as `{name}`, like `${id}` in plain text.")
_row("LineBreak.br", "native", "`<br />` in HTML texts; see $rich.break elsewhere.")
# A formatted text in a field SurveyJS shows as plain text (titles, descriptions, choices).
_row("$rich.bold", "approximated", "Bold is dropped. " + _PLAIN_TITLES)
_row("$rich.italic", "approximated", "Italic is dropped. " + _PLAIN_TITLES)
_row("$rich.link", "approximated", "The link text is kept, the address dropped. " + _PLAIN_TITLES)
_row("$rich.heading", "lowered", "A heading becomes its text. " + _PLAIN_TITLES)
_row(
    "$rich.list", "approximated", "List items become lines starting '- ' or '1. '. " + _PLAIN_TITLES
)
_row("$rich.break", "approximated", "A line break is a newline, which SurveyJS may not show.")
_row("$rich.lang", "approximated", "The language span is dropped. " + _PLAIN_TITLES)

# --- Behaviours that are not a single field ----------------------------------------------
_row("$pipe.value", "native", "`{name}` in a text inserts the answer (§8).")
_row(
    "$pipe.builtin",
    "unsupported",
    "Our runtime's built-ins (`${$trial}`, `${$position.*}`) have no SurveyJS counterpart; "
    "the pipe is dropped.",
)
_row("$pipe.choiceLabel", "native", "`{name}` on a choice question shows the choice text.")
_row(
    "$pipe.multi",
    "approximated",
    "`{name}` on a checkbox shows SurveyJS's own comma-separated list of choice texts.",
)
_row("$pipe.escaping", "native", "A piped answer is shown as text, never as HTML.")
_row("$text.markup", "lowered", "`<`, `>` and `&` are escaped in HTML texts.")
_row(
    "$text.braces",
    "approximated",
    "SurveyJS reads `{…}` in a text as a piped value; a literal `{name}` may show an answer.",
)
_row("$text.controlCharacters", "approximated", "Control characters are removed.")
_row(
    "$expr.unmappable",
    "unsupported",
    "A condition or value that reads something SurveyJS does not have (an assigned "
    "variable, a quota): the condition is dropped (a branch then always takes `then`).",
)
_row(
    "$redirect.piped",
    "unsupported",
    "A redirect param that pipes a value is not exported (nothing would check it against "
    "its pattern); the redirect is dropped.",
)
_row(
    "$missingStates",
    "approximated",
    "SurveyJS data leaves an unanswered or hidden question out; it does not tell "
    "irrelevant, unanswered and not reached apart (semantics.md §1).",
)

# --- Question-bank provenance (planning/question-bank.md §2.3, §5) -----------------------
for _d in (*QUESTIONS, "MatrixQuestion", "Page", "Block"):
    _row(
        f"{_d}.source",
        "unsupported",
        "Question-bank provenance annotation (which bank item and version this came from), "
        "not part of the form; it stays in the survey document and the codebook.",
    )
for _f in ("bank", "version", "library", "item", "checksum"):
    _row(f"Source.{_f}", "unsupported", "See Page.source.")
_row(
    "Metadata.instruments",
    "unsupported",
    "The instruments used (derived from `source`); kept in the survey document, the "
    "codebook and the pre-registration export.",
)
for _def, _fields in (
    ("Instrument", ("bank", "version", "library", "title", "abbreviation", "licence", "citation")),
    ("InstrumentLicence", ("class", "holder", "statement", "url", "evidenceDate")),
    ("InstrumentCitation", ("text", "doi")),
):  # fmt: skip
    for _f in _fields:
        _row(f"{_def}.{_f}", "unsupported", "See Metadata.instruments.")

SURVEYJS: dict[str, Capability] = {}
for _key, _level, _note in _ROWS:
    if _key in SURVEYJS:  # pragma: no cover - caught by the tests
        raise ValueError(f"duplicate capability row {_key}")
    SURVEYJS[_key] = Capability(_level, _note)

__all__ = ["SURVEYJS"]
