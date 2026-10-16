# Semantics decisions, batch 1 (approved 16 Oct 2026)

These are the open questions from `semantics.md` plus the server questions S-1 to S-4. Each recommendation comes from a cross-LLM review (GPT, Gemini, Qwen) and the lead.

- **Agree** = how many of the 3 reviewers backed this answer.
- **Lead** = an R1 question the reviewers didn't see; the lead decided it.

**Approved 16 Oct 2026:** the user delegated the choice to the lead, and every recommendation below was adopted as written. Task SEM1 folds them into `semantics.md` and updates the code and fixtures.

## Also decided by the lead (backend defaults, delegated by the user)

| Item | Decision |
|---|---|
| Retention | A retention policy is **required before publishing** (there's no silent default) |
| Deleting surveys | Published surveys can't be deleted; owners only; viewers can't export responses |
| Passwords | **The deployment decides** (user, 16 Oct 2026): `OSP_PASSWORD_MIN_LENGTH`, or institutional SSO later. The default is 8 plus the common-password blocklist |
| Signup | No self-signup in the MVP; adding it later requires email verification |
| Cookies and CSRF | Kept as built by C10 |
| Engine-computed orders | The lead checks the 385 realised `<engine>` values (permutation, stability, parity) and writes them into `expected/` after SEM1 |

## Contested (a decision changes behaviour)

| id | Recommendation | Agree | Alternative |
|---|---|---|---|
| C1-2 / C3a-8 | **Two-valued logic.** `not null` is true; `contains(null, v)` is false. So "did not pick X" is true for someone who didn't answer. The builder warns when `not` wraps a question that may be unanswered, and suggests `answered(x) and not …`. Type mismatches block publishing. At runtime they give null plus a logged diagnostic, never a crash | 2 | Gemini: three-valued, where `not null` is null and the question is hidden |
| C3a-7 | An assigned condition is **null until its `assign` node is reached**, though it is always recorded in the export | 2 | Qwen: visible from session start |
| C2-6 / C3a-2 | Computed variables export a value **and** a `__state` column (non-null → answered; null → unanswered; outside the path → not-reached or irrelevant) | 2 | Qwen: no state column |
| C2-9 | Add to `osp-survey/0.1`: `if()`, page-level `showIf`, numeric `min`/`max`. **Defer** dedicated `scores` and reverse scoring to 0.2 (use computed variables with `if()` meanwhile), plus page-order shuffling | 2 | GPT: scores now |
| S-1 | **Separate** the two timers: resume links expire after **30 days** of inactivity (configurable per survey); quota holds after 24 h. Resuming after the hold expired must take a quota place again | 1 | Gemini/Qwen: both 24 h. Recommended anyway, because multi-day studies (diaries) break with 24 h |
| R6-2 / R1 decimals | Decimals stored and exported as canonical strings (`2.50` → `2.5`). Arithmetic uses **28 significant digits, round half-even**, which is already built and checked against Python. Input longer than 28 digits is rejected | 1 | GPT: 34 digits. 28 is already implemented and exact in both engines |
| C3a-9 / R1-3 | Piped multi answer: labels in **displayed order**, joined with `", "`. Piped decimal: canonical form (`2.5`) | 2 | GPT: `"; "` separator |
| R6-1 / R1-7 | Trimming removes Unicode `White_Space` characters plus U+FEFF, and not zero-width space U+200B. Python and the TS engine use the **same explicit list**. No Unicode normalisation; the raw text is kept | 2 | Gemini: normalise to NFC |

## Agreed by all three reviewers (or lead, for R1 items)

| id | Decision |
|---|---|
| C1-1 | `x / 0` gives null, plus a logged diagnostic; a constant zero divisor blocks publishing |
| C1-3 | Add `if(cond, a, b)`: only the chosen branch is evaluated, and a null condition picks `b`. Both branches must have compatible types |
| C3a-1 / R1-6 | A page with a relevant note is shown. Notes have no state and no column. Empty-page skipping is per page |
| C3a-3 / C2-7 / R1-5 | Quotas use atomic server counts: a place is held at the check, used up on completion, and released on drop-out or after 24 h. `onFull` shows at most one block, then ends with `quota-full` (no `goto`). The result is recorded per node and reused on back, forward and replay |
| C3a-4 | (For 0.2) a score is null unless every item is answered, or an explicit `minAnswered` is set; reversal is `min + max − value` |
| C3a-5 | URL parameters are captured once at start and exported with value and state. A missing parameter takes its default (answered), or is unanswered if there's no default. A malformed one is recorded as unanswered with a diagnostic (the participant is never blocked) |
| C3a-6 | Going back and changing an answer so that a block drops out of the path makes that block's answers **irrelevant and cleared** on submit |
| C2-1 | Forward references are an error. Same-page references are allowed in either direction, but cycles are rejected. A reference into another branch arm or randomiser sibling is a warning |
| C2-2 | Logic refers to stable ids; export names can be renamed freely |
| C2-3 | A block appears once in the flow |
| C2-4 / R1-2 | `pick`: seeded shuffle, take the first `pick`, frozen at first reach |
| C2-5 / R1-2 | Each assigned variable is an independent uniform seeded draw, with stream id `<assign node>/<variable>`. Item order is keyed by page id |
| C2-8 | Codes are compared as strings (`1` = `"1"`), with no whitespace. **Variable names that differ only by case are an error** (it was a warning) |
| R6-3 | `$` namespace reserved. `$position` is 1-based in the innermost randomiser, `of` = `pick` or N, and null outside a randomiser. `${$trial}` works in labels |
| R6-4 | While a quota check is pending, the page stays and navigation is disabled. Refresh retries with the same idempotency key |
| R6-5 | Add `saveMode` and `localCopy` to survey settings. With memory-only storage, a refresh restarts with the same seed and conditions, and shows a notice |
| R6-6 | Two-device conflict: the server copy wins, the device that lost shows an explanation, and the lost copy is kept per S-3 |
| R1-1 | `surveyVersion` in seeds = the published version number as text, or `"draft"` for previews |
| R1-4 | Unreadable input (`12a`, `2026-02-30`) blocks Next with an "invalid" error, even on optional questions |
| R1-8 | If the server didn't assign a variable, the engine draws it and records `allocation: "seeded"` per variable |
| S-2 | **Accept late submits**, flagged `late` and not counted toward quotas (rejecting them lost data) |
| S-3 | The losing copy goes into an encrypted conflicts table, kept for a limited time, excluded from exports. The audit log stores only the id |
| S-4 | A retry with identical data returns the original success; different data returns 409 |
