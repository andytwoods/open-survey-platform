# Codebook: End nodes

- Survey id: `f11_end_nodes`
- Version: 1
- Version checksum: `sha256:test-11-end-nodes`
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

### `eligible`

- Type: single. One choice code.
- Label: Are you willing to answer two more questions?
- Block / page: `p1` / `p1_page`
- Required: yes (while shown)
- Shown if: always
- CSV columns: `eligible`, `eligible__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; eligible__state says which state applies.

| Code | Label (en) |
|---|---|
| `yes` | Yes |
| `no` | No |

### `rating`

- Type: integer. Whole number.
- Label: Rate your breakfast today from 1 to 10.
- Block / page: `p2` / `p2_page`
- Required: yes (while shown)
- Shown if: always
- CSV columns: `rating`, `rating__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; rating__state says which state applies.

### `extra`

- Type: text. Free text, trimmed.
- Label: Anything else about breakfast?
- Block / page: `p3` / `p3_page`
- Required: no
- Shown if: always
- CSV columns: `extra`, `extra__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; extra__state says which state applies.

## Other variables

None.

## Custom code (hooks) and data exports

This version runs no custom code, so it has no data-export capabilities.
