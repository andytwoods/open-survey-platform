# Survey logic semantics, v0 draft

**Status:** draft for review · **Purpose:** the single definition of how a survey behaves. The engine, simulator, debugger, transpilers and the LimeSurvey harness are all tested against this. Agents implement from it and must not guess beyond it.
Items marked **[verify: …]** are our intended behaviour, originally aligned with ODK XForms during the Enketo spike. Our own runtime (`runtime-design.md`) now implements this document directly, and the fixtures are the test.

## 1. Question states

Every question in a session is in exactly one state:

| State | Meaning | Stored value |
|---|---|---|
| `not-reached` | Flow never got to its page | absent |
| `irrelevant` | Page reached, but display logic hid it | `null`, flagged irrelevant |
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

## 2. Values and types

- Types: `integer`, `decimal`, `text`, `single` (one choice value), `multi` (set of choice values), `date`.
- Numbers are **decimal**, not binary float. Integer division isn't an operator. `/` returns a decimal.
- Text answers follow **Enketo's behaviour** (decided 16 Oct 2026, replacing the earlier "no trimming" decision to avoid forking Enketo): leading/trailing whitespace is trimmed, and a whitespace-only answer counts as `unanswered`. Internal whitespace and line breaks are kept.
- Choice values are the codes defined in the survey, never display labels.

## 3. Expressions and missing values

- Expressions are pure: no randomness, time or I/O.
- Comparing anything with `null` gives `false`, including `null == null`. Use `answered(x)` to test for presence.
- Arithmetic with `null` gives `null`. A condition that evaluates to `null` counts as `false`.
- `contains(multi, value)` tests a multi-choice answer.
- Referring to a question that is `not-reached` or `irrelevant` gives `null`.
- **When a previously answered question becomes irrelevant** (for example after going back and changing an earlier answer), its value is **cleared on page submit** and its state becomes `irrelevant`. **[confirmed with a lowering, Enketo spike E8, 16 Oct 2026:** Enketo itself only clears non-relevant values at final submit, so the old value reappears if relevance returns. Our runtime calls `form.clearNonRelevant()` on every page change, which gives exactly this rule (P5c).**]**

## 4. Required and validation

- `required` applies only while the question is relevant.
- Constraints are checked only on answered values.
- Validation runs on page submit. The page can't advance until it passes.

## 5. Navigation

- Back navigation is a per-survey setting (**default: allowed**, decided 16 Oct 2026).
- Going back re-evaluates relevance for later pages when they are revisited. Values follow §3.
- Refresh or resume returns to the same page with the same values, order and condition. **[confirmed, Enketo spike E7, 16 Oct 2026:** enketo-core has no persistence of its own. Our server autosaves the instance and the current page, and restores them on load (P6).**]**

## 6. Flow

- The flow is a tree of nodes: `block`, `branch`, `randomiser`, `assign`, `quotaCheck`, `end`. It is checked at validation time and has no cycles, so every session terminates.
- Blocks with no relevant questions are skipped silently.
- Reaching the end of the flow without an `end` node counts as `end: complete`.

## 7. Randomisation and assignment

- Each session has a `sessionSeed`, which must be a **positive integer** (decided 16 Oct 2026: Enketo throws on decimal or string seeds). Derived per-node seeds are integers too: `nodeSeed = (int.from_bytes(SHA-256(ns("osp-node-seed/1") + ns(surveyVersion) + ns(str(sessionSeed)) + ns(nodeId))[0:8], "big") mod (2^31 − 2)) + 1`, where `ns(s) = len(utf8(s)) + ":" + utf8(s) + ","` (a netstring). That gives 1 … 2^31 − 2, which Enketo accepts as a seed and uses as the Park–Miller state without reducing it (`osp_engine.random.node_seed`). Accepted session seeds are 1 … 2^53 − 1.
- Each random decision uses its own stream: `PRNG(hash(surveyVersion, sessionSeed, nodeId))`. Changing one randomiser doesn't change the others.
- The realised order and assignment are **fixed at first reach** and never re-rolled on back, refresh or resume.
- Every response records: the allocation mode (`server` for our Enketo runtime | `limesurvey-native` for LSS exports), the assigned conditions, and the realised question, block and choice orders.
- **Default (Enketo runtime):** our server assigns conditions and `sessionSeed` at session start and injects them into the form. Choice-order shuffles use XForms `randomize(nodeset, seed)`, and our engine reimplements its exact algorithm (inside-out Fisher–Yates + Park–Miller), so every order is reproducible. **[confirmed, Enketo spike E4, E5, 16 Oct 2026:** injection works, and Python matches Enketo on 900/1,000 seeds (every integer seed; the remainder truncates toward zero). Enketo rejects decimal and string seeds, so seeds must be integers.**]**
- **LSS export only:** a survey exported to LimeSurvey may use `limesurvey-native` allocation. There, LimeSurvey's own RNG decides, and we can record the outcome but not reproduce it.

## 8. Piping

- `${questionId}` inserts the display label for choice answers and the raw value for others. The XLSForm exporter always emits a `jr:choice-name()` calculate for piped choice questions (Enketo inserts codes otherwise).
- Piping an unanswered, irrelevant or not-reached question inserts an empty string.
- Piped text is HTML-escaped.

## 9. Versions

- Each response is bound to exactly one published survey version, and that version's checksum.
- Changing a published survey always creates a new version. Old versions' responses keep their own codebook.

## Open questions (need a human decision)

Resolved 16 Oct 2026: missing-value encoding (§1), back navigation default (§5), text trimming follows Enketo (§2).

Open (added by C1, `osp-expr`; the evaluator implements the **provisional** behaviour until a human decides):

1. **Division by zero (§2, §3).** What does `x / 0` give? **Provisional: `null`**, so it behaves like any other missing value (a condition using it is false). Note Enketo/XPath gives `Infinity` or `NaN` here.
2. **Ill-typed operands at runtime (§3).** What happens when values of the wrong kinds meet, e.g. `text == 5`, `text < "b"`, `text + 1`, `contains(non-multi, v)`, or a number used directly as a condition (`not q3`)? **Provisional:** a test (comparison, `contains`) on mismatched kinds is `false`; ordering (`< <= > >=`) is defined only for numbers and for dates (not text); arithmetic on non-numbers is `null`; `and` / `or` / `not` treat any operand that is not `true` as false, so `not null` is `true` (consistent with `not (q > 5)` being true when `q` is null). `typecheck` reports all of these before publish, so they should only arise in hand-edited JSON.
3. **Functions beyond `answered` and `contains`.** `planning/review.md` §2.3 uses `if(cond, a, b)` in the `age_band` calculate, but this document names no other functions. Not implemented until decided.

Open, raised by task C3a (fixtures v0). Fixtures that depend on one are marked `"pending"` and are drafts, not assertions:

- **C3a-1** Notes. Does a block holding only `note` items (a stimulus, a screen-out message) count as having "no relevant questions" and get skipped (§6)? Do notes have a state or a response column? Fixture 20 assumes the page is shown and notes have no state.
- **C3a-2** `calculate` items (§2.3 `age_band`). Which state does a calculated value have, when is it evaluated (page submit? continuously?), is it a response column, and is `if(cond, a, b)` part of the expression language (C1's v0 grammar has no `if`)?
- **C3a-3** `quotaCheck` (§6 lists the node, nothing defines it). Where do quota counts come from at runtime, what does `onFull: {goto: block}` do in a tree-shaped flow (after the goto block, is the session ended, and with which end code?), and is a quota hit recorded in the response?
- **C3a-4** `scores` (§2.3 `att_score`, `mean` with `reverse`). How missing items are handled, the decimal precision of a mean like 13/3, and where the score is recorded.
- **C3a-5** `embeddedData` from a URL parameter. Is it recorded in the response, with which state, and what happens when the parameter is missing (does `default` count as a value)?
- **C3a-6** Branch path changes after back. If going back changes an answer so that a branch no longer leads to a block that was already answered, are that block's answers `not-reached` or `irrelevant`, and are they cleared (§3 only covers `showIf`)? No fixture yet.
- **C3a-7** Referring to a condition variable (e.g. `framing`) before its `assign` node is reached. The server assigns it at session start (§7): is it visible to expressions and piping immediately, or `null` until the node? Fixtures only refer to conditions after the node, and record conditions even when the participant ends before reaching it (fixture 20, script `declined`).
- **C3a-8** `contains(x, v)` when `x` is `null`, and `not` applied to `null`. Both only matter inside `not (...)`: `not contains(c, "red")` with `c` unanswered is `true` if `contains` gives `false`, undecided if it gives `null`. No fixture yet.
- **C3a-9** Piping a `multi` answer (how several labels are joined) and piping a `decimal` (is `2.50` piped as typed or normalised?). No fixture yet.

**Added by agent C2 (`osp-spec`), 16 Oct 2026. Open; the validator implements the proposed rule until a human decides.**

- **C2-1 Reference order.** Proposed: number questions in flow order (depth-first walk of the flow tree; `then` before `else`; randomiser children, pages and items in document order). A condition or piped text may only refer to a question with a lower number than its own site (error `ref.forward`). Earlier items on the *same page* count as earlier (Enketo updates live). Only a question's own `constraint` may refer to itself. A target in another child of the same randomiser, or in the other arm of a branch, is legal but a warning, since it is often `null` (§3). An `assigned` variable is only available after its `assign` node; an `embedded` one from the start. Confirm?
- **C2-2 References use stable ids.** Conditions, `${…}` piping and flow nodes refer to a question's stable `id`, not its human-readable variable `name` (which defaults to the id and is what exports use). So renaming a variable never breaks logic. Confirm §8's `${questionId}` means this id.
- **C2-3 A block appears in the flow at most once**, even in two arms of one branch, so each question is one column with one state. Confirm, or define how a repeated block is stored.
- **C2-4 Randomiser `pick`.** The model allows "show `pick` of N children" (common for between-subjects stimulus blocks). §7 doesn't say how the subset is chosen (uniform seeded draw? least-filled?). Needs a rule before C4 implements it.
- **C2-5 Assignment method.** An `assign` node gives each listed variable one of its `levels`. Proposed: an independent, uniform seeded draw per variable (so a full factorial is balanced in expectation). Weighted or balanced allocation is not modelled (review §2.3: server state, post-MVP). Confirm.
- **C2-6 Computed variables** (`kind: computed`, XLSForm `calculate`) are needed for the worked example (`age_band`). Proposed: recomputed from current values whenever read, `null` inputs propagate by §3, and they are exported as columns. Confirm, including whether they get a `__state` column.
- **C2-7 Full quota.** Proposed: `onFull` may show one block, then ends the session with an `outcome` (review §2.3 used `goto`, which would allow loops). Only `countOn: complete` is modelled.
- **C2-8 Choice codes.** Proposed: `1` and `"1"` are the same code (XForms stores text), and codes may not contain whitespace (multi answers are space-separated in XForms). Variable names that differ only by case are a warning (SPSS, Stata and LimeSurvey fold case).
- **C2-9 Not modelled in `osp-survey/0.1`:** the worked example's `age_band` calculate (needs `if()`, see C1's question on functions; the fixture tests `age >= 40` instead), `scores` and `reverseScored` from review §2.3, page-level `showIf`, page-order shuffling within a block, and numeric `min`/`max` (use a `constraint`). Add them if wanted.
