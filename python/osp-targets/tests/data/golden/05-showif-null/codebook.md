# Codebook: showIf with null values

- Survey id: `f05_showif_null`
- Version: 1
- Version checksum: `sha256:test-05-showif-null`
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

### `a`

- Type: integer. Whole number.
- Label: Pick any whole number (optional).
- Block / page: `p1` / `p1_page`
- Required: no
- Shown if: always
- CSV columns: `a`, `a__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; a__state says which state applies.

### `b`

- Type: integer. Whole number.
- Label: Pick another whole number (optional).
- Block / page: `p1` / `p1_page`
- Required: no
- Shown if: always
- CSV columns: `b`, `b__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; b__state says which state applies.

### `c`

- Type: multi. Any number of choice codes.
- Label: Pick some colours (optional).
- Block / page: `p1` / `p1_page`
- Required: no
- Shown if: always
- CSV columns: `c_red`, `c_green`, `c_blue`, `c__state`
- Missing values: Answered: 1 in each chosen choice's column, 0 in the others. Unanswered, irrelevant, not-reached: every choice column empty; c__state says which state applies.

| Code | Label (en) | Column |
|---|---|---|
| `red` | Red | `c_red` |
| `green` | Green | `c_green` |
| `blue` | Blue | `c_blue` |

### `p2_anchor`

- Type: text. Free text, trimmed.
- Label: This question is always shown.
- Block / page: `p2` / `p2_page`
- Required: no
- Shown if: always
- CSV columns: `p2_anchor`, `p2_anchor__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; p2_anchor__state says which state applies.

### `s_gt`

- Type: text. Free text, trimmed.
- Label: Shown when: a > 5
- Block / page: `p2` / `p2_page`
- Required: no
- Shown if: `a > 5`
- CSV columns: `s_gt`, `s_gt__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; s_gt__state says which state applies.

### `s_not_gt`

- Type: text. Free text, trimmed.
- Label: Shown when: not (a > 5)
- Block / page: `p2` / `p2_page`
- Required: no
- Shown if: `not a > 5`
- CSV columns: `s_not_gt`, `s_not_gt__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; s_not_gt__state says which state applies.

### `s_eq`

- Type: text. Free text, trimmed.
- Label: Shown when: a == b
- Block / page: `p2` / `p2_page`
- Required: no
- Shown if: `a == b`
- CSV columns: `s_eq`, `s_eq__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; s_eq__state says which state applies.

### `s_neq`

- Type: text. Free text, trimmed.
- Label: Shown when: a != 3
- Block / page: `p2` / `p2_page`
- Required: no
- Shown if: `a != 3`
- CSV columns: `s_neq`, `s_neq__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; s_neq__state says which state applies.

### `s_arith`

- Type: text. Free text, trimmed.
- Label: Shown when: a + b > 3
- Block / page: `p2` / `p2_page`
- Required: no
- Shown if: `a + b > 3`
- CSV columns: `s_arith`, `s_arith__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; s_arith__state says which state applies.

### `s_unanswered`

- Type: text. Free text, trimmed.
- Label: Shown when: not answered(a)
- Block / page: `p2` / `p2_page`
- Required: no
- Shown if: `not answered(a)`
- CSV columns: `s_unanswered`, `s_unanswered__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; s_unanswered__state says which state applies.

### `s_contains`

- Type: text. Free text, trimmed.
- Label: Shown when: contains(c, "red")
- Block / page: `p2` / `p2_page`
- Required: no
- Shown if: `contains(c, "red")`
- CSV columns: `s_contains`, `s_contains__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; s_contains__state says which state applies.

## Other variables

None.

## Custom code (hooks) and data exports

This version runs no custom code, so it has no data-export capabilities.
