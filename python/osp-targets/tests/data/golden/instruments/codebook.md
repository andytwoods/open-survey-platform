# Codebook: Question bank provenance (invented test data)

- Survey id: `bank_demo`
- Version: 1
- Version checksum: `sha256:test-instruments`
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
- Decimals are exported as exact canonical text (`2.50` is `2.5`), never as binary floats.
- CSV is UTF-8, RFC 4180 (CRLF line ends, quoted fields).
- **Formula protection is on:** a cell starting with `=`, `+`, `-`, `@`, tab or carriage return gets a leading `'` so a spreadsheet shows it as text. Plain numbers such as `-3` are not changed. Strip one leading `'` from text cells to get the participant's exact input.

## Save mode

Mode: **not recorded**. Not recorded for this version (it has no publication with a save mode, or no responses yet). The per-response _save_mode column is authoritative.

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

This version assigns no conditions.

## Randomisation

This version has no randomisers and no shuffled items or choices.

## Instruments used

Questions inserted from a question bank, with the citation and licence recorded when the version was published. Cite each instrument you report.

### Demo two-item scale (DEMO-2)

- Bank item: `demo2`, version 1, bundled library
- Citation: Nobody, A. (2026). An invented scale. doi:10.0000/invented
- Licence: class `cc0`, holder Invented for tests, terms https://example.org/terms, read 2026-10-17
- Licence statement: Invented test data; no real instrument.
- Variables: `demo_q1`, `demo_q2`
- Scoring variables: `demo_total`

### Our lab's mood item

- Bank item: `3f1c2d4e-lab`, version 2, lab library
- Variables: `mood`

## Questions

In survey (flow) order. Conditions refer to other variables by export name.

### `demo_q1`

- Type: single. One choice code.
- Label: ... feel invented?
- Block / page: `demo` / `p_demo`
- Required: no
- Shown if: always
- From bank item: `demo2` v1 (bundled)
- CSV columns: `demo_q1`, `demo_q1__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; demo_q1__state says which state applies.

| Code | Label (en) |
|---|---|
| `0` | Never |
| `1` | Sometimes |
| `2` | Often |
| `3` | Always |

### `demo_q2`

- Type: single. One choice code.
- Label: ... feel like test data?
- Block / page: `demo` / `p_demo`
- Required: no
- Shown if: always
- From bank item: `demo2` v1 (bundled)
- CSV columns: `demo_q2`, `demo_q2__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; demo_q2__state says which state applies.

| Code | Label (en) |
|---|---|
| `0` | Never |
| `1` | Sometimes |
| `2` | Often |
| `3` | Always |

### `mood`

- Type: slider. A number picked on a slider, stored like an integer or decimal answer (see valueType); empty until the participant set it (it never defaults to a value).
- Label: Mood right now
- Slider: integer from 0 to 10 in steps of 1
- Block / page: `own` / `p_own`
- Required: no
- Shown if: always
- From bank item: `3f1c2d4e-lab` v2 (lab)
- CSV columns: `mood`, `mood__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; mood__state says which state applies.

### `age`

- Type: integer. Whole number.
- Label: Age
- Block / page: `own` / `p_own`
- Required: no
- Shown if: always
- CSV columns: `age`, `age__state`
- Missing values: Answered: the value. Unanswered, irrelevant, not-reached: empty; age__state says which state applies.

## Other variables

| Column | Kind | Details |
|---|---|---|
| `demo_total` | computed | computed as `demo_q1 + demo_q2` |

Each has a `<var>__state` column like a question: `answered` when it has a value; an embedded variable without a value (no parameter and no default, or a malformed one) is `unanswered`; a computed one whose input was null is `not-reached` if every question it reads was not reached, `irrelevant` if each was not reached or hidden, otherwise `unanswered`.

## Custom code (hooks) and data exports

This version runs no custom code, so it has no data-export capabilities.
