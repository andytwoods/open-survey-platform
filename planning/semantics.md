# Survey logic semantics, v0

**Status:** decisions batch 1 folded in (16 Oct 2026) · **Purpose:** the single definition of how a survey behaves. The engine, simulator, debugger, transpilers and the LimeSurvey harness are all tested against this. Agents implement from it and must not guess beyond it.
Items marked **[verify: …]** are our intended behaviour, originally aligned with ODK XForms during the Enketo spike. Our own runtime (`runtime-design.md`) now implements this document directly, and the fixtures are the test. Decision ids in brackets (C1-2, R6-4 …) point to `decisions-semantics-1.md`.

## 1. Question states

Every question in a session is in exactly one state:

| State | Meaning | Stored value |
|---|---|---|
| `not-reached` | Flow never got to its page | absent |
| `irrelevant` | Page reached, but display logic hid it, or its block later dropped off the path (§3) | `null`, flagged irrelevant |
| `unanswered` | Shown, left empty (only possible if not required) | `null` |
| `answered` | Shown and answered | the value |

Exports always distinguish these states, and the codebook documents how. Data archives generally recommend this: separate, labelled missing-value types, never one ambiguous blank **[A]**. Encoding depends on the format, so a missing code can never be mistaken for a real number:

| Format | Value cell | How the state is carried |
|---|---|---|
| CSV (MVP) | empty | Companion column `<var>__state` = `answered` / `unanswered` / `irrelevant` / `not-reached`. On by default, can be switched off |
| JSON (MVP) | `null` | `"state"` field per answer |
| SPSS `.sav` (later) | `-98` unanswered, `-99` irrelevant, `-97` not reached | Declared as **user-missing** with value labels, so SPSS excludes them automatically |
| Stata `.dta` (later) | `.a` unanswered, `.b` irrelevant, `.c` not reached | Extended missing values with labels |
| R (later, via `.sav` + haven) | tagged NA | From the SPSS declarations |

Raw `-99`-style codes are **never** written into CSV, where they would silently be averaged as real numbers.

**Variables have states too** [C2-6, C3a-5]:

- An **embedded** variable (a URL parameter) is captured once at session start and exported with a value and a state. A missing parameter takes its `default` (state `answered`), or is `unanswered` if there is no default. A malformed one (e.g. `12a` for an integer) is recorded as `unanswered` with a logged diagnostic; the participant is never blocked.
- A **computed** variable exports a value and a `__state` column: a non-null value is `answered`; a null value is `not-reached` if every question it reads (following other computed variables) is not-reached, `irrelevant` if each is not-reached or irrelevant, and `unanswered` otherwise.
- An **assigned** condition is always recorded with the response (§7), whether or not its `assign` node was reached.
- **Notes** have no state and no column [C3a-1].

**Exports** [M2-1 to M2-3]: the `_late` column is the server's flag (§10), not "after the survey closed" (that is the separate `_after_close` column). In a combined export of several versions, a question whose type or choices changed between versions gets separate columns `<name>_v<N>` per version, and the codebook notes the change.

## 2. Values and types

- Types: `integer`, `decimal`, `text`, `single` (one choice value), `multi` (set of choice values), `date`. A `slider` stores an `integer` or `decimal` (its `valueType`); a `matrix` stores nothing itself (its rows are `single` variables, below).
- **Matrix rows are separate variables** [C2c-1]: row `r` of a `matrix` question with id `m` is a single-choice variable with id **`m_r`** (what conditions and piping refer to) and export name **`<matrix name>_r`** (the matrix's `name`, or its id), with its own value, state and `__state` column. Row ids are unique within their matrix; the derived id must be unique among all ids and at most 64 characters. Every row offers the matrix's columns (one shared choice list). A row is **relevant exactly when its matrix is** (rows have no `showIf` of their own), so a hidden matrix makes every row `irrelevant`. A row is required if it says so, else if the matrix is (`required` on the matrix is the default for every row); required is checked per row (§4). The matrix id itself has no value: referring to it is an error.
- **Sliders start unanswered** [C2c-3] (runtime-design §6): no value until the participant sets one, so a required slider blocks Next until it is touched, and an untouched optional slider is `unanswered`, never its midpoint. A slider answer must lie on its grid, `min + k × step`; a value between steps is unreadable input (`invalid`, code `value.off_step`, §2 below), and one outside `min`…`max` is a `range` error (§4).
- Numbers are **decimal**, not binary float. Integer division isn't an operator. `/` returns a decimal.
- **Decimal precision** [R6-2]: arithmetic keeps **28 significant digits, rounding half-even** (Python's `decimal` default; the TS engine matches it exactly). `+ - *` on two integers stay exact integers. A decimal answer with more than 28 significant digits cannot be read exactly and is refused as unreadable input (§4).
- **Decimals are stored and exported in canonical form** [R6-2]: no exponent, no `+`, no superfluous leading zeros, no trailing zeros after the point, `0` for any zero (`2.50` → `2.5`, `.5` → `0.5`, `-0.0` → `0`).
- Text answers follow Enketo's behaviour (decided 16 Oct 2026): leading/trailing whitespace is trimmed, and a whitespace-only answer counts as `unanswered`. Internal whitespace and line breaks are kept.
- **The trim set** [R6-1, R1-7] is exactly the Unicode `White_Space` characters plus U+FEFF (the byte-order mark): U+0009–U+000D, U+0020, U+0085, U+00A0, U+1680, U+2000–U+200A, U+2028, U+2029, U+202F, U+205F, U+3000, U+FEFF. Not the zero-width space U+200B, and not U+001C–U+001F. Python (`osp_expr.values.TRIM_CODE_POINTS`) and the TS engine use the same explicit list, checked against `contract/vectors/trim.json`. Text is **never Unicode-normalised**; the raw text is kept, so `café` (composed) and `café` (decomposed) are different answers.
- Choice values are the codes defined in the survey, never display labels.
- **Codes compare as text** [C2-8]: `1` and `"1"` are the same code, in conditions (`==`, `!=`, `contains`) as in answers. Codes contain no whitespace.
- **Unreadable input** [R1-4]: input the runtime cannot read as the question's type (`12a` for an integer, `2026-02-30` for a date, an integer beyond ±(2^53 − 1), a decimal over 28 significant digits) is not stored; it blocks Next with an `invalid` error, even on an optional question.

## 3. Expressions and missing values

- Expressions are pure: no randomness, time or I/O.
- **Two-valued logic** [C1-2, C3a-8]. Comparing anything with `null` gives `false`, including `null == null`. `contains(null, v)` is `false`. A condition that evaluates to `null` counts as `false`, and `not null` is `true`. So "did not pick X" (`not contains(c, "x")`) is true for someone who didn't answer: the builder warns when `not` wraps a question that may be unanswered and suggests `answered(c) and not …`. Use `answered(x)` to test for presence.
- Arithmetic with `null` gives `null`.
- `contains(multi, value)` tests a multi-choice answer.
- **`if(cond, a, b)`** [C1-3, C2-9]: only the chosen branch is evaluated; a condition that is not `true` (including `null`) picks `b`. Both branches must have compatible types. Note that `if(age < 40, "young", "old")` gives `"old"` when `age` is unanswered; write `if(answered(age), …, null)` to keep it missing.
- **Division by zero** [C1-1]: `x / 0` gives `null` and a logged diagnostic. A constant zero divisor is a type error, so it blocks publishing.
- **Type mismatches** [C1-2] (`text == 5.5`, `text < "b"`, `text + 1`, `contains(non-multi, v)`, a number used as a condition) are type errors that block publishing. At runtime (hand-edited JSON) they give `null` plus a logged diagnostic, never a crash; inside `and` / `or` / `not` / `if` the mismatched operand counts as `null`. An integer and a text compared with `==` / `!=` are codes and compare as text (§2).
- Runtime diagnostics are logged with the session (the engine's state and the response record), never shown to the participant.
- Referring to a question that is `not-reached` or `irrelevant` gives `null`.
- **An assigned condition is `null` to expressions and piping until its `assign` node is reached** [C3a-7], although the server fixes its value at session start and the response always records it.
- **References** [C2-1, C2-2]: conditions, piping and flow refer to a question's stable `id`, never its export `name` (which can be renamed freely). A reference must point earlier in flow order (a depth-first walk: `then` before `else`, randomiser children, pages and items in document order); a forward reference is an error. **References between items on the same page are allowed in either direction**, but same-page `showIf` conditions that depend on each other in a loop are an error. A page-level `showIf` may refer only to earlier pages. Only a question's own `constraint` may refer to the question itself. A reference into the other arm of a branch, or into another child of the same randomiser, is a warning (it is often `null`).
- **When a previously answered question becomes irrelevant** (for example after going back and changing an earlier answer), its value is **cleared on page submit** and its state becomes `irrelevant`. **[confirmed with a lowering, Enketo spike E8, 16 Oct 2026:** Enketo itself only clears non-relevant values at final submit, so the old value reappears if relevance returns. Our runtime calls `form.clearNonRelevant()` on every page change, which gives exactly this rule (P5c).**]**
- **When a block drops off the path** [C3a-6]: if going back and changing an answer means a block that was already reached is no longer on the path (a branch now goes the other way, or an earlier `end` now ends the session), that block's answers become `irrelevant` and are **cleared on the submit** that changes the path. If the path later returns to the block, its questions are `unanswered` again.

## 4. Required and validation

- `required` applies only while the question is relevant.
- Constraints are checked only on answered values.
- **Numeric `min` / `max`** [C2-9] on integer and decimal questions are inclusive bounds, checked only on answered values; an answer outside them blocks Next with a `range` error.
- Unreadable input blocks Next with an `invalid` error, even on an optional question (§2).
- Validation runs on page submit. The page can't advance until it passes.

## 5. Navigation, saving and resuming

- Back navigation is a per-survey setting (**default: allowed**, decided 16 Oct 2026).
- Going back re-evaluates relevance for later pages when they are revisited. Values follow §3.
- Refresh or resume returns to the same page with the same values, order and condition. **[confirmed, Enketo spike E7, 16 Oct 2026:** enketo-core has no persistence of its own. Our server autosaves the instance and the current page, and restores them on load (P6).**]**
- **Save mode** [R6-5] is a survey setting, `saveMode`: `every-page` (default) saves to the server on every change; `end-only` sends nothing before the final submit and keeps its copy on the device as set by `localCopy`: `browser` (default; browser storage) or `memory`. If browser storage is unavailable, `end-only` falls back to memory, never to network saving.
- **A memory-only copy is lost on refresh** [R6-5]: the session restarts from the first page with the **same seed and conditions** (so the same orders and assignment), and the participant is shown a notice.
- **Resume links expire** [S-1] after **30 days without activity** by default, configurable per survey (`resumeExpiryDays`). This is separate from quota holds (§6).
- **While a quota check is pending** [R6-4], the submitted page stays shown, answers and navigation (including back) are disabled, and a refresh re-sends the call with the same idempotency key, so the server answers it at most once.
- **Saving never loses an answer that reached the session** [R9-1, 17 Oct 2026]: a refresh or close straight after typing keeps the last answer, including with browser storage blocked (the server is then the only copy). A save is judged by its event log, not only its base revision: a save whose log extends the server's copy is taken whatever revision it was based on (it overwrites nothing), and a late save the server's copy already contains changes nothing. Neither is a conflict. A refreshed page that knows its last save is still on the way waits briefly (at most ~3 s) for the server to have it.
- **Two devices** [R6-6, S-3]: when a stale copy (an old tab on device A) saves after another device moved on, so the two copies diverge, the server copy wins. Device A then shows the server's current page and values, with an explanation. The losing copy is kept in an encrypted conflicts table for a limited time, excluded from exports; the audit log stores only its id.

## 6. Flow

- The flow is a tree of nodes: `block`, `branch`, `randomiser`, `assign`, `quotaCheck`, `end`. It is checked at validation time and has no cycles, so every session terminates.
- **A block appears at most once in the flow** [C2-3], so each question is one column with one state.
- **Empty-page skipping is per page** [C3a-1, R1-6]: a page with no relevant item is skipped silently, and its questions become `irrelevant`. A relevant note counts as content, so a page holding only notes (a stimulus, a screen-out message) is shown.
- **Page-level `showIf`** [C2-9]: a page whose `showIf` is false is skipped and its questions are `irrelevant`.
- Reaching the end of the flow without an `end` node counts as `end: complete`.
- **Quotas** [C3a-3, C2-7, R1-5]: counts are atomic on the server. A `quotaCheck` asks the server only while its quota's `when` is true. A place is **held** at the check, **used up on completion**, and released when the participant drops out (24 hours without activity). Resuming after the hold was released must take a place again; if the quota is full by then, the participant continues and the submit is late (§10). The result is recorded per node and **reused** on back, forward and replay, without a new call. When the quota is full, `onFull` shows **at most one block**, then ends the session with its `outcome` (a quota-full outcome such as `quota_full`). There is no `goto`. Only `countOn: complete` is modelled.

## 7. Randomisation and assignment

- Each session has a `sessionSeed`, which must be a **positive integer** (decided 16 Oct 2026: Enketo throws on decimal or string seeds). Derived per-node seeds are integers too: `nodeSeed = (int.from_bytes(SHA-256(ns("osp-node-seed/1") + ns(surveyVersion) + ns(str(sessionSeed)) + ns(nodeId))[0:8], "big") mod (2^31 − 2)) + 1`, where `ns(s) = len(utf8(s)) + ":" + utf8(s) + ","` (a netstring). That gives 1 … 2^31 − 2, which Enketo accepts as a seed and uses as the Park–Miller state without reducing it (`osp_engine.random.node_seed`). Accepted session seeds are 1 … 2^53 − 1.
- **`surveyVersion`** in seeds [R1-1] is the published version number as decimal text (`"3"`), or `"draft"` for previews.
- Each random decision uses its own stream: `PRNG(hash(surveyVersion, sessionSeed, nodeId))`. Changing one randomiser doesn't change the others. **Stream ids** [R1-2, C2-5]: a randomiser's id; a page's item order is keyed by the **page** id; a question's choice order by the question id; each assigned variable by `<assign node id>/<variable id>`.
- **Randomiser `pick`** [C2-4]: a seeded shuffle of the children, taking the first `pick` (a uniform draw without replacement).
- **Assignment** [C2-5]: each assigned variable is an independent, uniform seeded draw. Weighted or balanced allocation is not modelled in `osp-survey/0.1`.
- The realised order and assignment are **fixed at first reach** and never re-rolled on back, refresh or resume.
- Every response records: the allocation mode (`server` for our runtime | `seeded` | `limesurvey-native` for LSS exports), the assigned conditions, and the realised question, block and choice orders.
- **Default (our runtime):** our server assigns conditions and `sessionSeed` at session start and injects them. If the server did not assign a variable, the engine draws it from its stream and records **`allocation: "seeded"` for that variable** (`conditionSources`) [R1-8]. Choice-order shuffles use XForms `randomize(nodeset, seed)`, and our engine reimplements its exact algorithm (inside-out Fisher–Yates + Park–Miller), so every order is reproducible. **[confirmed, Enketo spike E4, E5, 16 Oct 2026:** injection works, and Python matches Enketo on 900/1,000 seeds (every integer seed; the remainder truncates toward zero). Enketo rejects decimal and string seeds, so seeds must be integers.**]**
- **LSS export only:** a survey exported to LimeSurvey may use `limesurvey-native` allocation. There, LimeSurvey's own RNG decides, and we can record the outcome but not reproduce it.

## 8. Piping

- `${questionId}` inserts the display label for choice answers and the raw value for others. The XLSForm exporter always emits a `jr:choice-name()` calculate for piped choice questions (Enketo inserts codes otherwise).
- **A piped `multi` answer** [C3a-9, R1-3] inserts its choice labels in the order they were **displayed** (the realised choice order), joined with `", "`. **A piped decimal** is in canonical form (`2.5`); a computed number in plain notation; a boolean as `true` / `false`.
- **Built-ins** [R6-3]: the `$` namespace is reserved. `${$trial}` is the 1-based number of the current page on the participant's path (pages skipped as empty don't count; after back it is the number of the page now shown). `${$position.index}` and `${$position.of}` give the 1-based position within the innermost randomiser and `of` = its `pick` (or its number of children); outside a randomiser they are empty. `$pagesDone`, `$language` and `$device` are also available.
- Piping an unanswered, irrelevant or not-reached question inserts an empty string.
- Piped text is HTML-escaped.
- **Pipes inside formatting** (planning/rich-text.md §3, RT2): in a rich-text value a pipe is a node `{"pipe": "id"}` with the same identifiers, built-ins and reference rules as `${id}`. A piped value takes the formatting of the run it sits in (bold text around a pipe stays bold); the value itself is never parsed as rich text, so an answer cannot add formatting, links or markup. A rich value with no formatting is stored as the plain string with `${id}` written back.

## 9. Versions

- Each response is bound to exactly one published survey version, and that version's checksum.
- Changing a published survey always creates a new version. Old versions' responses keep their own codebook.
- **Variable names that differ only by case are an error** [C2-8] (SPSS, Stata and LimeSurvey fold case).
- **Publishing needs a retention policy** (lead decision, 16 Oct 2026): `settings.retention` must be set (`days-after-close`, `after-date` or an explicit `indefinite`); there is no silent default. Published surveys can't be deleted.

## 10. Submitting

- **Late submits are accepted** [S-2]: a submit that arrives after the session's quota holds were released (24 hours idle) or after its resume link expired is stored, flagged `late` by the server, and **not counted toward quotas**. Rejecting it would lose data.
- **Retries** [S-4]: a submit retry with identical data returns the original success (same response); different data for an already submitted session gives 409.

## 11. Consent and withdrawal

Added by M5 (MVP 12b). Where the docs were silent, the most protective option was taken; those choices are marked **[M5, protective]** for the lead to confirm.

- **The consent page is survey-level** (`consent`), not a flow node: it is shown first, before any question, at most once. A flow node could be placed after a block or inside a branch, which would need extra rules to keep "consent before collection"; the survey-level setting makes it structural.
- It has `text`, `agreeLabel`, `declineLabel` (all translatable; **nothing can be piped** into them, `consent.pipe`), `declineOutcome` (default `declined`; never `complete`, `consent.outcome`) and `countDeclines` (default **off** **[M5, protective]**).
- **Version**: the consent version is `sha256:` of the canonical JSON of the compiled texts in every language (`osp_runtime.plan.consent_version`). Any wording change is a new version.
- **Before agreement nothing about the participant is saved** [M5, protective], in both save modes. The server creates the session (seed and assignment only, as in `end-only`), stores **no URL parameters** for a survey with a consent page (they travel in the response at submit), and refuses snapshots, quota checks and submits (`consent.required`, 403) until the session has agreed to exactly the plan's version. The runtime sends no snapshot before agreement.
- **Agree**: the server records `consentVersion` and `consentedAt` (server clock) on the session; the engine records them too, and the response carries both (`server.consentVersion`, `server.consentedAt`; the record's own `consentVersion`, `consentedAt`). A submit whose `consentVersion` differs from the plan's is refused. Exports add `_consent_version` and `_consented_at` (only for versions with a consent page); the codebook includes the consent texts.
- **Decline**: the session ends with `declineOutcome`, no question is reached and **no response is recorded**. The server deletes the session (seed, assignment, token), gives back any balanced-assignment count, writes **no audit entry** [M5, protective], and adds one to an anonymous per-publication count only if `countDeclines` is on. A decline after agreeing is refused (withdraw instead).
- **Engine**: until the participant decides, the view's `status` is `consent` with page `$consent` (no items, no navigation); answers are refused (`consent-pending`) and Next does nothing. A memory-only restart (§5) shows the consent page again.
- **Withdrawal**: after agreeing (before or after submit) the participant can withdraw from the end screen or via the resume link. The server deletes the response and the session through the store's deletion, gives back the held quota places of an unsubmitted session, and writes an audit entry with the reason and the number of responses deleted, **never answer data**. The resume token stops working. Quota places used by a *submitted* response stay used (open question C-1).
- **Researcher deletion**: `DELETE /api/surveys/{id}/responses/{responseId}` needs `response.delete` (owner, editor) and writes a `response.delete` audit entry without answer data.
- **No IP addresses**: no participant endpoint stores or logs a client address (it is only an in-memory rate-limit key); `osp-api serve` writes access logs without it and blanks it in every uvicorn log record.

## Open questions (need a human decision)

- **C-1 (M5; decided by the lead 17 Oct 2026: keep as is, the place stays used, so funded recruitment is never exceeded; researchers can raise the quota)**: when a participant withdraws a *submitted* response, should its quota place (and balanced-assignment count) be given back so another participant can take it? Currently it stays used.
- **C-2 (M5; decided by the lead 17 Oct 2026: off by default, as built)**: should declines be counted by default? Currently off; the researcher opts in.

Resolved 16 Oct 2026: see `decisions-semantics-1.md` (C1-1 to C1-3, C3a-1 to C3a-9, C2-1 to C2-9, R6-1 to R6-6, R1-1 to R1-8, S-1 to S-4), plus the lead's M2-1 to M2-3. Earlier: missing-value encoding (§1), back navigation default (§5), text trimming follows Enketo (§2).

Matrix and slider (C2c, 16 Oct 2026). C2c-1 and C2c-3 above follow from existing rules (a matrix row is a `single` question; a slider is an `integer`/`decimal` question that starts empty). These parts were not covered, so the agent picked the conservative option, marked here for a human to confirm:

- **C2c-2 (decided by the lead, 17 Oct 2026, as proposed)**: matrix rows have no `showIf` or `constraint` of their own, and neither rows nor columns can be shuffled, in `osp-survey/0.1`. Per-row display logic would need its own same-page rules; use separate questions meanwhile.
- **C2c-4 (decided by the lead, 17 Oct 2026, as proposed; the slider widget must show the error, never snap silently)**: a slider value that is in range but off the step grid (typed into the numeric alternative) is refused as unreadable input (`value.off_step`), rather than rounded to the nearest step or accepted as is. Rounding would store a value the participant did not give.

Deferred to `osp-survey/0.2` (decided, not modelled yet): dedicated `scores` (null unless every item is answered, or an explicit `minAnswered` is set; reversal is `min + max − value`) and reverse scoring [C3a-4], and page-order shuffling within a block [C2-9]. Use computed variables with `if()` meanwhile.

None open.

### Endings per outcome (decided 17 Oct 2026, end-of-survey plan §4.1; built in EN1)
`settings.endings` maps an outcome to the screen shown when a session ends with it (title, body with piping as in §8, status line mode). Every end node with that outcome shares it; an end node's own `message` is shown above the body. An outcome without an ending shows the app's defaults. The status line is the app's own and truthful: "sent" once a response is stored, "nothing recorded" after a consent decline (§11), and it can be hidden but never reworded; a decline always shows it. An ending for an outcome nothing reaches is a warning (`ending.unreachable`).

### Answers shown after submit (end-of-survey plan §4.4; built in EN5)
An ending with `summary: answers` lists the participant's own answers under its body: every answered question on the path, in the order the pages were shown and the items displayed, with its label and the answer as text (a choice's label; a multi's labels in the realised order as piping gives them, §8; a matrix row by row), plus a Print button (the browser prints; no PDF is generated). The list is built from the engine state, the same states and values the record holds, and never fetched back from the server. It is shown only on the page whose own submit the server acknowledged: a resumed or already-submitted session, a reload (a new session) and a withdrawal show the ending without it, and after a memory-only resume nothing is left to show. Never for the consent decline (`ending.declined_summary`, an error): nothing was recorded. Notes, unanswered and irrelevant questions are left out.

### End redirects (lead decisions 2 and 3, 17 Oct 2026, end-of-survey plan §4.2; built in EN2)
An ending may carry a `redirect`: a template from `settings.redirectTemplates` (or `hooks.redirects`; one map, a name in one place only), one value per placeholder (a literal, or text with pipes as in §8 plus the ending-only built-ins `${$response.id}`, `${$session.id}`, `${$outcome}`, which are empty before the end), a `delay` of 0–60 s (default 5), a `mode` (`auto`: countdown then navigate, "Stay on this page" cancels; `link`: the participant clicks) and a button `label`. A template is an https URL with placeholders only after the origin; a filled value must match its placeholder's pattern in full (default `[A-Za-z0-9_-]{1,64}`), is `encodeURIComponent`-encoded, may not be `.` or `..`, and the filled URL must keep the template's origin; otherwise there is **no redirect** (nothing shown, nothing navigates) and the record carries `redirect.param_rejected`. A redirect fires only after the server acknowledged *this tab's* submit (or the decline), at most once: a resumed or already-submitted session shows the ending without it. A hook's `setEndRedirect` takes precedence over the ending's redirect. Never from the builder preview (the URL is shown instead). A value that pipes a question is a data export: owner-confirmed, in the codebook, audited (`survey.redirects_changed`), warned about as `redirect.param_question`.

### Quota places and non-complete outcomes (decided 17 Oct 2026, end-of-survey plan §4.5)
Quota places count completes only. A session that passed a `quotaCheck` and then ends with any non-complete outcome releases its place when it ends. A submitted complete response that is later withdrawn keeps its place (C-1).

### External task step (built in EX2; planning/external-tasks.md)
A flow node `externalTask` sends the participant to an external task (a jsPsych/PsychoJS/Gorilla experiment) and resumes the survey on return. Reaching it is an effect, like a `quotaCheck`: the result is recorded per node and reused on back, refresh and replay, so the task runs once. The outbound URL is a declared redirect `template` (§4.2 redirect rules: https, placeholders only after the origin, every value pattern-checked and `encodeURIComponent`-encoded) filled with `params` (literal or piped, a piped answer being a data export); the platform also appends `osp_return` (where to come back) and `osp_token`. The **return token** `osp_token` is `base64url(payload).hmac_hex` over `{v,sid,node,exp}` with a server secret: a changed payload fails verification (tamper), `exp` bounds its life (expiry, default 6 h), and it is bound to the session and node (cross-context replay is a tamper). On return the values named in `returns` (embedded variables, `source: url`) are captured into the session's URL parameters exactly as a start-time URL parameter is: recorded with a value and a state, **never trusted** (the return URL is participant-visible). Same-context replay changes nothing because the node's result is already recorded. An outbound URL that cannot be built (a rejected or missing piped param) skips the node with an `external.param_rejected` diagnostic rather than stranding the participant (lead decision E-1). `PROLIFIC_PID`/`STUDY_ID`/`SESSION_ID` are ordinary embedded URL variables; a Prolific completion code per outcome is an EN1/EN2 ending redirect.

