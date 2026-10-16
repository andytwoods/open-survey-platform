# Codebook: Framing and incentive study

- Survey id: `srv_7f3c`
- Version: 3
- Version checksum: `sha256:test-20-worked-example`
- Languages: en, de (default en)
- Codebook format: `osp-codebook/1`

## How to read this data

Every question is in exactly one state. The value cell is filled only when the state is `answered`.

| State | Meaning | CSV value cell | JSON `value` |
|---|---|---|---|
| `answered` | Shown and answered. | the value | the value |
| `unanswered` | Shown, left empty (only possible when not required). | empty | null |
| `irrelevant` | Its page was reached, but its show-if hid it. | empty | null |
| `not-reached` | The flow never got to its page. | empty | null |

- **CSV:** an empty value cell plus a companion column `<var>__state` holding the state. **No numeric missing codes such as -99 are ever written**, so an average can never include one.
- **JSON:** every answer is `{state, value}`; `value` is `null` unless answered.
- **Multiple choice** questions get one 0/1 column per choice, `<var>_<code>`, plus `<var>__state`.
- Timestamps are UTC, ISO 8601 with milliseconds (`2026-10-16T09:30:00.000Z`).
- Decimals are exported as exact canonical text (`2.50` is `2.5`), never as binary floats.
- CSV is UTF-8, RFC 4180 (CRLF line ends, quoted fields).
- **Formula protection is on:** a cell starting with `=`, `+`, `-`, `@`, tab or carriage return gets a leading `'` so a spreadsheet shows it as text. Plain numbers such as `-3` are not changed. Strip one leading `'` from text cells to get the participant's exact input.

## Save mode

Mode: **every-page**. Answers were saved to the server on every page change. Partial sessions exist on the server, so drop-outs are visible to the researcher, but this export holds only submitted responses.

## Response metadata columns

| Column | Meaning |
|---|---|
| `_response_id` | Response id (server). |
| `_session_id` | Participant session id (pseudonymous). |
| `_version` | Published survey version the response belongs to (semantics §9). |
| `_version_checksum` | Checksum of that version's survey document. |
| `_plan_checksum` | Checksum of the runtime plan the participant's browser ran. |
| `_engine_version` | Version of the participant engine (web/engine). |
| `_allocation_mode` | How conditions were assigned: server (our server, at session start), seeded (the engine drew at least one condition from the session seed), or limesurvey-native. |
| `_save_mode` | every-page or end-only (runtime-design §5.0). |
| `_seed` | Session seed (positive integer, semantics §7); reproduces every order. |
| `_started_at` | Session start, UTC, ISO 8601. |
| `_submitted_at` | Submission accepted by the server, UTC, ISO 8601. |
| `_late` | true if the server accepted the submit after the session had expired (its quota holds were released or its resume link had expired); a late response is not counted toward quotas (semantics S-2). Set by the server, never by the browser. |
| `_after_close` | true if the response was submitted after the survey was closed; empty if not known. |
| `_end` | End outcome reached (e.g. complete); empty if none was recorded. |
| `_language` | Language the participant used. |

## Conditions

Assigned by the server at session start (semantics §7). One column per condition, named after it, holding the level in force.

| Column | Levels |
|---|---|
| `framing` | `gain`, `loss` |
| `incentive` | `£5 voucher`, `charity donation` |

## Randomisation

Each realised order is fixed at first reach and recorded per response as one cell: ids or codes separated by spaces, in the order shown. Empty means the participant never reached it. Every order is reproducible from `_seed`.

| Column | What is ordered | Of |
|---|---|---|
| `_order.items.attitudes_page` | items on page `attitudes_page` | `att1`, `att2`, `att3` |

## Questions

In survey (flow) order. Conditions refer to other variables by export name.

### `consent`

- Type: single. One choice code.
- Label: Do you consent to take part?
- Block / page: `consent_blk` / `consent_blk_page`
- Required: yes (while shown)
- Shown if: always
- CSV columns: `consent`, `consent__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; consent__state says which state applies.

| Code | Label (en) | Label (de) |
|---|---|---|
| `1` | Yes | Ja |
| `0` | No | Nein |

### `age`

- Type: integer. Whole number.
- Label: How old are you?
- Block / page: `demo` / `demo_page`
- Required: yes (while shown)
- Shown if: always
- Constraint: `age >= 18 and age <= 120` (message: Please enter an age between 18 and 120.)
- CSV columns: `age`, `age__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; age__state says which state applies.

### `att1`

- Type: single. One choice code.
- Label: With the ${incentive} you were offered, the programme seems fair.
- Block / page: `attitudes` / `attitudes_page`
- Required: no
- Shown if: always
- CSV columns: `att1`, `att1__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; att1__state says which state applies.

| Code | Label (en) | Label (de) |
|---|---|---|
| `1` | Strongly disagree | Strongly disagree |
| `2` | Disagree | Disagree |
| `3` | Neutral | Neutral |
| `4` | Agree | Agree |
| `5` | Strongly agree | Strongly agree |

### `att2`

- Type: single. One choice code.
- Label: I would support Programme A.
- Block / page: `attitudes` / `attitudes_page`
- Required: no
- Shown if: always
- CSV columns: `att2`, `att2__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; att2__state says which state applies.

| Code | Label (en) | Label (de) |
|---|---|---|
| `1` | Strongly disagree | Strongly disagree |
| `2` | Disagree | Disagree |
| `3` | Neutral | Neutral |
| `4` | Agree | Agree |
| `5` | Strongly agree | Strongly agree |

### `att3`

- Type: single. One choice code.
- Label: Programme A is too risky.
- Block / page: `attitudes` / `attitudes_page`
- Required: no
- Shown if: always
- CSV columns: `att3`, `att3__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; att3__state says which state applies.

| Code | Label (en) | Label (de) |
|---|---|---|
| `1` | Strongly disagree | Strongly disagree |
| `2` | Disagree | Disagree |
| `3` | Neutral | Neutral |
| `4` | Agree | Agree |
| `5` | Strongly agree | Strongly agree |

## Other variables

| Column | Kind | Details |
|---|---|---|
| `source` | embedded | URL parameter `src`, text, default `direct` |
| `age_band` | computed | computed as `if(age < 40, "18-39", "40+")` |
| `att_score` | computed | computed as `(att1 + att2 + (6 - att3)) / 3` |

Each has a `<var>__state` column like a question: `answered` when it has a value; an embedded variable without a value (no parameter and no default, or a malformed one) is `unanswered`; a computed one whose input was null is `not-reached` if every question it reads was not reached, `irrelevant` if each was not reached or hidden, otherwise `unanswered`.

## Quotas

| Quota | Counts when | Limit | When full |
|---|---|---|---|
| `q_old` | `age_band == "40+"` | 150 | show `screenout`, then outcome `quota_full` |

## Custom code (hooks) and data exports

This version runs no custom code, so it has no data-export capabilities.
