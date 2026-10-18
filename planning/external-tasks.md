# External task step and Prolific integration (task EX2)

**Status:** built, 18 Oct 2026 (branch `agent/EX2`). Builds on EN1 (endings per outcome) and
EN2 (declarative end redirects), both on `main`. **Clean-room:** the integration points come
from the public documentation of Prolific (`researcher-help.prolific.com`), jsPsych
(`jspsych.org`), Gorilla (`gorilla.sc/support`) and PsychoJS/Pavlovia, read 18 Oct 2026. No
vendor source was opened.

## 1. What EX2 adds

A psychology study often hands the participant to a **task hosted elsewhere** (a jsPsych/PsychoJS
experiment on Pavlovia, a Gorilla task, the lab's own page) in the middle of the survey, then
takes them back to finish. EX2 gives this a declarative flow node, `externalTask`, that reuses
the EN2 redirect-template machinery for the outbound hop and resumes the survey on return.

Prolific itself needs nothing new: a Prolific completion code per ending is already EN1 + EN2,
a `settings.endings.<outcome>.redirect` to the Prolific template with a literal `cc` param and
`${prolific_pid}` piped from an embedded variable. EX2 only adds the mid-survey external-task
hop and documents the Prolific capture. See §5.

## 2. The `externalTask` flow node

```jsonc
{
  "type": "externalTask",
  "id": "et1",
  "template": "jspsych",                 // a settings.redirectTemplates (or hooks.redirects) key
  "params": { "pid": "${prolific_pid}", "sid": "${$session.id}" },
  "returns": ["reaction_time", "task_ok"] // embedded variables filled from the return URL
}
```

- **`template`** names a redirect template (the same shape and rules as EN2: an https URL with
  `{name}` placeholders only after the origin, each value pattern-checked and
  `encodeURIComponent`-encoded, the origin re-checked before navigating). This is the external
  task's URL.
- **`params`** fills the template's placeholders: a literal, or a piped `${…}` value (a question,
  a variable, or a built-in, including `${$session.id}`). A param that pipes an **answer** is a
  data export, exactly as for an end redirect (`external.param_question`, audited).
- **`returns`** lists **embedded variables** (declared with `source: "url"`). On return the
  platform reads each variable's `param` from the return URL and stores it, exactly as a URL
  parameter is captured at session start (semantics §1: recorded with a value and a state,
  **never trusted**). Values the external task puts in the return URL are participant-visible and
  so are treated as untrusted input, like any URL parameter; the authoritative task data lives on
  the task platform.

The platform appends two **reserved query parameters** to the outbound URL, which the external
task must echo back to send the participant home:

| Param | Meaning |
|---|---|
| `osp_return` | the absolute URL to send the participant back to (the survey, same device) |
| `osp_token` | a signed, expiring, context-bound **return token** (below) |

A template placeholder may not be named `osp_return` or `osp_token` (`external.reserved_param`).

## 3. The return token (signed, expiring, context-bound)

When the participant reaches an `externalTask` node, the participant app asks the server to mint
a return token (`POST /api/sessions/{id}/external/{node}/handoff`, authenticated by the session's
resume token). The token is

```
base64url(payload) + "." + hex(HMAC_SHA256(server_secret, base64url(payload)))
payload = {"v": 1, "sid": <session id>, "node": <node id>, "exp": <unix seconds>}
```

- **Tamper**: any change to the payload (a different session, node, or a later expiry) breaks the
  HMAC, so the server rejects it (`external.token_invalid`).
- **Expiry**: `exp` is `now + OSP_EXTERNAL_TOKEN_TTL` (default 6 h). A token past `exp` is rejected
  (`external.token_expired`). The window bounds how long a task may take.
- **Context-bound**: the token carries the session and node, and the server checks both against
  the call, so a token minted for one session or node is useless for another (cross-context
  replay is a tamper, rejected).
- **Replay (same context)**: the return (`POST …/external/{node}/return`) only *authorises* the
  resume; it stores nothing itself. The engine records the node as resolved and reuses that
  result on every later pass (idempotent per session and node, exactly as a quota check). A second
  return with the same token therefore changes nothing: the first return's values stand. The
  return call also needs the session's secret resume token, so a leaked return token alone cannot
  be replayed.

The server secret is `OSP_EXTERNAL_TOKEN_KEY` (32+ bytes). In dev, if unset, the service derives a
per-process secret; a token then does not survive a restart or a second worker, which is fine for a
single dev process and refused for production by `osp-api serve` (it requires the key, like the
store keys).

## 4. Flow, engine and resume

The engine treats `externalTask` like `quotaCheck`: reaching it with no recorded result emits an
`external` **effect** (the filled outbound URL, the reserved-param names, the return variables) and
pauses; the recorded result is reused on back, refresh and replay, so the task runs once.

1. The app sees the pending external effect, asks the server for a return token, appends
   `osp_return` (this survey's URL on this origin) and `osp_token`, and navigates
   (`location.assign`) to the task. `Referrer-Policy: no-referrer` stays, so the task never sees
   the survey URL beyond what we pass.
2. The participant does the task. The task sends them back to `osp_return` with `osp_token` and any
   return values as query parameters.
3. The app boots, restores the paused session from its local copy (or the server copy in
   `every-page`), sees `osp_token`, and calls the return endpoint to verify it. On success it
   resolves the external effect with the whitelisted return values, which merge into the session's
   URL parameters (so the declared embedded variables capture them), and the flow continues.

A participant who returns on a **different device** needs the resume link, as for any resume; the
external task alone cannot carry the survey's session. A return whose outbound URL could not be
built (a rejected param, e.g. a missing piped value) is **skipped** with an
`external.param_rejected` diagnostic rather than stranding the participant (lead decision E-1,
below).

## 5. Prolific capture (PROLIFIC_PID / STUDY_ID / SESSION_ID)

Prolific appends `PROLIFIC_PID`, `STUDY_ID` and `SESSION_ID` to the study URL. They are captured
with ordinary **embedded variables** (`source: "url"`), already in osp-survey/0.1:

```jsonc
"variables": [
  { "id": "prolific_pid", "kind": "embedded", "source": "url", "param": "PROLIFIC_PID" },
  { "id": "study_id",     "kind": "embedded", "source": "url", "param": "STUDY_ID" },
  { "id": "prolific_session", "kind": "embedded", "source": "url", "param": "SESSION_ID" }
]
```

They then pipe into an end redirect's completion code (`cc`) per ending, into an `externalTask`
param, or into the data. A Prolific completion URL per outcome (complete vs screen-out) is an
EN1/EN2 ending redirect; EX2 adds no new mechanism for it, only this documentation and the worked
fixture.

## 6. Decisions for the lead

- **E-1 (as built):** an `externalTask` whose outbound URL cannot be built (a rejected or missing
  piped param) is skipped with a diagnostic, so the participant is never stranded. Alternative: end
  the session with a dedicated outcome. Recommended: skip, because a missing optional id should not
  lose the participant; a required id that is missing is a recruitment-link problem the researcher
  sees in the data.
- **E-2 (as built):** returned values are captured like URL parameters (recorded, not trusted),
  because the return URL is participant-visible. A lab that needs trustworthy task data reads it
  from the task platform and joins on `prolific_pid` / `${$session.id}`. Cryptographically signed
  return values (the task signs its payload with a shared key) are a possible later addition.
- **E-3 (as built):** the return token is stateless (HMAC + expiry + context binding); same-context
  replay is prevented by the engine's per-node idempotency, not a server-side consumed-token store.
  A consumed-nonce store (as the host-identity nonces) could be added if a stronger single-use
  guarantee is wanted independent of the engine.
