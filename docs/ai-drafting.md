# Drafting with an AI assistant

Open Survey Platform ships an **MCP server**, `osp-mcp`. MCP (the Model Context Protocol) is
how AI assistants such as Claude call tools. Point your assistant at `osp-mcp` and you can
describe a study in plain words; the assistant drafts the survey in your lab, you review it in
the builder, and you publish it yourself when it is right.

The server **drafts only**. It has no tool that publishes, deletes a survey, exports data or
reads participant responses, whatever role it runs as. Every edit it makes is an ordinary
survey op, validated by the same rules as the builder's, saved in the edit history and
undoable; the researcher keeps the last word.

## Setting it up

`osp-mcp` runs on the machine that can reach the platform's database, with the same two
settings `osp-api` and `osp-cli` use plus who it acts as:

| Variable | Meaning |
|---|---|
| `OSP_DATABASE_URL` | The platform's database (`sqlite:///.data/osp.db` in `make dev`, or your Postgres URL). |
| `OSP_STORE_KEYS` | The encryption keyring (`.data/dev-keys.env` in `make dev`; your secret store in production). |
| `OSP_MCP_USER` | The researcher the drafts belong to: the same user id your host gives `osp-api`. |
| `OSP_MCP_LAB` | The lab the surveys are created in. |
| `OSP_MCP_ROLE` | `editor` (default), `owner` or `viewer`. A viewer can read but not draft. |
| `OSP_MCP_NAME` | Optional display name for the edit history. |
| `OSP_MCP_BUILDER_URL` | Where the builder opens a survey, with `{id}`. Default `http://localhost:5173/surveys/{id}` (the `make dev` builder); behind a host use the host's editor URL. |

In an MCP client's configuration (Claude Desktop, Claude Code and others take this JSON
shape) the server is a command to launch:

```json
{
  "mcpServers": {
    "open-survey-platform": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/open-survey-platform", "osp-mcp"],
      "env": {
        "OSP_DATABASE_URL": "sqlite:////path/to/open-survey-platform/.data/osp.db",
        "OSP_STORE_KEYS": "k1:…",
        "OSP_MCP_USER": "dev-researcher",
        "OSP_MCP_LAB": "dev-lab"
      }
    }
  }
}
```

`uv run osp-mcp tools` prints the tool list without touching a database, which is a quick
way to check the installation. The server speaks MCP over standard input and output; it does
not open a port.

!!! note "Who is the assistant?"
    There is no sign-in in `osp-mcp`, as there is none in `osp-api`: whoever launches the
    process says which researcher it acts as, the way a host does with signed headers. Give
    it the researcher's own id so the edit history names the right person, and the keys of a
    database you are happy for that person to edit. A production deployment should run it
    for one researcher at a time, never as a shared service.

## The tools

| Tool | What it does |
|---|---|
| `list_surveys`, `create_survey`, `get_survey` | The lab's surveys; a new draft (from a title, or a whole osp-survey document); a survey's outline with every id, type and label, or the full JSON. |
| `add_block`, `add_page`, `add_question`, `add_choice` | Build the structure in typed steps: a block with its pages and questions (placed in the flow), a page with its questions, one question with choices, rows, help, `required` and a `showIf` condition, one more option. |
| `set_property`, `set_condition` | Any field of any object (`/metadata` and `/settings` included); a condition from text such as `age >= 18 and answered(coffee)`. |
| `apply_ops`, `list_ops`, `describe_op` | Any edit op by id, in one all-or-nothing transaction, with the catalogue and each op's parameter schema. The same ops the builder sends. |
| `validate`, `preview` | Every error and warning with a pointer, plus what the builder will ask for before publishing (retention, consent); compile the draft into the participant plan and return the builder link where **Preview** runs it. |
| `undo`, `history` | Reverse a transaction (or redo an undo); the edit history. |

Two ops are deliberately not offered: `set_hooks` (researcher hooks are custom code, written
and audited by a person) and `apply_patch` (raw JSON surgery belongs to the builder's JSON
view). Everything else in the op catalogue is available through `apply_ops`.

## A worked example: describe your study, get a draft

Suppose you tell the assistant:

> I'm studying whether coffee affects sleep. Screen for age (adults only) and whether they
> drink coffee at all. Coffee drinkers should be asked how many cups a day and when their
> last cup is. Everyone rates how well they fall asleep and stay asleep. Keep data for 90
> days after the study closes and add a short consent statement.

A capable assistant makes roughly these calls (each block below is one tool call; the test
suite replays them exactly, with `$SURVEY` standing for the id the first call returns).

**1. Create the draft.** It starts with one block, one page and an empty note.

```json
{"tool": "create_survey", "arguments": {"title": "Coffee and sleep"}}
```

**2. Screening.** A block with one page and two required questions, placed in the flow.

```json
{"tool": "add_block", "arguments": {
  "survey_id": "$SURVEY",
  "block_id": "screening",
  "title": "Screening",
  "pages": [{
    "id": "screen",
    "questions": [
      {"id": "age", "type": "integer", "label": "How old are you?", "required": true,
       "properties": {"min": 18, "max": 120}},
      {"id": "coffee", "type": "single", "label": "Do you drink coffee?", "required": true,
       "choices": ["Yes", "No"]}
    ]
  }]
}}
```

**3. Coffee habits, only for coffee drinkers.** The page's `showIf` refers to the earlier
question by id; codes are compared, so "Yes" is `1`.

```json
{"tool": "add_block", "arguments": {
  "survey_id": "$SURVEY",
  "block_id": "habits",
  "title": "Coffee habits",
  "pages": [{
    "id": "habits_page",
    "title": "Your coffee",
    "showIf": "coffee == 1",
    "questions": [
      {"id": "cups", "type": "integer", "label": "How many cups do you drink on a typical day?",
       "properties": {"min": 0}},
      {"id": "last_cup", "type": "single", "label": "When do you usually have your last cup?",
       "choices": ["Morning", "Afternoon", "Evening"]}
    ]
  }]
}}
```

**4. Sleep, for everyone.** A matrix: two rows share three columns.

```json
{"tool": "add_block", "arguments": {
  "survey_id": "$SURVEY",
  "block_id": "sleep",
  "title": "Sleep",
  "pages": [{
    "id": "sleep_page",
    "questions": [
      {"id": "sleep_quality", "type": "matrix", "label": "Over the past month, how would you rate…",
       "required": true,
       "rows": [{"id": "falling", "label": "Falling asleep"}, {"id": "staying", "label": "Staying asleep"}],
       "choices": ["Poor", "Fair", "Good"]}
    ]
  }]
}}
```

**5. Small edits.** Another option, a sanity constraint with its message, and the welcome
note on the first page.

```json
{"tool": "add_choice", "arguments": {"survey_id": "$SURVEY", "owner": "last_cup", "label": "Night"}}
```

```json
{"tool": "set_condition", "arguments": {"survey_id": "$SURVEY", "target": "cups",
  "field": "constraint", "condition": "cups <= 20"}}
```

```json
{"tool": "set_property", "arguments": {"survey_id": "$SURVEY", "target": "cups",
  "property": "constraintMessage", "value": "Please check the number of cups."}}
```

```json
{"tool": "set_property", "arguments": {"survey_id": "$SURVEY", "target": "intro",
  "property": "label", "value": "Thank you for taking part. This takes about three minutes."}}
```

**6. Retention and consent.** Two ops in one transaction through `apply_ops`: a retention
policy (required before publishing) and the consent page.

```json
{"tool": "apply_ops", "arguments": {"survey_id": "$SURVEY", "ops": [
  {"op": "set_property", "params": {"target": "/settings", "property": "retention",
   "value": {"kind": "days-after-close", "days": 90}}},
  {"op": "set_consent", "params": {"consent": {
   "text": "This study asks about your coffee and sleep habits. Taking part is voluntary and you can stop at any time. Answers are stored without your name.",
   "agreeLabel": "I agree to take part"}}}
]}}
```

**7. Check and hand over.** `validate` reports no errors and nothing left for the publish
checks; `preview` compiles the plan and returns the builder link.

```json
{"tool": "validate", "arguments": {"survey_id": "$SURVEY"}}
```

```json
{"tool": "preview", "arguments": {"survey_id": "$SURVEY"}}
```

The assistant's last message is the builder link. You open it, press **Preview** to walk
through the survey, adjust anything in the editor (or ask the assistant to; every change is
in **Undo**), and press **Publish** when you are satisfied. The assistant cannot.

## What the guardrails guarantee

- **Draft only.** The server dispatches eight app commands: create, list, get, apply ops,
  undo, redo, history and preview plan. A test proves against the command registry that none
  of them needs the publish, delete, export or response-deletion permission, and the tool
  names and descriptions never offer those actions.
- **Ops are validated.** Edits go through the same transaction path as the builder: each
  op's parameters are checked, then the whole survey, and a rejected transaction changes
  nothing. Warnings (a condition that refers to a later question, say) are saved and
  reported, so the assistant can fix them.
- **No participant data.** The drafting tools read drafts and the edit history only. There is
  no results, export or reproducibility tool, and the response tables are never touched.
- **Roles still apply.** Permissions come from the configured role as they do for every
  other client: a `viewer` can list and read but every edit is refused.

The tests behind these claims are in `python/osp-mcp/tests/` (`test_guardrails.py`,
`test_mcp_client.py`, which drives the server with a scripted MCP client over standard
input and output and replays the worked example above).
