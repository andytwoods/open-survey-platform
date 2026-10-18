"""Qualtrics (``.qsf``) capability table.

One row per ``osp-survey`` schema field (``"<SchemaDef>.<field>"``), plus value refinements
(``"<SchemaDef>.<field>=<value>"``) and target behaviours that are not a single field
(``"$<name>"``), in the same shape as the XLSForm and LimeSurvey tables.
``tests/test_qsf_capabilities.py`` runs the same completeness guard. The exporter looks
levels up here, so every diagnostic it emits carries the level written in this table.

Sources (clean-room): the public Qualtrics documentation of survey flow, question types,
display logic, embedded data and piped text, and the shape of ``.qsf`` files as our own
importer reads them (``imports/qsf.py``). No Qualtrics code.
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
    "Qualtrics draws its own random order: our seed is not reproduced and the realised "
    "order is not stored in the response, so the run cannot be replayed."
)

# --- Survey root -------------------------------------------------------------------------
_row("Survey.specVersion", "native", "Not written: the .qsf is a Qualtrics export.")
_row(
    "Survey.id",
    "lowered",
    "Qualtrics survey ids are `SV_` + 15 characters: one is derived from a hash of the id. "
    "Qualtrics gives the imported survey a new id.",
)
_row("Survey.version", "unsupported", "No survey version field in Qualtrics; dropped.")
_row("Survey.metadata", "native", "Container; see Metadata.*.")
_row("Survey.settings", "native", "Container; see Settings.*.")
_row("Survey.choiceLists", "lowered", "Copied into each question's choices.")
_row("Survey.variables", "native", "Container; see the variable kinds.")
_row("Survey.blocks", "native", "Survey blocks (`BL`); pages are page breaks in the block.")
_row("Survey.quotas", "unsupported", "Qualtrics quotas are not written; set them up in Qualtrics.")
_row("Survey.flow", "native", "The survey flow (`FL`): blocks, branches, randomizers, ends.")

# --- Metadata and settings ---------------------------------------------------------------
_row("Metadata.title", "native", "`SurveyEntry.SurveyName`.")
_row(
    "Metadata.description",
    "approximated",
    "`SurveyEntry.SurveyDescription` (default language, plain text), which Qualtrics does "
    "not show to participants.",
)
_row(
    "Metadata.languages",
    "native",
    "Each question's `Language` translations; the codes are our tags upper-cased (see "
    "$language.code).",
)
_row("Metadata.defaultLanguage", "native", "`SurveyEntry.SurveyLanguage`.")
_row("Metadata.license", "unsupported", "No licence field in Qualtrics; dropped.")
_row("Metadata.ddi", "unsupported", "No study-metadata block in Qualtrics; dropped.")
_row("Settings.backNavigation", "native", "Survey option `BackButton` (true/false).")
_row("Settings.saveMode", "unsupported", "Our runtime's save mode; Qualtrics saves itself.")
_row("Settings.localCopy", "unsupported", "Our runtime's device copy; not in Qualtrics.")
_row(
    "Settings.resumeExpiryDays",
    "unsupported",
    "Our resume links; Qualtrics' partial-response deadline is a survey option set there.",
)
_row("Settings.retention", "unsupported", "Data retention is a platform policy, not the survey's.")
_row("Retention.kind", "unsupported", "See Settings.retention.")
_row("Retention.days", "unsupported", "See Settings.retention.")
_row("Retention.until", "unsupported", "See Settings.retention.")
_row("Settings.theme", "unsupported", "Our design tokens; Qualtrics themes are set there.")
for _f in ("dark", "light"):
    _row(f"Colours.{_f}", "unsupported", "See Settings.theme.")
for _f in ("accent", "background", "error", "focus", "muted", "surface", "text"):
    _row(f"Palette.{_f}", "unsupported", "See Settings.theme.")
for _f in (
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
):
    _row(f"Theme.{_f}", "unsupported", "See Settings.theme.")
_row(
    "Survey.consent",
    "approximated",
    "A first block with the consent text and a required agree / decline question; a branch "
    "ends the survey on decline. Unlike our consent page, Qualtrics records a response "
    "(with the decline) before agreement.",
)
_row("Consent.text", "lowered", "A descriptive-text question in the consent block.")
_row("Consent.agreeLabel", "lowered", "Choice 1 of the consent question.")
_row("Consent.declineLabel", "lowered", "Choice 2 of the consent question.")
_row(
    "Consent.declineOutcome",
    "approximated",
    "The decline ends the survey; the outcome is stored in the `ospoutcome` embedded field.",
)
_row(
    "Consent.countDeclines",
    "approximated",
    "Qualtrics always records the declined response; it is not left out of counts.",
)
_row(
    "Settings.endings",
    "approximated",
    "Endings per outcome (EN1): Qualtrics' end-of-survey messages live in a message library "
    "a .qsf cannot carry, so each ending is a descriptive-text block shown just before the "
    "survey ends (the participant presses Next), followed by Qualtrics' default end message.",
)
_row("Ending.title", "lowered", "The first paragraph of the ending block's text.")
_row("Ending.body", "lowered", "The paragraphs after the title; pipes become piped text.")
_row("Ending.status", "approximated", "Our status line is not written.")
_row("Ending.summary", "unsupported", "Reserved (EN5); not exported.")
_row(
    "Ending.redirect",
    "lowered",
    "End redirects (EN2): the End of Survey element's `SurveyTermination` = `Redirect` "
    "with `EOSRedirectURL`, when every param is a literal (see $redirect.piped).",
)
_row("EndRedirect.template", "lowered", "The template URL with its literal params filled in.")
_row("EndRedirect.params", "lowered", "Literal params are URL-encoded into the redirect URL.")
_row(
    "EndRedirect.delay",
    "unsupported",
    "Qualtrics redirects at once; there is no countdown.",
)
_row("EndRedirect.mode", "native", "`auto`: Qualtrics redirects automatically.")
_row(
    "EndRedirect.mode=link",
    "approximated",
    "Qualtrics always redirects automatically: a `link` redirect is not shown as a link.",
)
_row("EndRedirect.label", "unsupported", "No link text in a Qualtrics redirect; dropped.")
_row(
    "Settings.redirectTemplates",
    "lowered",
    "Redirect templates (EN2) are filled into the redirect URLs that use them.",
)
_row("RedirectTemplate.url", "lowered", "See Settings.redirectTemplates.")
_row("RedirectTemplate.params", "lowered", "See Settings.redirectTemplates.")
_row(
    "RedirectParam.pattern",
    "approximated",
    "Checked here for literal params; Qualtrics does not re-check values at run time.",
)
_row(
    "Survey.hooks",
    "unsupported",
    "Researcher hooks (custom code on key events, runtime-design.md §7a) run only in our "
    "runtime's sandbox; they are not exported (Qualtrics' question JavaScript is a "
    "different model), so the imported survey runs without them.",
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
_row("ChoiceList.id", "native", "Not written: each question gets its own choices.")
_row("ChoiceList.choices", "native", "The question's `Choices` (or a grid's `Answers`).")
_row(
    "Choice.value",
    "native",
    "The recode value (`RecodeValues`). Qualtrics recodes are numbers: a text value gets "
    "its position as the code, reported under $choice.code.",
)
_row("Choice.label", "native", "The choice's `Display` text.")

# --- Questions ---------------------------------------------------------------------------
_rows(
    QUESTIONS,
    "id",
    "native",
    "The question's `DataExportTag` when `name` is unset; see $names.* for renames.",
)
_rows(QUESTIONS, "label", "native", "`QuestionText` (HTML). Piping: see $pipe.*.")
_rows(
    QUESTIONS,
    "help",
    "lowered",
    "Qualtrics has no help text: it is a second, smaller paragraph of the question text.",
)
_rows(
    QUESTIONS,
    "custom",
    "unsupported",
    "Lab annotations from the panel profile (planning/property-profiles.md); not part of "
    "the form. They stay in the survey document and the codebook.",
)
_rows(
    QUESTIONS,
    "showIf",
    "lowered",
    "`DisplayLogic`: the condition as Or-ed sets of And-ed conditions (see $logic.*). "
    "Qualtrics leaves a hidden question unanswered, as our §3 does.",
)
_rows(ANSWERABLE, "name", "native", "The `DataExportTag`; see $names.* for renames.")
_rows(
    ANSWERABLE,
    "required",
    "native",
    "`ForceResponse` = ON; Qualtrics only enforces it on displayed questions (§4).",
)
_rows(
    ANSWERABLE,
    "constraint",
    "unsupported",
    "Qualtrics custom validation is not written; the condition is not checked there.",
)
_rows(
    ("IntegerQuestion", "DecimalQuestion"),
    "min",
    "native",
    "`ValidNumber.Min` of the content validation.",
)
_rows(
    ("IntegerQuestion", "DecimalQuestion"),
    "max",
    "native",
    "`ValidNumber.Max` of the content validation.",
)
_rows(
    ANSWERABLE,
    "constraintMessage",
    "unsupported",
    "Qualtrics shows its own validation messages; ours is not written.",
)
_row(
    "IntegerQuestion.type",
    "native",
    "Text entry (TE/SL) with content validation `ValidNumber`, `NumDecimals` = 0.",
)
_row("DecimalQuestion.type", "native", "Text entry (TE/SL) with content validation `ValidNumber`.")
_row("TextQuestion.type", "native", "Text entry, single line (TE/SL).")
_row("TextQuestion.multiline", "native", "Text entry, multiple lines (TE/ML).")
_row("SingleQuestion.type", "native", "Multiple choice, single answer (MC/SAVR).")
_row(
    "MultiQuestion.type",
    "lowered",
    "Multiple choice, multiple answer (MC/MAVR): Qualtrics stores one column per choice "
    "instead of one list of codes.",
)
_row(
    "DateQuestion.type",
    "approximated",
    "Text entry with content validation `ValidDate` (yyyy/mm/dd): no date picker, and the "
    "date is stored as the text typed.",
)

# --- Matrix and slider (C2c; semantics.md §2) ---------------------------------------------
_row(
    "MatrixQuestion.type",
    "native",
    "Matrix table, Likert, single answer (Matrix/Likert/SingleAnswer): the rows are its "
    "statements (`Choices`), the columns its scale points (`Answers`).",
)
_row("MatrixQuestion.id", "native", "The `DataExportTag` when `name` is unset.")
_row("MatrixQuestion.label", "native", "`QuestionText`.")
_row("MatrixQuestion.help", "lowered", "A second, smaller paragraph of the question text.")
_row("MatrixQuestion.custom", "unsupported", "Lab annotations; see the other question types.")
_row("MatrixQuestion.showIf", "lowered", "`DisplayLogic`; see $logic.*.")
_row(
    "MatrixQuestion.name",
    "native",
    "The `DataExportTag`; each statement's export tag (`ChoiceDataExportTags`) is its row id.",
)
_row(
    "MatrixQuestion.required",
    "native",
    "`ForceResponse` = ON when every row is required; see $matrix.someRowsRequired.",
)
_row("MatrixQuestion.rows", "native", "The statements, in order.")
_row("MatrixQuestion.choiceList", "lowered", "The shared list is copied into the scale points.")
_row("MatrixQuestion.choices", "native", "The scale points (`Answers`).")
_row("MatrixRow.id", "native", "The statement's export tag (`ChoiceDataExportTags`).")
_row("MatrixRow.label", "native", "The statement's `Display` text.")
_row("MatrixRow.required", "native", "See MatrixQuestion.required.")
_row(
    "SliderQuestion.type",
    "native",
    "Slider (Slider/HSLIDER) with one statement; an untouched slider records no value.",
)
_row("SliderQuestion.valueType", "native", "`NumDecimals` 0 for integers.")
_row("SliderQuestion.min", "native", "`CSSliderMin`.")
_row("SliderQuestion.max", "native", "`CSSliderMax`.")
_row("SliderQuestion.step", "native", "`NumDecimals`: a step of 1, 0.1, 0.01 …; see $slider.step.")
_row(
    "$slider.step",
    "approximated",
    "Qualtrics slider precision is a number of decimals: a step that is not 1, 0.1, 0.01 … "
    "becomes that precision, and answers between steps are allowed.",
)
_row("SliderQuestion.minLabel", "native", "The first slider `Labels` entry.")
_row("SliderQuestion.maxLabel", "native", "The second slider `Labels` entry.")
_row(
    "$matrix.someRowsRequired",
    "approximated",
    "`ForceResponse` is per question: when only some rows are required, none is forced.",
)
_row("NoteQuestion.type", "native", "Descriptive text (DB/TB).")
_rows(CHOICE_QUESTIONS, "choiceList", "lowered", "The shared list is copied into the question.")
_rows(CHOICE_QUESTIONS, "choices", "native", "The question's `Choices`, in `ChoiceOrder`.")
_rows(CHOICE_QUESTIONS, "choiceOrder", "native", "`fixed`: choices in `ChoiceOrder`.")
for _d in CHOICE_QUESTIONS:
    _row(
        f"{_d}.choiceOrder=shuffle",
        "approximated",
        "Choice randomisation (`Randomization` Type All). " + _UNSEEDED,
    )

# --- Pages and blocks --------------------------------------------------------------------
_row("Page.id", "lowered", "Not written: pages are page breaks inside their block.")
_row("Page.items", "native", "The block's questions up to the next page break.")
_row(
    "Page.title",
    "lowered",
    "Qualtrics pages have no title: a descriptive-text question at the top of the page.",
)
_row("Page.itemOrder", "native", "`fixed`: block order.")
_row(
    "Page.showIf",
    "lowered",
    "Qualtrics has no page logic: the condition is And-ed into every question's display "
    "logic, so the page is skipped when it holds for none.",
)
_row(
    "Page.itemOrder=shuffle",
    "approximated",
    "Qualtrics randomises question order per block (`RandomizeQuestions`), across its page "
    "breaks: written only for a one-page block, otherwise the order is fixed. " + _UNSEEDED,
)
_row("Block.id", "lowered", "The block's `ID` is `BL_` + a hash of the id.")
_row(
    "Block.title",
    "native",
    "The block's `Description` (its label in the Qualtrics editor, not shown to "
    "participants); a block without a title is described by its id.",
)
_row("Block.pages", "native", "The block's elements, pages separated by page breaks.")

# --- Variables ---------------------------------------------------------------------------
_rows(VARIABLES, "id", "native", "The embedded data field name when `name` is unset.")
_rows(VARIABLES, "name", "native", "The embedded data field name; see $names.* for renames.")
_row(
    "EmbeddedVariable.kind",
    "native",
    "An embedded data field set at the start of the flow; Qualtrics fills it from the URL "
    "query parameter of the same name.",
)
_row("EmbeddedVariable.valueType", "native", "`text`: `VariableType` String.")
for _v in ("integer", "decimal"):
    _row(
        f"EmbeddedVariable.valueType={_v}",
        "approximated",
        "`VariableType` Number; Qualtrics does not check that the URL value is a number "
        "(or a whole number).",
    )
_row("EmbeddedVariable.source", "native", "The URL query string.")
_row("EmbeddedVariable.param", "native", "The field's name; see $embedded.param.")
_row(
    "$embedded.param",
    "approximated",
    "Qualtrics reads the URL parameter named like the field, so the field is named after "
    "`param`: the data column is the parameter name, not the variable's name.",
)
_row(
    "EmbeddedVariable.default",
    "lowered",
    "A branch after the field's declaration sets the default when the URL left it empty.",
)
_row(
    "AssignedVariable.kind",
    "approximated",
    "A randomizer presenting one of several embedded data elements, each setting one level. "
    "The draw is Qualtrics' own: our seed and allocation are not reproduced.",
)
_row("AssignedVariable.levels", "lowered", "One embedded data element per level.")
_row(
    "ComputedVariable.kind",
    "unsupported",
    "Computed variables are not written (Qualtrics' embedded-data math is not our decimal "
    "arithmetic); compute them from the exported data.",
)
_row("ComputedVariable.expr", "unsupported", "See ComputedVariable.kind.")

# --- Quotas ------------------------------------------------------------------------------
_row("Quota.id", "unsupported", "See Survey.quotas.")
_row("Quota.when", "unsupported", "See Survey.quotas.")
_row("Quota.when=unmappable", "unsupported", "See Survey.quotas.")
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
    _row(f"{_d}.id", "native", "Not written: Qualtrics numbers flow elements (`FlowID`).")
_row("BlockNode.type", "native", "A flow `Block` element.")
_row("BlockNode.block", "native", "The element's block `ID`.")
_row("BranchNode.type", "native", "A flow `Branch` element.")
_row("BranchNode.if", "lowered", "`BranchLogic`, written like display logic; see $logic.*.")
_row("BranchNode.then", "native", "The branch's own flow.")
_row(
    "BranchNode.else",
    "lowered",
    "Qualtrics branches have no else: a second branch on the negated condition.",
)
_row(
    "RandomiserNode.type",
    "approximated",
    "A `BlockRandomizer` presenting its children in random order. " + _UNSEEDED,
)
_row(
    "RandomiserNode.children",
    "native",
    "The randomizer's elements; a child that is not a block is a `Group` element.",
)
_row("RandomiserNode.pick", "native", "`SubSet`: the number of elements presented.")
_row("AssignNode.type", "approximated", "See AssignedVariable.kind.")
_row("AssignNode.variables", "approximated", "One randomizer per listed variable.")
_row("QuotaCheckNode.type", "unsupported", "Quotas are not exported (see Survey.quotas).")
_row("QuotaCheckNode.quota", "unsupported", "See QuotaCheckNode.type.")
for _f in ("type", "template", "params", "returns"):
    _row(
        f"ExternalTaskNode.{_f}",
        "unsupported",
        "The hop to an external task and back is not written (Qualtrics would need an "
        "authenticated return link); the survey runs straight on.",
    )
_row("EndNode.type", "native", "An `EndSurvey` element.")
_row(
    "EndNode.outcome",
    "lowered",
    "`screened_out` is the Screened response flag; any other outcome but `complete` is "
    "stored in the `ospoutcome` embedded field set just before the end.",
)
_row(
    "EndNode.message",
    "approximated",
    "A descriptive-text block shown just before the end (the participant presses Next).",
)

# --- Expressions (osp-expr AST): only what display and branch logic can say -------------
_row("IntLit.kind", "native", "A number operand.")
_row("IntLit.value", "native", "Written as digits.")
_row("DecLit.kind", "native", "A number operand.")
_row("DecLit.value", "native", "Written in plain notation (no exponent).")
_row("TextLit.kind", "native", "A text operand.")
_row("TextLit.value", "native", "Written as it is.")
_row("BoolLit.kind", "lowered", "`true` drops the condition; `false` cannot be written.")
_row("BoolLit.value", "lowered", "See BoolLit.kind.")
_row("NullLit.kind", "lowered", "Only as `answered`: Empty / Not Empty.")
_row("Ref.kind", "native", "The question (`QID`), statement or embedded field it names.")
_row("Ref.id", "native", "Rewritten to the question's QID or the field name.")
_row(
    "Compare.kind",
    "lowered",
    "Against a literal only: Selected / Not Selected on a choice (or a grid cell), Is "
    "Equal To, Greater Than … on a text, number or slider entry or an embedded field. "
    "Anything else cannot be written ($logic.unmappable).",
)
_row("Compare.op", "native", "`== != < <= > >=`: Equal To, Not Equal To, Less Than …")
_row("Compare.left", "native", "Operand.")
_row("Compare.right", "native", "Operand.")
_row(
    "Arith.kind",
    "unsupported",
    "Display and branch logic cannot compute: a condition with arithmetic is not written "
    "($logic.unmappable).",
)
_row("Arith.op", "unsupported", "See Arith.kind.")
_row("Arith.left", "unsupported", "See Arith.kind.")
_row("Arith.right", "unsupported", "See Arith.kind.")
_row("And.kind", "lowered", "`And` conjunctions, after rewriting the condition as Or of Ands.")
_row("And.args", "native", "Operands.")
_row("Or.kind", "lowered", "`Or` conjunctions between condition sets.")
_row("Or.args", "native", "Operands.")
_row(
    "Not.kind",
    "lowered",
    "Pushed down to the conditions: Selected ↔ Not Selected, Empty ↔ Not Empty; other "
    "negations cannot be written ($logic.unmappable).",
)
_row("Not.arg", "native", "Operand.")
_row(
    "Answered.kind",
    "lowered",
    "Not Empty on a text, number or slider entry or an embedded field; for a choice "
    "question, any choice Selected.",
)
_row("Answered.ref", "native", "The question or field.")
_row(
    "If.kind",
    "unsupported",
    "Display and branch logic have no if-then-else: not written ($logic.unmappable).",
)
_row("If.cond", "unsupported", "See If.kind.")
_row("If.then", "unsupported", "See If.kind.")
_row("If.else", "unsupported", "See If.kind.")
_row("Contains.kind", "native", "Selected on the choice of a multiple-answer question.")
_row("Contains.ref", "native", "The question.")
_row("Contains.value", "native", "The choice.")

# --- Rich text (planning/rich-text.md §3 and §8) -------------------------------------------
_row(
    "RichText.type",
    "native",
    "Written as HTML, which Qualtrics texts are: `<p>`, `<h3>`–`<h5>`, `<ul>` / `<ol>`, "
    "`<strong>`, `<em>`, `<a>`, `<span lang>`, `<br />`; the text itself escaped "
    "($text.markup).",
)
_row(
    "RichText.blocks",
    "native",
    "One element per block. A lone paragraph has no `<p>` wrapper, so one-line fields "
    "(choices, statements) stay one line.",
)
_row("Paragraph.type", "native", "`<p>` (none around a lone paragraph).")
_row("Paragraph.content", "native", "The paragraph's runs.")
_row(
    "Heading.type",
    "lowered",
    "`<h3>`, `<h4>` or `<h5>` (level + 2); the size is absolute, not relative to the page.",
)
_row("Heading.level", "native", "See Heading.type.")
_row("Heading.content", "native", "The heading's runs.")
_row("RichList.type", "native", "`<ul>` or `<ol>` of `<li>` items.")
_row("RichList.items", "native", "See RichList.type.")
_row("TextRun.text", "native", "The run's text, HTML-escaped ($text.markup).")
_row("TextRun.marks", "native", "`<strong>` / `<em>`.")
_row(
    "TextRun.href",
    "native",
    '`<a href="https://…" target="_blank" rel="noopener noreferrer">`; adjacent runs with '
    "the same URL are one link.",
)
_row("TextRun.lang", "native", '`<span lang="…">`.')
_row("PipeRun.pipe", "native", "Piped text, as `${id}` in plain text (see $pipe.*).")
_row("LineBreak.br", "native", "`<br />`.")
_row("$rich.bold", "native", "See TextRun.marks.")
_row("$rich.italic", "native", "See TextRun.marks.")
_row("$rich.link", "native", "See TextRun.href.")
_row("$rich.heading", "lowered", "See Heading.type.")
_row("$rich.list", "native", "See RichList.type.")
_row("$rich.break", "native", "See LineBreak.br.")
_row("$rich.lang", "native", "See TextRun.lang.")

# --- Behaviours that are not a single field ----------------------------------------------
_row(
    "$pipe.value",
    "native",
    "Piped text: `${q://QIDn/ChoiceTextEntryValue}` for a text or number entry, "
    "`${q://QIDn/ChoiceNumericEntryValue/1}` for a slider, `${e://Field/name}` for an "
    "embedded field.",
)
_row(
    "$pipe.builtin",
    "unsupported",
    "`${$trial}`, `${$position.index}` … are our runtime's built-ins; dropped from the text.",
)
_row(
    "$pipe.choiceLabel",
    "native",
    "Piping a single-choice question: `${q://QIDn/ChoiceGroup/SelectedChoices}` inserts the label.",
)
_row(
    "$pipe.multi",
    "approximated",
    "Piping a multiple-answer question inserts the selected labels, comma separated.",
)
_row(
    "$pipe.unsupported",
    "unsupported",
    "A pipe of a grid row or a computed variable cannot be written "
    "as piped text; dropped from the text.",
)
_row(
    "$pipe.escaping",
    "approximated",
    "Qualtrics inserts piped answers as they were typed; whether it escapes HTML in them is "
    "not documented.",
)
_row(
    "$text.markup",
    "lowered",
    "Qualtrics texts are HTML: `&`, `<`, `>` are escaped so the text shows as written.",
)
_row(
    "$text.controlCharacters",
    "approximated",
    "Control characters are dropped from texts.",
)
_row(
    "$names.rename",
    "lowered",
    "Export tags and field names here start with a letter and hold only letters, digits "
    "and `_`, unique ignoring case; other names are rewritten. The mapping is in the "
    "export's `name_map`.",
)
_row(
    "$names.reserved",
    "lowered",
    "A name equal to a Qualtrics response column (`ResponseId`, `StartDate`, `Finished`, "
    "`Progress`, ...) is renamed. The mapping is in the export's `name_map`.",
)
_row(
    "$choice.code",
    "lowered",
    "A choice value that is not a whole number (a text code) is coded by its position; the "
    "mapping is in the export's `choice_codes`.",
)
_row(
    "$language.code",
    "approximated",
    "Qualtrics has its own list of language codes (`EN`, `DE`, `ES-ES`, `PT-BR`, `ZH-S` "
    "…): a tag with a region or script is upper-cased and may need choosing again there.",
)
_row(
    "$logic.unmappable",
    "unsupported",
    "The condition cannot be written as Qualtrics logic (see Compare.kind, Not.kind): a "
    "question is shown always; a branch's arms both run for everyone.",
)
_row(
    "$redirect.piped",
    "unsupported",
    "An end redirect with a piped parameter (EN2) is not exported: Qualtrics cannot "
    "re-check the value against the template's pattern before sending it.",
)
_row(
    "$missingStates",
    "approximated",
    "Qualtrics leaves not-reached, hidden and unanswered all empty (§1); telling them apart "
    "needs the survey logic replayed (osp-engine).",
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
    "The instruments used (citation, licence), derived at publish; listed in the codebook, "
    "not written to the form. Cite them in the study documentation.",
)
for _def, _fields in (
    ("Instrument", ("bank", "version", "library", "title", "abbreviation", "licence", "citation")),
    ("InstrumentLicence", ("class", "holder", "statement", "url", "evidenceDate")),
    ("InstrumentCitation", ("text", "doi")),
):  # fmt: skip
    for _f in _fields:
        _row(f"{_def}.{_f}", "unsupported", "See Metadata.instruments.")

QSF: dict[str, Capability] = {}
for _key, _level, _note in _ROWS:
    if _key in QSF:  # pragma: no cover - caught by the tests
        raise ValueError(f"duplicate capability row {_key}")
    QSF[_key] = Capability(_level, _note)

__all__ = ["QSF"]
