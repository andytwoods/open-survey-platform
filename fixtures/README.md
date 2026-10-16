# fixtures/

Shared test fixtures used by every test layer: engine (C4), XLSForm export (C6), the Enketo
harness (C8) and the builder. Each folder `NN-name/` holds a survey, one or more answer scripts
and one expected trace per script. The format is provisional and written down in
[`FORMAT.md`](FORMAT.md); C3b converts it to `osp-spec` once C2 lands. All answers are
synthetic. No real personal data, ever.

`tests/test_fixtures_shape.py` checks that every folder has all three parts, that the JSON
parses and that every `pending` id exists in `planning/semantics.md`.

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

## Placeholders and pending traces

- `"<engine>"` marks a value that depends on the PRNG (shuffled orders, and in fixture 13 the
  page sequence). Only the file's `invariants` are asserted until C4 fills these in.
- Every trace in `20-worked-example` is marked `"pending"`: notes-only pages, `calculate`,
  `quotaCheck`, `scores` and `embeddedData` are not yet defined in `planning/semantics.md`
  (open questions C3a-1 to C3a-5). The traces are drafts under the assumptions stated there.

## Not covered yet

- Open questions without fixtures: branch path changes after back (C3a-6), conditions referred
  to before `assign` (C3a-7), `not contains(null, …)` (C3a-8), piping `multi` and `decimal`
  answers (C3a-9).
- Also missing: `limesurvey-native` allocation, the seeded-random fallback when the server sends
  no condition, randomisers that pick a subset, language fallback for missing translations,
  date comparisons in expressions, and checking that randomiser streams are independent.
