"""LimeSurvey (``.lss``, LimeSurvey 6.x) capability table.

One row per ``osp-survey`` schema field (``"<SchemaDef>.<field>"``), plus value refinements
(``"<SchemaDef>.<field>=<value>"``) and target behaviours that are not a single field
(``"$<name>"``), in the same shape as the XLSForm table. ``tests/test_lss_capabilities.py``
runs the same completeness guard. The exporter looks levels up here, so every diagnostic it
emits carries the level written in this table.

Sources (clean-room): our own hand-written ``spikes/spike-1/survey/spike1.lss``, the
spike's observed behaviour in LimeSurvey 6.17 (``spikes/spike-1/FINDINGS.md``), and the
public LimeSurvey manual (question types, Expression Manager, quotas).
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
    "LimeSurvey draws its own random order: our seed is not reproduced and the realised "
    "order is not stored in the response (spike-1 Q4), so the run cannot be replayed."
)

# --- Survey root -------------------------------------------------------------------------
_row("Survey.specVersion", "native", "Not written: the .lss carries its own DBVersion.")
_row(
    "Survey.id",
    "lowered",
    "LimeSurvey survey ids are numeric: a 6-digit sid is derived from a hash of the id. "
    "The import keeps it when free and renumbers groups and questions (spike-1 Q1).",
)
_row("Survey.version", "unsupported", "No survey version field in LimeSurvey; dropped.")
_row("Survey.metadata", "native", "Container; see Metadata.*.")
_row("Survey.settings", "native", "Container; see Settings.*.")
_row("Survey.choiceLists", "lowered", "Copied into each question's answer options.")
_row("Survey.variables", "native", "Container; see the variable kinds.")
_row("Survey.blocks", "lowered", "Each page of a block in the flow becomes a question group.")
_row("Survey.quotas", "lowered", "LimeSurvey quotas where the condition fits; see Quota.*.")
_row("Survey.flow", "lowered", "The flow tree becomes group relevance equations (`grelevance`).")

# --- Metadata and settings ---------------------------------------------------------------
_row("Metadata.title", "native", "`surveyls_title`, one row per language.")
_row("Metadata.description", "native", "`surveyls_description`, one row per language.")
_row(
    "Metadata.languages",
    "native",
    "Base `language` plus `additional_languages`; every text has one l10n row per language. "
    "Our tag must also be a LimeSurvey language code.",
)
_row("Metadata.defaultLanguage", "native", "The survey's base `language`.")
_row("Metadata.license", "unsupported", "No licence field in LimeSurvey; dropped.")
_row("Metadata.ddi", "unsupported", "No study-metadata block in LimeSurvey; dropped.")
_row("Settings.backNavigation", "native", "Survey setting `allowprev` (Y/N).")
_row("Settings.saveMode", "unsupported", "Our runtime's save mode; LimeSurvey saves itself.")
_row("Settings.localCopy", "unsupported", "Our runtime's device copy; not in LimeSurvey.")
_row("Settings.resumeExpiryDays", "unsupported", "Our resume links; LimeSurvey has its own.")
_row("Settings.retention", "unsupported", "Data retention is a platform policy, not the survey's.")
_row("Retention.kind", "unsupported", "See Settings.retention.")
_row("Retention.days", "unsupported", "See Settings.retention.")
_row("Retention.until", "unsupported", "See Settings.retention.")

# --- Choices -----------------------------------------------------------------------------
_row("ChoiceList.id", "native", "Not written: each question gets its own answer rows.")
_row("ChoiceList.choices", "native", "Answer options (`answers` + `answer_l10ns`).")
_row(
    "Choice.value",
    "native",
    "The answer code. Codes must be 1-5 letters/digits (subquestion codes up to 20); any "
    "other value gets a generated code, reported under $choice.code.",
)
_row("Choice.label", "native", "`answer_l10ns.answer` (single) or the subquestion text (multi).")

# --- Questions ---------------------------------------------------------------------------
_rows(
    QUESTIONS,
    "id",
    "native",
    "The question code (`title`) when `name` is unset; see $names.* for renames.",
)
_rows(QUESTIONS, "label", "native", "`question_l10ns.question`. Piping: see $pipe.*.")
_rows(QUESTIONS, "help", "native", "`question_l10ns.help`.")
_rows(
    QUESTIONS,
    "showIf",
    "native",
    "Question `relevance` equation. LimeSurvey clears an irrelevant answer to NULL as soon as "
    "the page is submitted (spike-1 Q6), as our §3 does.",
)
_rows(ANSWERABLE, "name", "native", "The question code (`title`); see $names.* for renames.")
_rows(ANSWERABLE, "required", "native", "`mandatory` = Y; only enforced while relevant (§4).")
_rows(
    ANSWERABLE,
    "constraint",
    "lowered",
    "`em_validation_q` attribute, written `is_empty(q.NAOK) or (...)` so it is only checked "
    "on answered values (§4).",
)
_rows(
    ("IntegerQuestion", "DecimalQuestion"),
    "min",
    "lowered",
    "Joined into `em_validation_q` as `q >= min`; the validation tip covers both.",
)
_rows(
    ("IntegerQuestion", "DecimalQuestion"),
    "max",
    "lowered",
    "Joined into `em_validation_q` as `q <= max`; the validation tip covers both.",
)
_rows(ANSWERABLE, "constraintMessage", "native", "`em_validation_q_tip`, per language.")
_row(
    "IntegerQuestion.type",
    "native",
    "Type N (numerical input) with `num_value_int_only` = 1. LimeSurvey stores numbers as "
    "decimal(30,10), so exports may show trailing zeros.",
)
_row("DecimalQuestion.type", "native", "Type N (numerical input).")
_row("TextQuestion.type", "native", "Type S (short free text).")
_row("TextQuestion.multiline", "native", "Type T (long free text) instead of S.")
_row("SingleQuestion.type", "native", "Type L (list, radio).")
_row(
    "MultiQuestion.type",
    "lowered",
    "Type M (multiple choice): one subquestion per choice, stored as one column per choice "
    "(`<q>_<code>` = Y or empty) instead of one list of codes.",
)
_row("DateQuestion.type", "native", "Type D (date); stored with a 00:00:00 time.")

# --- Matrix and slider (C2c; semantics.md §2) ---------------------------------------------
_row(
    "MatrixQuestion.type",
    "native",
    "Type F (array): one subquestion per row, the columns as answer options. Each row is "
    "its own response column `<q>_<row>`, as our row variables are (C2c-1).",
)
_row("MatrixQuestion.id", "native", "The question code when `name` is unset.")
_row("MatrixQuestion.label", "native", "`question_l10ns.question`.")
_row("MatrixQuestion.help", "native", "`question_l10ns.help`.")
_row(
    "MatrixQuestion.showIf",
    "native",
    "Question `relevance`; irrelevant answers are cleared on submit (spike-1 Q6).",
)
_row(
    "MatrixQuestion.name",
    "native",
    "The question code; each row's EM variable is `<code>_<row code>` (our `<name>_<row id>`).",
)
_row(
    "MatrixQuestion.required",
    "native",
    "`mandatory` = Y when every row is required; see $matrix.someRowsRequired.",
)
_row("MatrixQuestion.rows", "native", "Subquestions, in order.")
_row("MatrixQuestion.choiceList", "lowered", "The shared list is copied into the answer options.")
_row("MatrixQuestion.choices", "native", "Answer options (the columns).")
_row(
    "MatrixRow.id",
    "native",
    "The subquestion code (letters and digits; other characters are removed).",
)
_row("MatrixRow.label", "native", "The subquestion text.")
_row("MatrixRow.required", "native", "See MatrixQuestion.required.")
_row(
    "SliderQuestion.type",
    "approximated",
    "Type N (numerical input): a number box, not a slider (LimeSurvey's slider layout exists "
    "only on type K). Like ours it starts empty; the end labels are not shown.",
)
_row("SliderQuestion.valueType", "native", "`integer`: `num_value_int_only` = 1.")
_rows(
    ("SliderQuestion",),
    "min",
    "lowered",
    "Joined into `em_validation_q` as `q >= min`.",
)
_rows(
    ("SliderQuestion",),
    "max",
    "lowered",
    "Joined into `em_validation_q` as `q <= max`.",
)
_row(
    "SliderQuestion.step",
    "lowered",
    "Joined into `em_validation_q` as `fmod(q - min, step) == 0`.",
)
_row("SliderQuestion.minLabel", "unsupported", "A number box has no end labels; dropped.")
_row("SliderQuestion.maxLabel", "unsupported", "A number box has no end labels; dropped.")
_row(
    "$matrix.someRowsRequired",
    "lowered",
    "`mandatory` is per question: when only some rows are required, `em_validation_q` "
    "requires those rows instead (checked only while the question is relevant, §4).",
)
_row("NoteQuestion.type", "native", "Type X (text display / boilerplate).")
_rows(CHOICE_QUESTIONS, "choiceList", "lowered", "The shared list is copied into the question.")
_rows(CHOICE_QUESTIONS, "choices", "native", "Answer options of the question.")
_rows(CHOICE_QUESTIONS, "choiceOrder", "native", "`fixed`: answers in sort order.")
for _d in CHOICE_QUESTIONS:
    _row(
        f"{_d}.choiceOrder=shuffle",
        "approximated",
        "Question attribute `random_order` = 1. " + _UNSEEDED,
    )

# --- Pages and blocks --------------------------------------------------------------------
_row("Page.id", "native", "One question group per page (survey format G: group by group).")
_row("Page.items", "native", "The group's questions, in `question_order`.")
_row("Page.title", "native", "`group_l10ns.group_name` (otherwise the page id).")
_row("Page.itemOrder", "native", "`fixed`: question order.")
_row("Page.showIf", "native", "Joined into the group's relevance (`grelevance`).")
_row(
    "Page.itemOrder=shuffle",
    "approximated",
    "Every question on the page shares a `random_group` attribute, so LimeSurvey shuffles "
    "them. " + _UNSEEDED,
)
_row("Block.id", "lowered", "Not written: its pages become consecutive groups.")
_row("Block.title", "native", "Builder-only label; not exported, as in our runtime.")
_row("Block.pages", "lowered", "Consecutive question groups sharing the block's relevance.")

# --- Variables ---------------------------------------------------------------------------
_rows(VARIABLES, "id", "native", "The question code when `name` is unset.")
_rows(VARIABLES, "name", "native", "The question code; see $names.* for renames.")
_row(
    "EmbeddedVariable.kind",
    "lowered",
    "A hidden short-text question (`hidden` = 1) in the first group, filled from the URL.",
)
_row(
    "EmbeddedVariable.valueType",
    "lowered",
    "Stored as text; Expression Manager compares numerically when both sides are numbers.",
)
_row(
    "EmbeddedVariable.source",
    "approximated",
    "LimeSurvey prefills a question from a URL parameter named like its code. Prefill works "
    "and survives back/reload but is not sticky: re-entering with a new value overwrites it "
    "(spike-1 Q5).",
)
_row(
    "EmbeddedVariable.param",
    "approximated",
    "The URL parameter must be the question code; a different `param` name is not kept, so "
    "links must use `?<code>=value`.",
)
_row("EmbeddedVariable.default", "native", "A default value (`defaultvalues`).")
_row(
    "AssignedVariable.kind",
    "approximated",
    "Two hidden equation questions in the first group: a seed latched with "
    "`if(!is_empty(seed), seed, rand(1, n))` (an unguarded rand() re-rolls, spike-1 Q7) and "
    "the level picked from it. The draw is LimeSurvey's own, made at survey start for every "
    "participant: our seed and allocation are not reproduced.",
)
_row("AssignedVariable.levels", "lowered", "Nested `if()` over the levels in the equation.")
_row("ComputedVariable.kind", "lowered", "A hidden equation question (type *).")
_row(
    "ComputedVariable.expr",
    "approximated",
    'Equation `{if(<inputs answered>, expr, "")}` in the group of its last input. '
    "LimeSurvey computes it when that page is shown, and its numbers are PHP floats, not "
    "decimals (§2).",
)

# --- Quotas ------------------------------------------------------------------------------
_row("Quota.id", "native", "Quota `name`.")
_row(
    "Quota.when",
    "lowered",
    "Quota members: `q == code` on a single-choice question, `contains(q, code)` on a "
    "multi-choice one. Members of one question are ORed, different questions ANDed. A "
    "condition of any other shape cannot be expressed and drops the quota.",
)
_row(
    "Quota.when=unmappable",
    "unsupported",
    "The quota condition is not an AND of (ORs of) answer codes; the quota is dropped.",
)
_row("Quota.limit", "native", "Quota `qlimit`.")
_row("Quota.countOn", "native", "LimeSurvey quotas count completed responses.")
_row(
    "Quota.onFull",
    "approximated",
    "Quota action 1 (terminate): LimeSurvey shows the quota message and ends the response.",
)
_row(
    "QuotaFull.block",
    "approximated",
    "The texts of the block's items become the quota message; its questions are not asked.",
)
_row(
    "QuotaFull.outcome",
    "approximated",
    "LimeSurvey records a quota screen-out, not our outcome name.",
)

# --- Flow --------------------------------------------------------------------------------
for _d in ("BlockNode", "BranchNode", "RandomiserNode", "AssignNode", "QuotaCheckNode", "EndNode"):
    _row(f"{_d}.id", "native", "Only used to name generated questions and groups.")
_row("BlockNode.type", "lowered", "Group relevance is the flow path to the node.")
_row("BlockNode.block", "native", "The referenced block's groups are emitted at this point.")
_row("BranchNode.type", "lowered", "Branch arms become relevance conditions.")
_row("BranchNode.if", "lowered", "ANDed into `then` relevance; its negation into `else`.")
_row("BranchNode.then", "lowered", "Emitted in place with the branch condition.")
_row("BranchNode.else", "lowered", "Emitted in place with the negated condition.")
_row("RandomiserNode.type", "approximated", "See RandomiserNode.children.")
_row(
    "RandomiserNode.children",
    "approximated",
    "When every child is a one-page block, their groups share a `randomization_group` and "
    "LimeSurvey shuffles them. " + _UNSEEDED + " Otherwise children run in document order.",
)
_row(
    "RandomiserNode.pick",
    "approximated",
    "One latched `rand()` equation per child in the first group; a child is relevant when "
    "fewer than `pick` siblings drew a larger number. LimeSurvey's draw, not our seed.",
)
_row("AssignNode.type", "approximated", "See AssignedVariable.kind.")
_row("AssignNode.variables", "approximated", "Each listed variable gets its seed and level.")
_row(
    "QuotaCheckNode.type",
    "approximated",
    "LimeSurvey checks a quota when its member questions are submitted, not at this point "
    "of the flow.",
)
_row("QuotaCheckNode.quota", "approximated", "See QuotaCheckNode.type.")
_row(
    "EndNode.type",
    "approximated",
    "No early termination: every group after the end is made irrelevant, so LimeSurvey "
    "goes straight to submit and the response counts as complete.",
)
_row("EndNode.outcome", "lowered", "Recorded in the hidden `ospoutcome` equation.")
_row("EndNode.message", "lowered", "A boilerplate (X) question in its own group, relevant there.")

# --- Expressions (osp-expr AST) ----------------------------------------------------------
_row("IntLit.kind", "native", "Number.")
_row("IntLit.value", "native", "Written as digits.")
_row("DecLit.kind", "native", "Number.")
_row("DecLit.value", "native", "Written in plain notation (no exponent).")
_row("TextLit.kind", "native", "String literal.")
_row("TextLit.value", "native", "Quoted; `join()` when it holds both quote kinds.")
_row("BoolLit.kind", "lowered", "`1` / `0`.")
_row("BoolLit.value", "lowered", "See BoolLit.kind.")
_row("NullLit.kind", "lowered", '`""` as a value; any comparison with it is `0`.')
_row("Ref.kind", "lowered", "`<code>.NAOK`, so an irrelevant input reads as empty.")
_row("Ref.id", "native", "Rewritten to the question code.")
_row(
    "Compare.kind",
    "lowered",
    "Guarded with `!is_empty(x.NAOK)` for each operand reference so a comparison with a "
    "missing value is false, even null == null (§3). Dates compare via strtotime(). A "
    "literal compared with a choice question is rewritten to its answer code.",
)
_row("Compare.op", "native", "`== != < <= > >=`.")
_row("Compare.left", "native", "Operand.")
_row("Compare.right", "native", "Operand.")
_row(
    "Arith.kind",
    "approximated",
    "Expression Manager numbers are floats, not decimals (§2), so results can differ in the "
    "last digits. Division by zero is guarded to give null (open question 1).",
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
_row(
    "Answered.kind",
    "lowered",
    "`!is_empty(q.NAOK)`; for a multi-choice question, any subquestion is `Y`.",
)
_row("Answered.ref", "native", "The question code.")
_row("If.kind", "native", "Expression Manager `if(cond, a, b)`.")
_row("If.cond", "native", "The EM condition.")
_row("If.then", "native", "The EM value.")
_row("If.else", "native", "The EM value.")
_row("Contains.kind", "lowered", '`<q>_<code>.NAOK == "Y"` on the choice\'s subquestion.')
_row("Contains.ref", "native", "The question code.")
_row("Contains.value", "native", "The choice's subquestion code.")

# --- Behaviours that are not a single field ----------------------------------------------
_row("$pipe.value", "native", "`{q}` in a text inserts the stored value (§8).")
_row(
    "$pipe.builtin",
    "unsupported",
    "`${$trial}`, `${$position.index}` … are our runtime's built-ins; dropped from the text.",
)
_row(
    "$pipe.choiceLabel",
    "native",
    "Piping a single-choice question: `{q.shown}` inserts the label (spike-1 Q8).",
)
_row(
    "$pipe.multi",
    "approximated",
    "Piping a multi-choice question inserts its space-separated codes, not labels.",
)
_row(
    "$pipe.escaping",
    "native",
    "Expression Manager HTML-escapes piped answers (spike-1 Q8), as §8 requires.",
)
_row(
    "$text.markup",
    "lowered",
    "LimeSurvey texts are HTML: `&`, `<`, `>` are escaped so the text shows as written.",
)
_row(
    "$text.braces",
    "lowered",
    "`{` starts an Expression Manager expression; a literal brace is written `\\{`.",
)
_row(
    "$text.controlCharacters",
    "approximated",
    "Control characters are not allowed in XML 1.0; they are dropped.",
)
_row(
    "$names.rename",
    "lowered",
    "Question codes must start with a letter, hold only letters and digits and be at most "
    "20 characters, unique ignoring case. Other names are rewritten (e.g. `consent_blk` → "
    "`consentblk`); the mapping is in the export's `name_map`.",
)
_row(
    "$names.reserved",
    "lowered",
    "A code equal to a LimeSurvey response column or Expression Manager variable (`id`, "
    "`token`, `submitdate`, `lastpage`, `startlanguage`, `seed`, `startdate`, `datestamp`, "
    "`ipaddr`, `refurl`, ...) is renamed; LimeSurvey would otherwise rename or duplicate it "
    "in exports (spike-1 Q2). The mapping is in the export's `name_map`.",
)
_row(
    "$choice.code",
    "lowered",
    "A choice value that is not a valid answer code (1-5 letters/digits; 20 for multi) gets a "
    "generated code; the mapping is in the export's `choice_codes`.",
)
_row(
    "$quota.dropped",
    "unsupported",
    "The quota this check names could not be exported (see Quota.when=unmappable).",
)
_row(
    "$missingStates",
    "approximated",
    "LimeSurvey stores NULL for not-reached and irrelevant and an empty value for unanswered "
    "(§1); telling not-reached from irrelevant needs the survey logic replayed (osp-engine).",
)

LSS: dict[str, Capability] = {}
for _key, _level, _note in _ROWS:
    if _key in LSS:  # pragma: no cover - caught by the tests
        raise ValueError(f"duplicate capability row {_key}")
    LSS[_key] = Capability(_level, _note)

__all__ = ["LSS"]
