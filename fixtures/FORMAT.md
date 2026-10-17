# Fixture format

Surveys are real `osp-survey/0.1` documents (the `osp-spec` model, C2). Answer scripts and
expected traces keep the provisional formats C3a wrote (`osp-fixture-script/0`,
`osp-fixture-expected/0`); C3b did not need to change their shape.

Each fixture is `fixtures/NN-name/` with:

```text
survey.json            the survey            ("specVersion": "osp-survey/0.1")
scripts/<id>.json      one participant each  ("format": "osp-fixture-script/0")
expected/<id>.json     trace for that script ("format": "osp-fixture-expected/0")
pending.json           optional: what the survey cannot express yet ("osp-fixture-pending/0")
```

`scripts/` and `expected/` file names match one to one. All data is synthetic.
`tests/test_fixtures_shape.py` loads every survey through `osp_spec.parse` and requires zero
error diagnostics (warnings and info are allowed).

## 1. survey.json

The model, its JSON Schema and the validator are in `python/osp-spec`
(`schema/survey.schema.json`). C3a wrote the fixtures in a small v0 format before the model
existed; C3b converted them with `fixtures/tools/convert_v0.py`, which documents the mapping
and stays as a record (the v0 files are in git history up to commit `85db6ad`). Conventions
the traces rely on:

- **One block, one page.** Every fixture block is a `Block` with exactly one `Page`. The block
  keeps the v0 id and the page is `<block>_page`. Traces and scripts name **blocks**: a step's
  `page`, a script's `expectPage`, `orders.blocks` and the keys of `orders.items` are block ids.
- **Conditions** (`showIf`, `constraint`, branch `if`) are C1's AST (`osp_expr`), not text. The
  model has no comment field, so the v0 condition text was dropped; `osp_expr.to_text` prints
  it back. Question labels in fixtures 05 and 19 still spell out the condition.
- **Conditions from `assign`** are `assigned` variables (`variables[]`, `kind: "assigned"`),
  one per v0 design factor, all set by a single `assign` node `assign_design`.
- **Flow node ids**: `n_<block>` for block nodes, `branch_<n>`, `end_<outcome>`,
  `assign_design`; randomisers keep their v0 id (`r_blocks`, the PRNG stream id).
- **Id clashes.** Ids are unique across the whole survey, so a v0 choice list or block that
  shared an id with a question was renamed: `commute_list` (10), `tags_list` (19) and block
  `consent_blk` (20, which also changed that block's `page`/`expectPage` in its traces).
- **PRNG node ids** (§7 streams): randomiser `id`, **page** id for `itemOrder` (decided,
  R1-2; `itemOrder` lives on the page), question id for `choiceOrder`,
  `<assign node>/<variable>` for an assigned variable the engine draws itself.
- **Survey settings** the runner reads from `survey.json`: `settings.saveMode` and
  `settings.localCopy` (fixture 33).

### pending.json

A fixture whose survey uses something `osp-survey/0.1` cannot express leaves that part out of
`survey.json` and records it here (only fixture 20 has one, with no open question in it):

```jsonc
{
  "format": "osp-fixture-pending/0",
  "pending": ["C3a-2"],                 // open questions in planning/semantics.md
  "allowedDiagnostics": [               // error diagnostics the survey may have; every one
    { "code": "…", "pointer": "…" }     //   listed must still occur (no stale entries)
  ],
  "notExpressible": [ { "feature": "…", "openQuestion": "C3a-2", "why": "…", "v0": { … } } ]
}
```

`v0` keeps the left-out part verbatim, in the v0 survey format, so nothing is lost.

## 2. scripts/<id>.json

```jsonc
{
  "format": "osp-fixture-script/0",
  "id": "main",
  "description": "…",
  "sessionSeed": 4242,                        // positive integer (§7)
  "language": "en",
  "server": {                                 // what our server injects at session start
    "conditions": { "cond": "B" },
    "quotas": { "q_old": "open" | "full" }    // fixtures 20 and 24
  },
  "actions": [
    { "expectPage": "p1", "set": { "q1": 4 }, "do": "next" },
    { "setIfShown": { "q_x": 1, "q_y": 2 }, "do": "next" },
    { "do": "back" }
  ]
}
```

- `do`: `next` (submit the page: validate, then move on), `back`, `refresh` (reload the
  browser page), `resume` (leave and come back later; same contract as refresh, §5).
- `set` is applied before `do`. Every id in it must be visible on the current page.
  `setIfShown` applies only the ids that are visible (for randomised page orders).
  `null` clears an answer. Text is given raw, before trimming.
- `expectPage` is a sanity check on the page the action is taken on. It is left out when the
  page depends on the PRNG.
- Values are not submitted by `back`, `refresh` or `resume`, but they are kept: our server
  autosaves on every change (§5, spike E7).

### Script extensions (R6, fixtures 21–37)

All optional, so every earlier script is still valid. A runner that doesn't support one yet
should skip the script, not fail it.

| Field | Where | Meaning |
|---|---|---|
| `"do": "switchDevice"` | action | Continue on another device (runtime-design §5.4). The runner takes `snapshot(state)` as the server holds it and calls `restore(plan, snapshot)` on a device with no local copy. `"device": "B"` names the device now in use. `"restoreFrom": "local"` instead revives that device's own last local copy without reloading (a stale tab; fixture 25) |
| `"do": "retry"` | action | Send the pending effect again (runtime-design §3, §5.5). `next` sends the first call itself. A `refresh` or `resume` also re-sends a pending effect once, with the same idempotency key (semantics §5, R6-4); nothing else does, so the number of calls is fixed |
| `server.quotaCalls` | script | `{ quotaCheckNodeId: ["timeout" \| "lostReply" \| "ok", …] }`: what happens to the 1st, 2nd … call. `timeout`: the request never reaches the server. `lostReply`: the server records its result but the reply is lost. `ok`: the reply arrives. Calls past the list are `ok`. Idempotent per (session, node): once recorded, every reply carries the recorded result |
| `server.quotas` | script | As before: `"open"` or `"full"`, the result the server records on the first call that reaches it |
| `replay` | script | `{ "server": { … } }`: after the script, replay the response's event log through a fresh engine against this (different) server state. It must make **no** effect calls and must give exactly `response` |
| `storage` | script | `"blocked"`: IndexedDB is unavailable (private mode). In `every-page` mode answers are saved to the server on every change (R-1); in `end-only` mode the copy falls back to memory (§5.0), so a `refresh` or `resume` restarts the session from the first page with the same seed and conditions (semantics §5, R6-5; step `notice: "restarted"`). `settings.localCopy: "memory"` does the same without `storage` |

## 3. expected/<id>.json

```jsonc
{
  "format": "osp-fixture-expected/0",
  "fixture": "06-clear-on-back",
  "script": "main",
  "pending": [],               // open-question ids; non-empty = draft, do not assert yet
  "steps": [ { … }, … ],       // steps[0] = after session start, steps[i] = after actions[i-1]
  "invariants": [ … ],
  "response": { … }
}
```

So `steps` has one more entry than `actions`.

**Step**

| Field | Meaning |
|---|---|
| `index` | Position in `steps` |
| `page` | Id of the block shown (each fixture block has one page), or `null` once the session has ended |
| `visible` | Item ids shown, in display order (notes included) |
| `errors` | `{ id: { "kind": "required" } }`, `{ id: { "kind": "range" } }` (numeric `min`/`max`), `{ id: { "kind": "constraint", "message": "…" } }` or `{ id: { "kind": "invalid", "code": "…" } }` (unreadable input, e.g. `value.too_long`); when non-empty the page did not advance |
| `nav` | `{ "back": bool }`; `null` after the end |
| `questions` | Every question (not notes or calculates): `{ "state": …, "value": … }` |
| `orders` | `{ "blocks": {randomiserId: [...]}, "items": {blockId: [...]}, "choices": {questionId: [...]} }`; only shuffled nodes, only once reached |
| `conditions` | Assigned conditions (from the server at session start, §7) |
| `end` | End code, or `null` while running |
| `labels` | Optional. Rendered label (session language, pipes filled, piped text HTML-escaped) per visible item |
| `choiceLabels` | Optional. `[[value, label], …]` in display order |
| `effect` | Optional (R6, fixture 24). The pending effect, `{ "kind": "quota", "nodeId": … }`, or `null` when none is waiting |
| `device` | Optional (R6, fixture 25). The device the step happens on (`"A"`, `"B"`) |
| `notice` | Optional (fixtures 25, 33). A runtime-layer message the runner reports, not engine state: `"restarted"` (a memory-only session restarted on refresh) or `"conflict"` (this device's save was stale; it now shows the server copy, semantics §5, R6-6) |
| `builtins` | Optional (R6, fixture 32). Built-in variables (runtime-design §7a) on this page: `{ "trial": n, "position": { "randomiserId", "index", "of" } }`; `null` after the end |

`errors` only ever comes from a `next` in that step's action: a step after `back`,
`refresh`, `resume`, `switchDevice` or `retry` has `{}`.

**Values**: `integer` JSON integer; `decimal` JSON *string* (`"0.1"`), so no binary float
sneaks in (§2); `text` the trimmed string; `single` the code; `multi` an array of codes in
choice-list order (compare as a set); `date` `"YYYY-MM-DD"`; `slider` as `integer` or `decimal`
by its `valueType`. A **matrix** has no entry of its own: each row is a `single` question keyed
by its row variable id `<matrix id>_<row id>` (in `questions`, `answers`, `errors` and a script's
`set`), with CSV state column `<matrix name>_<row id>__state`; `visible` and `labels` list the
matrix id (semantics §2, C2c-1; fixture 38). `value` is `null` unless the state is `answered`.

**Response** (§1, §7, §9): `surveyId`, `surveyVersion`, `end`, `allocation` (`"server"`),
`sessionSeed`, `conditions`, `orders`, `answers` (the JSON export form: value + state per
question) and `csvState` (the CSV companion columns `<id>__state`, also for embedded and
computed variables). Fixture 20 adds the engine's `computed` and `embedded` values and
`variableStates` (the export state of each embedded and computed variable). Fixture 24 adds `effects`: the
recorded effect results, `[{ "kind": "quota", "nodeId", "quota", "result" }]`, which replay
reuses.

**Network** (optional, R6; fixtures 24 and 33): a top-level `network` object with call counts
for the runtime layer (R4), which the engine runner ignores: `quotaCalls` per `quotaCheck`
node, `snapshotWrites` (snapshot PUTs before submit) and `submits`.

**Placeholders**

- `"<engine>"`: depends on the PRNG. C4 fills it in from the engine; until then only the
  invariants are asserted. It can stand for an order, a `visible` list, a `page`, or a
  question's state object (fixture 13, where the page order decides which question is shown).
- `"<pending:…>"` marked a value an open question left undecided. No trace uses it since
  decisions batch 1 (16 Oct 2026); a new open question may use it again, with the id in the
  file's `pending` list.

**Invariants**

```jsonc
{ "kind": "permutation", "of": ["att1", "att2"], "paths": ["response.orders.items.p_att"] }
{ "kind": "equal", "paths": ["steps[1].page", "response.orders.blocks.r_blocks[0]"] }
```

`permutation`: every path's value is a permutation of `of`. `equal`: all paths hold the same
value (stability across back/refresh/resume, and that the order shown is the order recorded).
Paths are rooted at the expected file: `steps[i]…` or `response…`.

## 4. Trace conventions (C3a readings, flagged for C4)

These follow from semantics.md; they are written down so C4 and the harness agree.

1. **States are re-evaluated on every page change** for every question whose page has been
   reached. This is the §3 lowering (`clearNonRelevant()` on every page flip): a question made
   irrelevant by a changed answer is `irrelevant` and `null` from that submit on, even before
   its page is revisited; one made relevant again is `unanswered` until answered.
2. **Once reached, a question never goes back to `not-reached`.** If a submit after `back`
   takes its block off the path (a branch now goes the other way), it becomes `irrelevant`
   and its value is cleared on that submit; it is `unanswered` if the path later returns
   (semantics §3, C3a-6; fixture 34).
3. **A skipped empty block (§6) leaves its questions `irrelevant`**, not `not-reached`: the flow
   did get to the block; display logic hid every question. Back skips it too.
4. **During a session**, a visible question with a value is `answered` even before submit and
   even if its constraint fails (the step's `errors` say so). The final response only ever
   holds values that passed validation.
5. **Branches not taken and blocks after an `end`** leave their questions `not-reached`.
6. **Conditions** are present from `steps[0]`, because the server assigns them at session
   start (§7), and the response records them even if the `assign` node was never reached.
   Expressions and piping see them as `null` until the `assign` node is reached (C3a-7).

R6 readings, used by fixtures 21–37 (they follow from the rules above):

7. **Within the current page, `showIf` is live** (runtime-design §3, `answer → live show-if
   within the page`): a hidden question's state is `irrelevant` at once, but its value is only
   cleared when the page is submitted (fixtures 22, 29).
8. **A refresh, resume or device switch is not a page change.** Off-page states stay as they
   were at the last submit, so an unsubmitted change that would hide a later answer does not
   clear it (fixture 36).
9. **A value typed and then left with `back` is kept, unsubmitted**, and a later cascade clears
   it like any other value (fixtures 21, 29, 35, 37).
10. **`$trial` is the 1-based number of the current page on the participant's path** (R-7):
    pages skipped as empty don't count, and after `back` it is the number of the page now
    shown, so back then next gives the same number again (fixture 32).
