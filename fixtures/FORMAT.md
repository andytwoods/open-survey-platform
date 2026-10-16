# Fixture format v0 (provisional)

Written by C3a before `osp-spec` (C2) exists. C3b converts every fixture to the real model, so
this format is deliberately small, regular and close to `planning/semantics.md` and the
`review.md` §2.3 example. Where it differs from §2.3, conditions are plain text instead of
JSONLogic.

Each fixture is `fixtures/NN-name/` with:

```text
survey.json            the survey            ("format": "osp-fixture-survey/0")
scripts/<id>.json      one participant each  ("format": "osp-fixture-script/0")
expected/<id>.json     trace for that script ("format": "osp-fixture-expected/0")
```

`scripts/` and `expected/` file names match one to one. All data is synthetic.

## 1. survey.json

```jsonc
{
  "format": "osp-fixture-survey/0",
  "description": "what the fixture tests",
  "id": "f06_clear_on_back",
  "version": 1,
  "title": "…",                      // text, see "Text" below
  "languages": ["en"],               // first one is the default
  "settings": { "backNavigation": true },
  "choiceLists": { "yesno": [ { "value": "yes", "label": "Yes" }, … ] },
  "design": { "factors": [ { "id": "cond", "levels": ["A", "B"] } ] },   // only with assign
  "blocks": { "p1": { "items": [ … ], "itemOrder": "fixed" | "shuffle" } },
  "flow": [ … ]
}
```

Fixture 20 also carries `metadata`, `embeddedData`, `scores`, `quotas` and a fuller `design`
exactly as in `review.md` §2.3. Those parts are undecided in semantics (C3a-1…5).

**Pages.** One block is one page (as in the Enketo spike: one `field-list` group per page).
`itemOrder` defaults to `"fixed"`.

**Items.** Every item has `id` (unique across the survey) and `type`.

| Field | Applies to | Meaning |
|---|---|---|
| `type` | all | `integer` `decimal` `text` `single` `multi` `date` (questions, §2), `note` (display only), `calculate` (fixture 20 only) |
| `label` | all but calculate | Text; may contain `${id}` pipes (§8) |
| `required` | questions | default `false` (§4) |
| `constraint` | questions | Expression; refers to the question by its own id, e.g. `age >= 18 and age <= 120` |
| `constraintMessage` | questions | Text shown when the constraint fails |
| `showIf` | questions | Expression; question is relevant when it is true (null counts as false, §3) |
| `choices` | single, multi | Name of a `choiceLists` entry |
| `choiceOrder` | single, multi | `"fixed"` (default) or `"shuffle"` |
| `expr` | calculate | Expression |

**Choices.** `{ "value": <string or integer>, "label": <text> }`. Values are codes (§2).

**Text.** A plain string (same in every language) or `{ "en": "…", "de": "…" }`.

**Expressions** (C1 grammar): numbers, `"double-quoted strings"`, question/condition ids,
`== != < <= > >=`, `and or not`, `+ - * /`, parentheses, `answered(id)`,
`contains(multiId, value)`. Usual precedence: `* /` over `+ -` over comparisons over `not` over
`and` over `or`. Fixture 20's calculate uses `if(…)`, which is outside the v0 grammar (C3a-2).

**Flow nodes** (§6):

| Node | Meaning |
|---|---|
| `{ "block": "p1" }` | Show that block's page |
| `{ "branch": { "if": expr, "then": [nodes], "else": [nodes] } }` | `else` optional |
| `{ "randomiser": { "id": "r1", "shuffle": [nodes] } }` | All children, in a shuffled order (§7) |
| `{ "assign": "design" }` | Point where the design's conditions take effect (§7) |
| `{ "quotaCheck": "q_old" }` | Fixture 20 only, pending C3a-3 |
| `{ "end": "code" }` | End the session with that code |

Running off the end of the flow is `end: "complete"` (§6).

**PRNG node ids** (§7 streams): randomiser `id`, block id for `itemOrder`, question id for
`choiceOrder`.

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
    "quotas": { "q_old": "open" | "full" }    // fixture 20 only, pending C3a-3
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
| `page` | Block id shown, or `null` once the session has ended |
| `visible` | Item ids shown, in display order (notes included) |
| `errors` | `{ id: { "kind": "required" } }` or `{ id: { "kind": "constraint", "message": "…" } }`; when non-empty the page did not advance |
| `nav` | `{ "back": bool }`; `null` after the end |
| `questions` | Every question (not notes or calculates): `{ "state": …, "value": … }` |
| `orders` | `{ "blocks": {randomiserId: [...]}, "items": {blockId: [...]}, "choices": {questionId: [...]} }`; only shuffled nodes, only once reached |
| `conditions` | Assigned conditions (from the server at session start, §7) |
| `end` | End code, or `null` while running |
| `labels` | Optional. Rendered label (session language, pipes filled, piped text HTML-escaped) per visible item |
| `choiceLabels` | Optional. `[[value, label], …]` in display order |

**Values**: `integer` JSON integer; `decimal` JSON *string* (`"0.1"`), so no binary float
sneaks in (§2); `text` the trimmed string; `single` the code; `multi` an array of codes in
choice-list order (compare as a set); `date` `"YYYY-MM-DD"`. `value` is `null` unless the state
is `answered`.

**Response** (§1, §7, §9): `surveyId`, `surveyVersion`, `end`, `allocation` (`"server"`),
`sessionSeed`, `conditions`, `orders`, `answers` (the JSON export form: value + state per
question) and `csvState` (the CSV companion columns `<id>__state`). Fixture 20 adds
`calculated`, `scores` and `embeddedData`, all pending.

**Placeholders**

- `"<engine>"`: depends on the PRNG. C4 fills it in from the engine; until then only the
  invariants are asserted. It can stand for an order, a `visible` list, a `page`, or a
  question's state object (fixture 13, where the page order decides which question is shown).
- `"<pending:C3a-N>"`: undecided in semantics; see `planning/semantics.md` "Open questions".

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
2. **Once reached, a question never goes back to `not-reached`** (but see C3a-6).
3. **A skipped empty block (§6) leaves its questions `irrelevant`**, not `not-reached`: the flow
   did get to the block; display logic hid every question. Back skips it too.
4. **During a session**, a visible question with a value is `answered` even before submit and
   even if its constraint fails (the step's `errors` say so). The final response only ever
   holds values that passed validation.
5. **Branches not taken and blocks after an `end`** leave their questions `not-reached`.
6. **Conditions** are present from `steps[0]`, because the server assigns them at session
   start (§7), and the response records them even if the `assign` node was never reached
   (C3a-7 covers referring to them before the node).
