# fixtures/

Shared test fixtures used by every test layer: engine (C4), XLSForm export (C6), the Enketo
harness (C8) and the builder. Each folder `NN-name/` holds a survey, one or more answer scripts
and one expected trace per script. Surveys are `osp-survey/0.1` documents (`python/osp-spec`);
scripts and traces use the fixture formats in [`FORMAT.md`](FORMAT.md). C3b converted the
surveys from C3a's provisional v0 format with `tools/convert_v0.py`. All answers are
synthetic. No real personal data, ever.

`tests/test_fixtures_shape.py` checks that every folder has all three parts, that the JSON
parses, that every survey loads through `osp_spec` with zero error diagnostics (a fixture's
`pending.json` may allow specific ones; none does today) and that every `pending` id exists in
`planning/semantics.md`. Current warnings: fixture 20 has an untranslated `de` consent label
(`text.missing_translation`, as in `review.md` §2.3) and an unplaced `screenout` block
(`block.unused`, see below).

## Fixtures

| # | Folder | Scripts | Tests |
|---|---|---|---|
| 01 | `01-all-types` | answered, empty | One page with integer, decimal, text, single, multi, date and a note. |
| 02 | `02-required` | main, many-books | Required checks on submit; required applies only while relevant (§4). |
| 03 | `03-constraints` | main, boundary-low, boundary-high | Integer, decimal and text constraints with messages; unanswered values skip checks. |
| 04 | `04-text-whitespace` | whitespace, trimmed-optional | §2 text: trim, whitespace-only = unanswered, internal whitespace kept. |
| 05 | `05-showif-null` | all-null, a7-b-null, a3-b3 | §3 null semantics in showIf: comparisons, not, arithmetic, answered(), contains(). |
| 06 | `06-clear-on-back` | main, relevance-returns | §3: a previously answered question that becomes irrelevant is cleared on page submit. |
| 07 | `07-back-navigation` | main | §5: back keeps values; relevance of later pages is re-evaluated. |
| 08 | `08-back-disabled` | main | §5 per-survey setting backNavigation = false. |
| 09 | `09-refresh-resume` | main, refresh-at-start | §5/§7: refresh and resume restore page, values, orders and condition. |
| 10 | `10-empty-block-skipped` | no-car, has-car | §6: a block with no relevant questions is skipped silently (also on back). |
| 11 | `11-end-nodes` | ineligible, early-exit, complete | §6: explicit end nodes with codes, inside branches and at the end of the flow. |
| 12 | `12-implicit-end` | skip-branch, take-branch | §6: reaching the end of the flow without an end node counts as end: complete. |
| 13 | `13-randomiser-blocks` | main | §7 randomiser node shuffling blocks; order fixed at first reach, stable on back/refresh. |
| 14 | `14-item-order-shuffle` | main | §7 itemOrder shuffle within a block; recorded and stable across back. |
| 15 | `15-choice-order-shuffle` | seed-small, seed-large | §7 choice-order shuffle (XForms randomize) on single and multi questions. |
| 16 | `16-assign` | control, treatment | §7 assign: server-assigned condition drives a branch, is piped and is recorded. |
| 17 | `17-piping` | main, all-empty, irrelevant-had-value | §8 piping: choice label, raw values, HTML escaping, empty for missing values. |
| 18 | `18-multi-language` | en, de | Two languages: labels, choice labels, constraint messages and piping per session. |
| 19 | `19-expressions` | x10, x-neg | §2/§3 expressions: + - * /, precedence, and/or/not, contains(), decimal (not float). |
| 20 | `20-worked-example` | declined, complete-gain, loss-charity-back-refresh, screenout-quota-full | `review.md` §2.3 in full: consent gate, constraint, calculate, quota, 2×2 assign, branch, shuffled block, piping, score. **Pending** (C3a-1 to C3a-5). |

### Adversarial fixtures (R6)

Transition fixtures from `planning/runtime-design.md` §4. They use the script and trace
extensions in [`FORMAT.md`](FORMAT.md) §2–§4 (`switchDevice`, `retry`, `quotaCalls`, `replay`,
`storage`, `effect`, `device`, `builtins`, `network`).

| # | Folder | Scripts | Tests |
|---|---|---|---|
| 21 | `21-back-cascade-three-levels` | change-root, change-root-then-restore, change-middle | §3: a → b → c → d over four pages; changing a after back clears b, c, d in one submit (incl. an unsubmitted d); restoring a brings b back empty and required. |
| 22 | `22-clearing-chain` | big-then-small, same-page-toggle | §3: clearing y hides z and v but reveals w (`not answered(y)`); same-page live hide, then clear on submit; the old value never returns. |
| 23 | `23-refresh-every-step` | arm-a | §5/§7: a refresh before and after every action, after a failed constraint and after back; choice order and condition stable. |
| 24 | `24-quota-pending-retry` | timeout-refresh-lost-reply, full | runtime-design §3/§5.5: quota effect times out, survives a refresh, loses a reply, resolves; recorded result reused on back and on replay. **Pending** (C3a-3, R6-4). |
| 25 | `25-second-device-resume` | a-to-b-mid-page, stale-device-a | runtime-design §5.4: snapshot hand-off to device B mid-page; back on B into pages answered on A. Stale device A after B moved on is **pending** (R6-6). |
| 26 | `26-decimal-edge-cases` | exact, trailing-zeros, precision | §2: 0.1 + 0.2 == 0.3 (incl. a constraint a float would fail), 0.1 × 0.2 == 0.02, 2^53 + 1. Trailing zeros and precision are **pending** (R6-2). |
| 27 | `27-unicode-text` | kept-as-typed, unicode-edges | §2/§8: emoji with modifier, RTL (Hebrew, Arabic), internal NBSP and zero-width space kept; markup escaped when piped. Non-ASCII whitespace at the ends and NFC are **pending** (R6-1). |
| 28 | `28-regression-order-refresh` | refresh-before-answer | Spike workaround 1: item and choice order fixed at first reach, before render; refresh with nothing answered, resume, back + refresh. |
| 29 | `29-regression-clear-on-page-change` | hide-refresh-show | Spike workaround 2 (E8): same-page hide cleared on submit; stays cleared across refresh/resume; returns empty. |
| 30 | `30-regression-server-resume` | storage-blocked | Spike workaround 3 (E7, R-1): no local copy; refresh and resume restore unsubmitted answers from the server. |
| 31 | `31-regression-choice-label-piping` | en, de | Spike workaround 4 (§8): label not code (integer codes, shuffled list), per language, after back-and-change and refresh. |
| 32 | `32-trial-position-builtins` | trial, position | runtime-design §7a, R-7: `$trial` skips empty blocks and doesn't count failed submits, refreshes or revisits after back. `$position` is **pending** (R6-3); `${$trial}` piping is not expressible (`pending.json`). |
| 33 | `33-end-only-save` | browser-copy, storage-blocked | runtime-design §5.0: no snapshot writes before submit; refresh/resume from the browser copy. **Pending** (R6-5): the model has no `saveMode`. |
| 34 | `34-branch-change-after-back` | car-then-bus, car-bus-car | A branch leads elsewhere after back-and-change. **Pending** (C3a-6). |
| 35 | `35-back-change-empty-block` | kids-none-kids | §3/§4/§6: a change after back empties a visited block: cleared, skipped on next and back, a later required question appears; the block returns empty. |
| 36 | `36-refresh-unsubmitted-change` | change-refresh-revert | §3/§5: refresh is not a submit, so an unsubmitted change does not clear later answers; submitting it does. |
| 37 | `37-constraint-after-back` | lower-budget | §4: lowering budget after back makes an accepted `spend <= budget` fail on its next submit; the value is kept until fixed. |

## Coverage

| Feature | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| integer | x | x | x | x | x |  | x |  | x | x | x |  | x |  |  |  | x | x | x | x |
| decimal | x |  | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | x |  |
| text | x | x | x | x | x | x | x | x |  | x | x | x | x | x |  | x | x | x | x |  |
| single | x | x |  |  |  | x | x | x | x | x | x | x | x | x | x | x | x | x |  | x |
| multi | x | x |  |  | x |  |  |  |  |  |  |  |  |  | x |  |  |  | x |  |
| date | x | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| note | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | x |
| required (§4) |  | x | x | x |  | x |  |  |  | x | x | x |  |  |  |  | x | x |  | x |
| required only while relevant (§4) |  | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| constraint + message (§4) |  |  | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  | x |  | x |
| constraint skipped when unanswered (§4) |  |  | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| showIf |  | x |  | x | x | x | x |  |  | x |  |  |  |  |  |  | x |  | x |  |
| null semantics in conditions (§3) |  |  |  |  | x |  |  |  |  |  |  |  |  |  |  |  |  |  | x |  |
| referring to an irrelevant question gives null (§3) |  |  |  |  |  | x |  |  |  |  |  |  |  |  |  |  | x |  |  |  |
| value cleared when it becomes irrelevant after back (§3) |  |  |  |  |  | x |  |  |  |  |  |  |  |  |  |  | x |  |  |  |
| whitespace-only text = unanswered, trimming (§2) |  |  |  | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| decimal, not float (§2) |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | x |  |
| arithmetic, precedence, and/or/not, contains() |  |  |  |  | x |  |  |  |  |  |  |  |  |  |  |  |  |  | x |  |
| back navigation (§5) |  |  |  |  |  | x | x |  |  | x |  |  | x | x |  |  | x |  |  | x |
| back disabled (§5) |  |  |  |  |  |  |  | x |  |  |  |  |  |  |  |  |  |  |  |  |
| refresh (§5) |  |  |  |  |  |  |  |  | x |  |  |  | x |  |  |  |  |  |  | x |
| resume (§5) |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  |  |  |  |  |  |
| empty block skipped (§6) |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  |  |  |  |  |
| branch |  |  |  |  |  |  |  |  | x |  | x | x |  |  |  | x | x |  |  | x |
| explicit end node with code (§6) | x |  | x |  |  |  |  |  | x |  | x |  |  |  |  | x | x |  |  | x |
| implicit end (§6) |  | x |  | x | x | x | x | x |  | x |  | x | x | x | x |  |  | x | x |  |
| randomiser over blocks (§7) |  |  |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  |  |
| item order shuffle (§7) |  |  |  |  |  |  |  |  | x |  |  |  |  | x |  |  |  |  |  | x |
| choice order shuffle (§7) |  |  |  |  |  |  |  |  | x |  |  |  |  |  | x |  |  |  |  |  |
| order stable on back/refresh/resume (§7) |  |  |  |  |  |  |  |  | x |  |  |  | x | x |  |  |  |  |  | x |
| assign, server-assigned conditions (§7) |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  | x |  |  |  | x |
| piping a choice label (§8) |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | x | x |  |  |
| piping a raw value or condition (§8) |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | x | x |  |  | x |
| piping unanswered / irrelevant / not-reached = empty (§8) |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | x |  |  |  |
| piped text HTML-escaped (§8) |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | x |  |  |  |
| multi-language |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | x |  | x |
| calculate, quota, score, embedded data (pending) |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | x |

### Coverage, fixtures 21–37 (R6)

Pending scripts count where their decided parts are asserted once the question is settled.

| Feature | 21 | 22 | 23 | 24 | 25 | 26 | 27 | 28 | 29 | 30 | 31 | 32 | 33 | 34 | 35 | 36 | 37 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| integer | x | x | x |   | x |   |   |   | x | x |   | x | x | x | x |   | x |
| decimal |   |   |   |   |   | x |   |   |   |   |   |   |   |   |   |   |   |
| text | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x |
| single | x |   | x | x | x |   |   | x | x |   | x | x | x | x | x | x |   |
| required (§4) | x |   | x | x | x |   |   | x | x | x | x | x | x | x | x | x | x |
| required only while relevant (§4) | x |   |   |   |   |   |   |   |   |   |   |   |   |   | x |   |   |
| constraint + message (§4) |   |   | x |   |   | x |   |   |   |   |   |   |   |   |   |   | x |
| constraint broken by an earlier answer changed after back (§4) |   |   |   |   |   |   |   |   |   |   |   |   |   |   |   |   | x |
| showIf | x | x |   |   | x | x | x |   | x | x |   | x |   |   | x | x | x |
| live showIf within a page |   | x |   |   |   |   |   |   | x |   |   |   |   |   | x |   |   |
| null semantics in conditions (§3) | x | x |   |   |   |   |   |   |   |   |   |   |   |   | x |   |   |
| cascade: clearing one value hides or reveals others (§3) | x | x |   |   |   |   |   |   |   |   |   |   |   |   |   |   |   |
| value cleared when it becomes irrelevant after back (§3) | x | x |   |   |   |   |   |   | x |   |   |   |   |   | x | x | x |
| cleared value does not return when relevant again (§3, E8) | x | x |   |   |   |   |   |   | x |   |   |   |   |   | x |   |   |
| unsubmitted change not applied by refresh (§3, §5) |   |   |   |   |   |   |   |   |   |   |   |   |   |   |   | x |   |
| whitespace-only text = unanswered, trimming (§2) |   | x |   |   |   |   | x |   |   | x |   |   |   |   |   |   |   |
| Unicode text: emoji, RTL, NBSP, zero-width (§2) |   |   |   |   |   |   | x |   |   |   |   |   |   |   |   |   |   |
| decimal, not float (§2) |   |   |   |   |   | x |   |   |   |   |   |   |   |   |   |   |   |
| back navigation (§5) | x | x | x | x | x |   |   | x | x | x | x | x |   | x | x | x | x |
| refresh (§5) |   | x | x | x |   |   |   | x | x | x | x | x | x |   |   | x |   |
| refresh at every step (§5) |   |   | x |   |   |   |   |   |   |   |   |   |   |   |   |   |   |
| resume (§5) |   |   |   |   |   |   |   | x | x | x |   |   | x |   |   |   |   |
| resume on a second device (runtime-design §5.4) |   |   |   |   | x |   |   |   |   |   |   |   |   |   |   |   |   |
| storage blocked (R-1, §5.0) |   |   |   |   |   |   |   |   |   | x |   |   | x |   |   |   |   |
| empty block skipped (§6) |   |   |   |   |   |   |   |   |   |   |   | x |   |   | x | x |   |
| branch |   |   | x |   |   |   |   |   |   |   |   |   |   | x |   |   |   |
| branch path changes after back (pending C3a-6) |   |   |   |   |   |   |   |   |   |   |   |   |   | x |   |   |   |
| explicit end node with code (§6) |   |   |   | x |   |   |   |   |   |   |   |   |   |   |   |   |   |
| implicit end (§6) | x | x | x |   | x | x | x | x | x | x | x | x | x | x | x | x | x |
| randomiser over blocks (§7) |   |   |   |   |   |   |   |   |   |   |   | x |   |   |   |   |   |
| item order shuffle (§7) |   |   |   |   |   |   |   | x |   |   |   |   |   |   |   |   |   |
| choice order shuffle (§7) |   |   | x |   | x |   |   | x |   |   | x |   |   |   |   |   |   |
| order stable on back/refresh/resume/device switch (§7) |   |   | x |   | x |   |   | x |   |   | x | x |   |   |   |   |   |
| assign, server-assigned conditions (§7) |   |   | x |   | x |   |   |   |   |   |   |   |   |   |   |   |   |
| piping a choice label (§8) |   |   |   |   |   |   |   |   |   |   | x |   |   |   |   |   |   |
| piping a raw value (§8) |   |   |   |   |   |   | x |   |   |   |   |   |   |   |   |   |   |
| piped text HTML-escaped (§8) |   |   |   |   |   |   | x |   |   |   |   |   |   |   |   |   |   |
| multi-language |   |   |   |   |   |   |   |   |   |   | x |   |   |   |   |   |   |
| quota effect: pending, retry, recorded result, replay (pending) |   |   |   | x |   |   |   |   |   |   |   |   |   |   |   |   |   |
| $trial (R-7) / $position (pending R6-3) |   |   |   |   |   |   |   |   |   |   |   | x |   |   |   |   |   |
| end-only save mode (pending R6-5) |   |   |   |   |   |   |   |   |   |   |   |   | x |   |   |   |   |

## Placeholders and pending traces

- `"<engine>"` marks a value that depends on the PRNG (shuffled orders, and in fixture 13 the
  page sequence). Only the file's `invariants` are asserted until C4 fills these in.
- Every trace in `20-worked-example` is marked `"pending"`: notes-only pages, `calculate`,
  `quotaCheck`, `scores` and `embeddedData` are not yet defined in `planning/semantics.md`
  (open questions C3a-1 to C3a-5). The traces are drafts under the assumptions stated there.
  The survey parts the model cannot express yet are listed below.
- R6 pending traces (drafts; only the decided parts are meant to hold):

  | Fixture / script | Open question | Draft assumption |
  |---|---|---|
  | 24 both scripts | C3a-3, R6-4 | While the quota call is pending, the submitted page stays shown with back off; `full` shows the `onFull` block, then ends with its `outcome` (C2-7 proposal); back from that block is `<pending:C3a-3>` |
  | 25 `stale-device-a` | R6-6 | Steps up to the stale submit are asserted as written; everything after it is a placeholder |
  | 26 `trailing-zeros`, `precision` | R6-2 | Which questions show is computed with exact decimals; stored values are placeholders |
  | 27 `unicode-edges` | R6-1 | Stored values, visibility and labels are placeholders |
  | 32 `position` | R6-3 | `index` 1-based within the randomiser, `of` = number of children; outside a randomiser it is a placeholder |
  | 33 both scripts | R6-5 | `browser-copy` is runtime-design §5.0 as written; `storage-blocked` after the refresh is a placeholder |
  | 34 both scripts | C3a-6 | States and values of the block the branch no longer leads to are placeholders |

## Not expressible in osp-survey/0.1

R6 additions, each kept in its fixture's `pending.json`:

| Fixture | Feature | Why | Open question |
|---|---|---|---|
| 32 | Piping `${$trial}` and `${$position.index}` in a label | `$` names are not identifiers, so it is `pipe.invalid`; the traces record the values in `steps[].builtins` instead | R6-3 |
| 33 | `settings.saveMode: "end-only"`, `localCopy: "browser"` | `Settings` only has `backNavigation` | R6-5 |

The rest are in fixture 20 (`20-worked-example`). These parts are left out of its `survey.json` and kept
verbatim, in v0 form, in `20-worked-example/pending.json`; nothing was invented to stand in
for them. Its traces were already pending and are unchanged.

| Feature | Why | Open question |
|---|---|---|
| `calculate` item `age_band = if(age < 40, "18-39", "40+")` | The model has computed variables, but the expression grammar has no `if()`, so there is no AST to store | C3a-2 |
| Quota `q_old` and its `quotaCheck` node | The model has quotas, but `when` uses `age_band` (above), and `onFull` needs an `outcome` end code; v0 only says `goto: screenout` | C3a-3 |
| `scores` (`att_score`, mean with reverse) and per-item `reverseScored` | No scores in the model | C3a-4 |
| `design.allocation` (`balanced`, `strata`, `fallback: seeded-random`) | No allocation settings in the model. `design.between` is implied: both factors are `assigned` variables set by one `assign` node | none yet |

Consequence: block `screenout` is reached only through the quota, so it is in `blocks` but not
in the flow (`block.unused` warning). The question `age` had no label in §2.3; the model
requires one, so the converter gave it "How old are you?" (the only content it added).
Expressible and converted: `metadata.license`/`ddi`, `embeddedData` (as an `embedded`
variable `source`; how it is recorded is still C3a-5), the 2×2 design (two `assigned`
variables), piping `${incentive}`.

## Not covered yet

- Open questions without fixtures: conditions referred to before `assign` (C3a-7),
  `not contains(null, …)` (C3a-8), piping `multi` and `decimal` answers (C3a-9). Branch path
  changes after back (C3a-6) now has fixture 34.
- Not covered by the R6 set: a quota whose `when` is false (does `quotaCheck` call the server at
  all?), `set` then `back` on the same page changing relevance before the back (is back a
  submit for clearing?), refresh after the end, hook effects (R7's own adversarial gate), and
  the `multi` and `date` types in cascades.
- Also missing: `limesurvey-native` allocation, the seeded-random fallback when the server sends
  no condition, randomisers that pick a subset, language fallback for missing translations,
  date comparisons in expressions, and checking that randomiser streams are independent.
