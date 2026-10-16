# Codebook: All question types

- Survey id: `f01_all_types`
- Version: 1
- Version checksum: `sha256:test-01-all-types`
- Languages: en (default en)
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
- Decimals are exported exactly as typed (text), never as binary floats.
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
| `_late` | true if the response was submitted after the survey was closed (provisional, semantics open question M2-1). |
| `_end` | End outcome reached (e.g. complete); empty if none was recorded. |
| `_language` | Language the participant used. |

## Conditions

This version assigns no conditions.

## Randomisation

This version has no randomisers and no shuffled items or choices.

## Questions

In survey (flow) order. Conditions refer to other variables by export name.

### `n_int`

- Type: integer. Whole number.
- Label: How many cups of tea did you drink yesterday?
- Block / page: `p1` / `p1_page`
- Required: no
- Shown if: always
- CSV columns: `n_int`, `n_int__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; n_int__state says which state applies.

### `n_dec`

- Type: decimal. Exact decimal, exported as typed text (e.g. 2.50 stays 2.50) so no binary rounding creeps in.
- Label: What did your last coffee cost, in pounds?
- Block / page: `p1` / `p1_page`
- Required: no
- Shown if: always
- CSV columns: `n_dec`, `n_dec__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; n_dec__state says which state applies.

### `t_text`

- Type: text. Free text, trimmed.
- Label: Describe the weather today.
- Block / page: `p1` / `p1_page`
- Required: no
- Shown if: always
- CSV columns: `t_text`, `t_text__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; t_text__state says which state applies.

### `s_single`

- Type: single. One choice code.
- Label: Which fruit do you prefer?
- Block / page: `p1` / `p1_page`
- Required: no
- Shown if: always
- CSV columns: `s_single`, `s_single__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; s_single__state says which state applies.

| Code | Label (en) |
|---|---|
| `apple` | Apple |
| `banana` | Banana |
| `cherry` | Cherry |

### `m_multi`

- Type: multi. Any number of choice codes.
- Label: Which colours do you like?
- Block / page: `p1` / `p1_page`
- Required: no
- Shown if: always
- CSV columns: `m_multi_red`, `m_multi_green`, `m_multi_blue`, `m_multi__state`
- Missing values: Answered: 1 in each chosen choice's column, 0 in the others. Unanswered, irrelevant, not-reached: every choice column empty; m_multi__state says which state applies.

| Code | Label (en) | Column |
|---|---|---|
| `red` | Red | `m_multi_red` |
| `green` | Green | `m_multi_green` |
| `blue` | Blue | `m_multi_blue` |

### `d_date`

- Type: date. Calendar date, YYYY-MM-DD.
- Label: Pick any date in 2026.
- Block / page: `p1` / `p1_page`
- Required: no
- Shown if: always
- CSV columns: `d_date`, `d_date__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; d_date__state says which state applies.

## Other variables

None.

## Custom code (hooks) and data exports

This version runs no custom code, so it has no data-export capabilities.
