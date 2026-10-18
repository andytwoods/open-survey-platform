"""XLSForm (ODK / Enketo / KoboToolbox) capability table.

One row per ``osp-survey`` schema field (``"<SchemaDef>.<field>"``), plus value refinements
(``"<SchemaDef>.<field>=<value>"``) and target-specific behaviours that are not a single
field (``"$<name>"``). ``tests/test_capabilities.py`` fails when a schema field has no row
or a row names a field that no longer exists. The exporter looks levels up here, so every
diagnostic it emits carries the level written in this table.

Sources: ODK XForms and XLSForm documentation, and the Enketo spike
(``spikes/spike-enketo/FINDINGS.md``, E4-E9).
"""

from __future__ import annotations

from .base import Capability, Level

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
# ANSWERABLE rows cover SliderQuestion's shared fields; its own rows are below.
CHOICE_QUESTIONS = ("SingleQuestion", "MultiQuestion")
VARIABLES = ("EmbeddedVariable", "AssignedVariable", "ComputedVariable")

# --- Survey root -------------------------------------------------------------------------
_row("Survey.specVersion", "native", "Not written: the workbook format carries its own version.")
_row("Survey.id", "native", "settings `form_id`.")
_row("Survey.version", "native", "settings `version` (as text).")
_row("Survey.metadata", "native", "Container; see Metadata.*.")
_row("Survey.settings", "native", "Container; see Settings.*.")
_row("Survey.choiceLists", "native", "choices sheet, one `list_name` per list.")
_row("Survey.variables", "native", "Container; see the variable kinds.")
_row("Survey.blocks", "lowered", "Each block in the flow becomes a `begin group`.")
_row("Survey.quotas", "unsupported", "XLSForm has no quotas (review.md §2.4).")
_row("Survey.flow", "lowered", "The flow tree becomes `relevant` expressions on block groups.")

# --- Metadata and settings ---------------------------------------------------------------
_row("Metadata.title", "native", "settings `form_title`.")
_row(
    "Metadata.title=translated",
    "approximated",
    "`form_title` is not translatable: the default-language title is used.",
)
_row("Metadata.description", "unsupported", "XLSForm has no survey description; dropped.")
_row("Metadata.languages", "native", "One `label::<language>` column per language.")
_row("Metadata.defaultLanguage", "native", "settings `default_language`.")
_row("Metadata.license", "unsupported", "No licence field in XLSForm; dropped.")
_row("Metadata.ddi", "unsupported", "No study-metadata block in XLSForm; dropped.")
_row("Settings.backNavigation", "native", "Back navigation is allowed by default in ODK/Enketo.")
_row("Settings.saveMode", "unsupported", "Our runtime's save mode; ODK/Enketo manage saving.")
_row("Settings.localCopy", "unsupported", "Our runtime's local copy; ODK/Enketo manage drafts.")
_row("Settings.resumeExpiryDays", "unsupported", "Resume links are our server's; not in the form.")
_row("Settings.retention", "unsupported", "Data retention is a platform policy, not the form's.")
_row("Retention.kind", "unsupported", "See Settings.retention.")
_row("Retention.days", "unsupported", "See Settings.retention.")
_row("Retention.until", "unsupported", "See Settings.retention.")
_row("Settings.theme", "unsupported", "Our design tokens; not exported to ODK/Enketo yet.")
_row("Colours.dark", "unsupported", "See Settings.theme.")
_row("Colours.light", "unsupported", "See Settings.theme.")
_row("Palette.accent", "unsupported", "See Settings.theme.")
_row("Palette.background", "unsupported", "See Settings.theme.")
_row("Palette.error", "unsupported", "See Settings.theme.")
_row("Palette.focus", "unsupported", "See Settings.theme.")
_row("Palette.muted", "unsupported", "See Settings.theme.")
_row("Palette.surface", "unsupported", "See Settings.theme.")
_row("Palette.text", "unsupported", "See Settings.theme.")
_row("Theme.baseSize", "unsupported", "See Settings.theme.")
_row("Theme.buttonStyle", "unsupported", "See Settings.theme.")
_row("Theme.choiceStyle", "unsupported", "See Settings.theme.")
_row("Theme.colours", "unsupported", "See Settings.theme.")
_row("Theme.density", "unsupported", "See Settings.theme.")
_row("Theme.font", "unsupported", "See Settings.theme.")
_row("Theme.headerText", "unsupported", "See Settings.theme.")
_row("Theme.lineSpacing", "unsupported", "See Settings.theme.")
_row("Theme.logoAssetId", "unsupported", "See Settings.theme.")
_row("Theme.mode", "unsupported", "See Settings.theme.")
_row("Theme.preset", "unsupported", "See Settings.theme.")
_row("Theme.radius", "unsupported", "See Settings.theme.")
_row("Theme.themeVersion", "unsupported", "See Settings.theme.")
_row(
    "Survey.consent",
    "unsupported",
    "Our runtime's consent page (no data before agreement); not written, so the exported "
    "form has no consent gate. Add an equivalent first question by hand.",
)
_row("Consent.text", "unsupported", "See Survey.consent.")
_row("Consent.agreeLabel", "unsupported", "See Survey.consent.")
_row("Consent.declineLabel", "unsupported", "See Survey.consent.")
_row("Consent.declineOutcome", "unsupported", "See Survey.consent.")
_row("Consent.countDeclines", "unsupported", "See Survey.consent.")
_row(
    "Settings.endings",
    "lowered",
    "Endings per outcome (EN1) become note groups: the `complete` ending is the form's final "
    "group (shown when the flow runs to its end or reaches an End node with outcome "
    "`complete`); another outcome's ending goes in the group of each End node with that "
    "outcome. Endings reached only through a quota or the consent decline have no place in "
    "the form, as quotas and the consent page are not exported.",
)
_row("Ending.title", "lowered", "The note group's label (its heading).")
_row("Ending.body", "lowered", "A note in the group, after the End node's own message; pipes kept.")
_row(
    "Ending.status",
    "approximated",
    "ODK and Enketo show their own message after a submit; our status line is not written.",
)
_row("Ending.summary", "unsupported", "Reserved (EN5); not exported.")
_row(
    "Ending.redirect",
    "unsupported",
    "End redirects (EN2) are our runtime's: ODK Collect and Enketo have no redirect after a "
    "submit, so the participant stays on their own thank-you screen.",
)
_row("EndRedirect.template", "unsupported", "See Ending.redirect.")
_row("EndRedirect.params", "unsupported", "See Ending.redirect.")
_row("EndRedirect.delay", "unsupported", "See Ending.redirect.")
_row("EndRedirect.mode", "unsupported", "See Ending.redirect.")
_row("EndRedirect.label", "unsupported", "See Ending.redirect.")
_row(
    "Settings.redirectTemplates",
    "unsupported",
    "Redirect templates (EN2) serve end redirects and hooks, neither of which XLSForm has.",
)
_row("RedirectTemplate.url", "unsupported", "See Settings.redirectTemplates.")
_row("RedirectTemplate.params", "unsupported", "See Settings.redirectTemplates.")
_row("RedirectParam.pattern", "unsupported", "See Settings.redirectTemplates.")
_row(
    "Survey.hooks",
    "unsupported",
    "Researcher hooks (custom code on key events, runtime-design.md §7a) run only in our "
    "runtime's sandbox; XLSForm has no event scripting, so the hooks are not exported and the "
    "form runs without them.",
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
_row(
    "Settings.backNavigation=false",
    "unsupported",
    "XLSForm cannot disable Back (Enketo has no option; Collect only via device settings).",
)

# --- Choices -----------------------------------------------------------------------------
_row("ChoiceList.id", "native", "choices `list_name`.")
_row("ChoiceList.choices", "native", "One choices row each.")
_row("Choice.value", "native", "choices `name`. XForms stores codes as text (C2-8).")
_row("Choice.label", "native", "choices `label::<language>`.")

# --- Questions ---------------------------------------------------------------------------
_rows(QUESTIONS, "id", "native", "Used as `name` when `name` is unset; references use names.")
_rows(QUESTIONS, "label", "native", "`label::<language>`. Piping: see $pipe.*.")
_rows(QUESTIONS, "help", "native", "`hint::<language>`.")
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
    "approximated",
    "`relevant`. ODK/Enketo keep a value that becomes non-relevant until final submit, "
    "not until page submit (§3, Enketo E8), so logic and piping can still see it.",
)
_rows(ANSWERABLE, "name", "native", "`name`.")
_rows(ANSWERABLE, "required", "native", "`required`; XForms applies it only while relevant (§4).")
_rows(ANSWERABLE, "constraint", "native", "`constraint`; checked only on non-empty values (§4).")
_rows(ANSWERABLE, "constraintMessage", "native", "`constraint_message::<language>`.")
_row("IntegerQuestion.type", "native", "`integer`.")
_rows(
    ("IntegerQuestion", "DecimalQuestion"),
    "min",
    "lowered",
    "Joined into `constraint` as `. >= min`; the constraint message covers both.",
)
_rows(
    ("IntegerQuestion", "DecimalQuestion"),
    "max",
    "lowered",
    "Joined into `constraint` as `. <= max`; the constraint message covers both.",
)
_row("DecimalQuestion.type", "native", "`decimal`.")
_row("TextQuestion.type", "native", "`text`; trimming follows Enketo (§2).")
_row("TextQuestion.multiline", "native", "`appearance: multiline` (a textarea in Enketo).")
_row("SingleQuestion.type", "native", "`select_one <list>`.")
_row("MultiQuestion.type", "native", "`select_multiple <list>`.")
_row("DateQuestion.type", "native", "`date`.")
_row("NoteQuestion.type", "native", "`note`.")
_rows(CHOICE_QUESTIONS, "choiceList", "native", "`select_one <list>` / `select_multiple <list>`.")
_rows(CHOICE_QUESTIONS, "choices", "lowered", "Inline choices become a generated choices list.")
_rows(CHOICE_QUESTIONS, "choiceOrder", "native", "`fixed`: choices sheet order.")
for _d in CHOICE_QUESTIONS:
    _row(
        f"{_d}.choiceOrder=shuffle",
        "lowered",
        "`parameters: randomize=true seed=${osp_seed_<q>}`: XForms randomize(), which "
        "osp_engine.random.randomize reproduces exactly (E5). The seed is drawn in the form "
        "(`once(random())`) rather than derived with node_seed() from a server sessionSeed; "
        "it is recorded in the data, so the order replays from it.",
    )

# --- Matrix and slider (C2c; semantics.md §2) ---------------------------------------------
_row("MatrixQuestion.id", "native", "Used as the group name when `name` is unset.")
_row(
    "MatrixQuestion.type",
    "lowered",
    "A `begin group` with `appearance: table-list`: a label-only header `select_one` "
    "(`appearance: label`, an extra empty field `osp_<name>_header`), then one "
    "`select_one <list>` per row (`appearance: list-nolabel`). Enketo shows table-list as a "
    "grid at every width, not the stacked-rows layout of our runtime (runtime-design §6).",
)
_row(
    "MatrixQuestion.label",
    "native",
    "`label::<language>` of the header row, above the column labels.",
)
_row("MatrixQuestion.help", "native", "`hint::<language>` of the header row.")
_row("MatrixQuestion.custom", "unsupported", "Lab annotations; see the other question types.")
_row(
    "MatrixQuestion.showIf",
    "approximated",
    "`relevant` on the group; as for questions, Enketo keeps hidden values until submit (§3).",
)
_row("MatrixQuestion.name", "native", "Prefix of each row's `name`: `<name>_<row id>` (C2c-1).")
_row("MatrixQuestion.required", "native", "`required` on each row that does not override it.")
_row("MatrixQuestion.rows", "native", "One `select_one` field per row, in order.")
_row("MatrixQuestion.choiceList", "native", "`select_one <list>` on every row.")
_row("MatrixQuestion.choices", "lowered", "Inline columns become a generated choices list.")
_row("MatrixRow.id", "native", "The row field's name is `<matrix name>_<row id>`.")
_row("MatrixRow.label", "native", "The row field's `label::<language>`.")
_row("MatrixRow.required", "native", "`required` on that row's field.")
_row(
    "SliderQuestion.type",
    "native",
    "`range` with `parameters: start end step`. Like ours it has no value until the "
    "participant touches it (Enketo draws no thumb before then).",
)
_row(
    "SliderQuestion.valueType",
    "native",
    "pyxform types `range` as int or decimal from its parameters.",
)
_row("SliderQuestion.min", "native", "`range` parameter `start`.")
_row("SliderQuestion.max", "native", "`range` parameter `end`.")
_row("SliderQuestion.step", "native", "`range` parameter `step`.")
_row(
    "SliderQuestion.minLabel",
    "unsupported",
    "`range` has no end labels in XLSForm; dropped (put them in the hint by hand).",
)
_row("SliderQuestion.maxLabel", "unsupported", "See SliderQuestion.minLabel.")

# --- Pages and blocks --------------------------------------------------------------------
_row("Page.id", "native", "`begin group` name with `appearance: field-list` (one screen).")
_row("Page.items", "native", "Questions inside the field-list group.")
_row(
    "Page.title",
    "unsupported",
    "Not exported yet (C2b added the field); the field-list group's `label` could carry it.",
)
_row("Page.itemOrder", "native", "`fixed`: sheet order.")
_row("Page.showIf", "native", "`relevant` on the page's field-list group.")
_row(
    "Page.itemOrder=shuffle",
    "approximated",
    "XForms cannot reorder questions; they are shown in document order.",
)
_row("Block.id", "native", "`begin group` name (no label, no appearance).")
_row("Block.title", "native", "Builder-only label; not exported, as in our runtime.")
_row("Block.pages", "lowered", "Field-list groups inside the block group; settings `style: pages`.")

# --- Variables ---------------------------------------------------------------------------
_rows(VARIABLES, "id", "native", "Used as `name` when `name` is unset.")
_rows(VARIABLES, "name", "native", "`name`.")
_row("EmbeddedVariable.kind", "lowered", "A `hidden` field.")
_row(
    "EmbeddedVariable.valueType",
    "lowered",
    "`hidden` stores text; XPath converts it to a number where an expression needs one.",
)
_row(
    "EmbeddedVariable.source",
    "approximated",
    "URL prefill depends on the host (Enketo: `?d[/data/<name>]=value`; Collect: none).",
)
_row(
    "EmbeddedVariable.param",
    "approximated",
    "The URL parameter name is not kept; hosts address the field by its path.",
)
_row("EmbeddedVariable.default", "native", "`default`.")
_row(
    "AssignedVariable.kind",
    "lowered",
    "Two calculates: `osp_seed_<var>` (seed drawn once in the form) and the level, picked "
    "with the same Park-Miller draw as osp_engine.random.assign (uniform weights).",
)
_row("AssignedVariable.levels", "lowered", "Nested `if()` over the levels in the level calculate.")
_row("ComputedVariable.kind", "native", "`calculate`.")
_row(
    "ComputedVariable.expr",
    "lowered",
    "`calculation` wrapped in `if(<inputs answered>, expr, '')` so null in gives null out (§3).",
)

# --- Quotas ------------------------------------------------------------------------------
for _f in ("id", "when", "limit", "countOn", "onFull"):
    _row(f"Quota.{_f}", "unsupported", "XLSForm has no quotas; dropped.")
for _f in ("block", "outcome"):
    _row(f"QuotaFull.{_f}", "unsupported", "XLSForm has no quotas; the screen-out is dropped.")

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
    _row(f"{_d}.id", "native", "Only used to name generated fields.")
_row("BlockNode.type", "lowered", "The block group's `relevant` is the flow path to the node.")
_row("BlockNode.block", "native", "The referenced block is emitted at this point of the flow.")
_row("BranchNode.type", "lowered", "Branch arms become relevance conditions.")
_row("BranchNode.if", "lowered", "ANDed into `then` relevance; its negation into `else`.")
_row("BranchNode.then", "lowered", "Emitted in place with the branch condition.")
_row("BranchNode.else", "lowered", "Emitted in place with the negated condition.")
_row("RandomiserNode.type", "approximated", "See RandomiserNode.children.")
_row(
    "RandomiserNode.children",
    "approximated",
    "XForms cannot reorder groups: children run in document order, not a random order.",
)
_row(
    "RandomiserNode.pick",
    "lowered",
    "Subset chosen in the form: `osp_order_<node>` = randomize() over a generated list of "
    "the children with a seed drawn once; the first `pick` are relevant.",
)
_row("AssignNode.type", "lowered", "See AssignedVariable.kind.")
_row("AssignNode.variables", "lowered", "Each listed variable gets its seed and level calculates.")
_row("QuotaCheckNode.type", "unsupported", "XLSForm has no quotas; the check is dropped.")
_row("QuotaCheckNode.quota", "unsupported", "XLSForm has no quotas; the check is dropped.")
for _f in ("type", "template", "params", "returns"):
    _row(
        f"ExternalTaskNode.{_f}",
        "unsupported",
        "XLSForm cannot leave the form to run an external task; the hop is dropped.",
    )
_row(
    "EndNode.type",
    "approximated",
    "No early termination in XForms: everything after the end is made non-relevant, and "
    "the participant still submits the form.",
)
_row("EndNode.outcome", "lowered", "Recorded in the `osp_outcome` calculate.")
_row("EndNode.message", "lowered", "A note in its own field-list group, relevant at that end.")

# --- Expressions (osp-expr AST) ----------------------------------------------------------
_row("IntLit.kind", "native", "XPath number.")
_row("IntLit.value", "native", "Written as digits.")
_row("DecLit.kind", "native", "XPath number.")
_row("DecLit.value", "native", "Written in plain notation (no exponent).")
_row("TextLit.kind", "native", "XPath string literal.")
_row("TextLit.value", "native", "Quoted; `concat()` when it holds both quote kinds.")
_row(
    "BoolLit.kind",
    "lowered",
    "`true()` / `false()` as a condition; the strings `'true'` / `'false'` as a value.",
)
_row("BoolLit.value", "lowered", "See BoolLit.kind.")
_row("NullLit.kind", "lowered", "`''` as a value; any comparison with it is `false()`.")
_row("Ref.kind", "native", "`${name}`.")
_row("Ref.id", "native", "Rewritten to the target's variable name.")
_row(
    "Compare.kind",
    "lowered",
    "Guarded with `string-length(${x}) > 0` for each operand reference so a comparison with "
    "a missing value is false, even null == null (§3). Date ordering uses decimal-date-time().",
)
_row("Compare.op", "native", "`= != < <= > >=`.")
_row("Compare.left", "native", "Operand.")
_row("Compare.right", "native", "Operand.")
_row(
    "Arith.kind",
    "approximated",
    "XPath numbers are IEEE doubles, not decimals (§2), so results can differ in the last "
    "digits. Division by zero is guarded to give null (semantics §3, C1-1).",
)
_row("Arith.op", "native", "`+ - *`, and `/` as `div`.")
_row("Arith.left", "native", "Operand.")
_row("Arith.right", "native", "Operand.")
_row("And.kind", "native", "`and`.")
_row("And.args", "native", "Operands.")
_row("Or.kind", "native", "`or`.")
_row("Or.args", "native", "Operands.")
_row("Not.kind", "native", "`not()`.")
_row("Not.arg", "native", "Operand.")
_row("Answered.kind", "lowered", "`string-length(${q}) > 0`.")
_row("If.kind", "native", "XPath `if(cond, a, b)`.")
_row("If.cond", "native", "The XPath condition.")
_row("If.then", "native", "The XPath value.")
_row("If.else", "native", "The XPath value.")
_row("Answered.ref", "native", "`${q}`.")
_row("Contains.kind", "lowered", "`selected(${q}, value)`.")
_row("Contains.ref", "native", "`${q}`.")
_row("Contains.value", "native", "The code, as an XPath string.")

# --- Behaviours that are not a single field ----------------------------------------------
_row("$pipe.value", "native", "`${q}` in a label inserts the raw value (§8).")
_row(
    "$pipe.builtin",
    "unsupported",
    "`${$trial}`, `${$position.index}` … are our runtime's built-ins; dropped from the label.",
)
_row(
    "$pipe.choiceLabel",
    "lowered",
    "Piping a single-choice question: `osp_label_<q>` = jr:choice-name(${q}, '${q}') (§8, E9).",
)
_row(
    "$pipe.multi",
    "approximated",
    "Piping a multi-choice question inserts its space-separated codes, not labels (C3a-9).",
)
_row(
    "$pipe.escaping",
    "approximated",
    "HTML escaping of piped text (§8) is not verified in ODK/Enketo.",
)
_row(
    "$text.markup",
    "approximated",
    "XLSForm labels are Markdown with some HTML: `*`, `_`, `#`, `<` may render as formatting.",
)
_row(
    "$text.controlCharacters",
    "approximated",
    "Control characters cannot be stored in .xlsx; they are dropped.",
)
_row(
    "$missingStates",
    "approximated",
    "XForms data has one empty value for not-reached, irrelevant and unanswered (§1). "
    "Enketo's pruned output drops non-relevant nodes, so `irrelevant`/`not-reached` show as "
    "absent and `unanswered` as empty; telling not-reached from irrelevant needs the survey "
    "logic replayed (osp-engine) over the submission.",
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

XLSFORM: dict[str, Capability] = {}
for _key, _level, _note in _ROWS:
    if _key in XLSFORM:  # pragma: no cover - caught by the tests
        raise ValueError(f"duplicate capability row {_key}")
    XLSFORM[_key] = Capability(_level, _note)

__all__ = ["XLSFORM"]
