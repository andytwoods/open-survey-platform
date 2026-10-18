# End-of-survey options (task EX1)

**Status:** plan, 17 Oct 2026 · **Research only.** Nothing here is built; §6 lists the build tasks.
**Clean-room:** the comparison in §2 comes from the public documentation of SurveyJS (surveyjs.io), Qualtrics (qualtrics.com/support) and LimeSurvey (manual.limesurvey.org), read on 17 Oct 2026. No source code of any of them was opened, and nothing in §4 copies their design: our model is an extension of the `end` node and `settings` we already have.

## 1. What we have today

Facts from the code on `main` (17 Oct 2026); `file:line` for the next agent.

| Area | Today |
|---|---|
| Ending | A flow `end` node has `outcome` (an identifier, default `complete`) and one optional translatable `message` (`python/osp-spec/src/osp_spec/model.py:420-424`). Reaching the end of the flow without an `end` node is `end: complete` (`semantics.md` §6). A quota's `onFull` shows at most one block, then ends with its own `outcome` (`model.py:364-369`). A consent decline ends with `declineOutcome` (default `declined`) and records no response (§11). A flow-critical hook failure ends with `hook-failed` (`runtime-design.md` §7a) |
| What the participant sees | One fixed screen for every outcome: `<h1>Thank you</h1>`, the end message as **plain text** (the engine's strong/em/lang segments are flattened by `plain()`), the fixed line "Your answers have been sent.", an optional "Taking you back…" link, and the Withdraw button (`web/runtime/src/App.svelte:339-350`). A screened-out or quota-full participant sees exactly the same screen as a completer. Decline has its own screen (`consent-messages.ts`) |
| Submit | The screen shows only after the server acknowledges the submit; a declined session finishes without submitting; 401/410 shows "This session has expired, so your answers could not be submitted." (`web/runtime/src/lib/session.ts:779-879`). Resuming a submitted session goes straight to the thank-you screen |
| Redirect | Only researcher **hook code** can redirect: `setEndRedirect(templateId, params)` picks one of the https templates declared in `hooks.redirects` (`HookRedirect`, `osp_spec/hooks.py:83-88`); placeholders only after the origin, each value pattern-checked (default `[A-Za-z0-9_-]{1,64}`) and `encodeURIComponent`-encoded (`hooks.py:225-247`, `web/hooks-sandbox/src/manifest.ts`). The app calls `location.assign(url)` **1.5 s** after the thank-you screen appears, never in the builder preview (`App.svelte:273-283`). No delay setting, no countdown, no "link only" mode. Redirects are "data exports": owner-only, audited, re-confirmed on code change (`runtime-design.md` §7a). The participant page sends `Referrer-Policy: no-referrer` (`web/runtime/index.html:6`), so the target never sees our URL |
| Closing | `closed_at` exists on surveys and publications, session start refuses a closed publication with 410 `survey.closed` ("This survey is closed.", `osp_runtime/session.py:414`), exports have `_after_close`, and retention can be `days-after-close`. But **no API route or builder control closes a survey** (`osp_store.close_survey` is called only by tests). No open/close dates, no paused state, no custom closed message, no response limit other than a quota |
| Outcome in the data | The outcome travels inside the encrypted response record (`_end` in exports, `results.status: complete\|all` filter). It is **not a column** on `responses`, so "how many were screened out" needs a decrypt-and-count. Nothing on the server checks the outcome at submit; a session that passed a `quotaCheck` and then ended with a non-complete outcome keeps its quota place (to verify against `semantics.md` §6 "used up on completion") |
| Builder | The End card edits Outcome and Message (`web/builder/src/lib/flow/NodeCard.svelte:230-242`). There is **no quota editor** (only `when` via `set_condition`), no redirect UI (templates are edited in the JSON view), no close button, no availability settings |
| Exports | XLSForm: `outcome` → `osp_outcome` calculate, `message` → a note group; quotas dropped. LSS: no early termination (every response counts as complete, `approximated`), outcome → `ospoutcome`, message → an X question, quota `onFull` → LimeSurvey action "terminate" with the block text or a default message, `surveyls_endtext` empty, `autoredirect: N`. Hooks and redirects `unsupported` in both |
| Fixtures | `11-end-nodes` (ineligible / early_exit / complete), `12-implicit-end`, `20-worked-example` (declined, quota_full), `24-quota-pending-retry`. None sets an end `message` or a redirect |
| Docs | `docs/logic.md` ("a 'screened out' outcome is simply an End node with that name"), `docs/publishing.md` (withdraw from the end screen, `_end` / `_late` / `_after_close`). The thank-you screen and redirects are not described |

So the engine already knows *which* ending was reached and the hooks path already has a safe redirect model. What is missing is everything a researcher would expect to set **without writing code**, and anything that makes one ending look different from another.

## 2. What the three platforms offer

Setting names are as the vendors' documentation prints them. "–" means the documentation has no such feature. Documentation URLs are in §2.1.

| Feature | SurveyJS (Form Library + Creator) | Qualtrics | LimeSurvey | Us today |
|---|---|---|---|---|
| Completion message | `completedHtml` (HTML); `showCompletePage` toggles the page | **Default message** ("We thank you for your time spent taking this survey. Your response has been recorded.") or **Custom** from the message library; must match the survey's base language | **End message** per language; HTML editor if enabled globally; not shown when the end URL auto-loads | Fixed "Thank you / Your answers have been sent."; optional plain-text message |
| Per-branch endings | `completedHtmlOnCondition`: list of `{expression, html}`, first match else `completedHtml` | Several **End of Survey** elements in the Survey Flow, each after a Branch, with **Override Survey Options** (message, redirect, flags) | One end message; branch-specific text only through expressions inside it (`{if(...)}`), or per-quota messages | One `message` per `end` node; same screen for all |
| Redirect | `navigateToUrl`, `navigateToUrlOnCondition` (`{expression, url}`); `onNavigateToUrl` can cancel; fires after `onComplete` | **Redirect to URL** (default ending or per element; not on free accounts); only one of message / summary / redirect | **End URL** + **Automatically load URL when survey complete**; otherwise the URL is shown as a link with **URL description** | Hook-only; template declared at publish |
| Redirect delay | – | – (Prolific's guide suggests a final block saying "clicking Next returns you to Prolific") | – (only a **Navigation delay** for buttons) | 1.5 s hard-coded, no countdown |
| Piped values in the URL | Placeholders documented for HTML properties and expressions; URL substitution and encoding not documented | `${e://Field/NAME}` and `${q://QID…}` appended as query parameters; built-ins `ResponseID`, `Q_TerminateFlag`…; encoding via the piped-text modifier `?format=urlencode` | URL fields `{SAVEDID}`, `{TOKEN}`, `{SID}`, `{LANG}`, question codes, any expression, `{PASSTHRU:name}`; encoding not documented | Declared template params, pattern-checked and encoded |
| Show the answers | `showPreviewBeforeComplete` + `previewMode` (all / answered) **before** submit, with Edit buttons; PDF via the separate PDF Generator | **Include response summary** / **Show Response Summary** after submit (PDF download), optionally **before completing**; redirect and summary are exclusive | **Participants may print answers**; **Public statistics** link after completion | – |
| Screen-out | `complete` trigger (`expression`); which trigger fired is only visible in `onComplete` (`completeTrigger`), nothing stored | Branch → End of Survey → **Flag Response As** Screened-Out (`Q_TerminateFlag`), **Do NOT record survey response**, **Do not increment quota counts**, **Screen-out Response** tally (add-on); `Finished = 1` for screened-out too | No "end here" action: the documented pattern is a **quota with limit 0** on a hidden Equation question, or hiding every later question (then the response counts as complete) | An `end` node with any outcome; stored in the record as `_end` |
| Quota-full ending | – (no quotas) | **End current survey** with **Customize end of survey experience** (same options as an element); **Prevent all new survey sessions** with an **inactive survey message**; by default the terminated response still increments the quota | **Quota Action** Terminate / allow modifying last answers; **Quota Message**, **URL**, **Autoload URL**; response stored as incomplete, token marked `Q` | `onFull` block + outcome; same screen |
| Closing | – (`state` has no closed value; the host decides) | **Survey Availability** start/expiry, **Expired survey message**, **Inactive Survey Message** ("Sorry, this survey is not currently active."), **Automatic survey closure**; in-progress respondents may finish | **Start date/time**, **Expiry date/time**; expired and deactivated messages (fixed text) | 410 "This survey is closed." if `closed_at` is set; nothing sets it |
| Already completed | `completedBeforeHtml` + `cookieName` ("Limit to one response", cookie only) | **Prevent multiple submissions** (cookie), **Duplicate Detection** flags | **Set cookie to prevent repeated participation**; token surveys | Resume of a submitted session shows the thank-you screen (server-side, by session) |
| Incomplete responses | Host's job | **Incomplete survey responses**: record or delete after 1 h … 1 year | Saved as incomplete; **Save and resume later** | Stored; `late` flag; `_end` absent |

### 2.1 Sources

- SurveyJS: `https://surveyjs.io/form-library/documentation/api-reference/survey-data-model` (members `completedHtml`, `completedHtmlOnCondition`, `completedBeforeHtml`, `navigateToUrl`, `navigateToUrlOnCondition`, `onNavigateToUrl`, `showPreviewBeforeComplete`, `previewMode`, `onCompleting`, `onComplete`, `clearInvisibleValues`, `state`); `…/design-survey/create-a-multi-page-survey#complete-page`; `…/design-survey/conditional-logic#dynamic-texts` and `#conditional-survey-logic-triggers`; `https://surveyjs.io/survey-creator/documentation/end-user-guide/how-to-create-custom-thank-you-page`; `https://surveyjs.io/documentation/backend-integration`. The markdown demo says the library's "basic sanitizing capabilities … do not guarantee 100% protection" and recommends a dedicated sanitiser.
- Qualtrics: `https://www.qualtrics.com/support/survey-platform/survey-module/survey-options/survey-termination/`; `…/survey-flow/standard-elements/end-of-survey-element/`; `…/survey-flow/advanced-elements/screen-out-management/`; `…/survey-tools/quotas/`; `…/survey-flow/standard-elements/passing-information-through-query-strings/`; `…/survey-options/survey-experience/`; `…/survey-options/partial-completion/`; `…/survey-options/survey-protection/`; `…/data-and-analysis-module/data/download-data/understanding-your-dataset/`; Prolific's guide `https://researcher-help.prolific.com/en/articles/445194-qualtrics-integration-guide`.
- LimeSurvey: `https://manual.limesurvey.org/Text_elements`; `…/Presentation`; `…/URL_fields`; `…/Panel_integration`; `…/Survey_quotas`; `…/Setting_conditions`; `…/Publication_%26_access`; `…/Closing_a_survey`; `…/Participant_settings`; `…/Global_settings` ("Filter HTML for XSS" on by default); forum thread 159209 (screen-out via a zero quota on a hidden Equation question).

### 2.2 What to take from each, and what not

- **Qualtrics** has the richest ending model: a default ending plus per-branch endings that override it, flags that name the ending in the data, and quota endings reusing the same options. Its weak spots are a cookie for duplicates and the warning that quotas are counted at submit, so they can be exceeded; our server-held quota places already avoid that.
- **SurveyJS** keeps the ending client-side and conditional (`completedHtmlOnCondition`), stores nothing about which ending fired, and has no closed state or quota. Its "preview before complete with Edit buttons" is the best answer-review UX of the three.
- **LimeSurvey** has one ending and makes screen-outs a quota trick. Its **URL description** (show the redirect as a link when it does not auto-load) and the per-quota message/URL are worth keeping in mind.
- **None of the three** offers a redirect delay, an accessible countdown, or any protection against a URL that leaks answers to a third party: Qualtrics and LimeSurvey let the researcher type a free-form URL with piped answers in it. We already refuse that (declared templates, origin fixed, values encoded) and should keep refusing it.

## 3. Gaps

Ordered by how often a psychology study needs them.

1. **Screened-out and quota-full participants see "Your answers have been sent."** The screen is the same for every outcome, so a researcher cannot say "you are not eligible" or "this group is full" with the right tone, and cannot give a different Prolific code. The per-node `message` helps, but it is plain text under a fixed heading.
2. **No redirect without code.** Returning a participant to Prolific, SONA, MTurk or the lab's own page needs a hook script. Every other platform does it with a URL field.
3. **No control over the redirect's timing**, no countdown, no "link only" mode, and the 1.5 s auto-redirect cannot be read by a screen reader before it fires (WCAG 2.2.1 Timing Adjustable, 3.2.5 Change on Request).
4. **Closing is unreachable.** The store and runtime support a closed survey, but there is no button, no route, no schedule and no custom message.
5. **No "see your answers"** for participants (receipt, print), which ethics committees sometimes ask for in diary or debrief studies.
6. **Rich text is lost on the end screen** (strong / em / lang segments flattened), though pages render them.
7. **Outcome is not a column**, so per-ending counts (completed / screened out / quota full / declined) are not cheap and the results page cannot show them without reading records.
8. **No quota editor in the builder**, so the only screen-out route that frees a place (quota-full) cannot be authored without the JSON view.
9. **Quota place after a non-complete ending**: the server counts a place used at the check; semantics says it is used on completion. A screened-out participant who passed the check may hold the place for 24 h. Needs a test and, if confirmed, a fix.

## 4. Recommended set

Principles: declarative (no code for the common cases), the engine stays the only place that decides flow, every ending is keyed by its **outcome** so the data, the screen, the redirect and the exports agree, and redirect safety stays as strict as the hooks path.

### 4.1 Model: endings keyed by outcome

A survey-level map `settings.endings` gives each outcome its screen. End nodes, quota `onFull`, consent `declineOutcome` and the built-in `hook-failed` all end with an outcome; the ending for that outcome is what the participant sees. End nodes keep their optional `message`, shown as an extra paragraph on top of the ending's body (today's behaviour, so existing surveys don't change).

```yaml
settings:
  endings:
    complete:                       # the default ending; always present (defaults if omitted)
      title: { en: "Thank you" }
      body: { en: "Your completion code is **C1AB2**. You can also return automatically below." }
      redirect: { template: prolific, params: { cc: "C1AB2" }, delay: 5, mode: auto }
    screened_out:
      title: { en: "Thank you for your interest" }
      body: { en: "This study needs participants aged 18 or over, so it ends here." }
      redirect: { template: prolific, params: { cc: "SCREENED" }, delay: 0 }
    quota_full:
      body: { en: "The group you belong to is already complete. Nothing more is needed from you." }
  redirectTemplates:                # moved out of `hooks.redirects`; hooks keep using them
    prolific:
      url: "https://app.prolific.com/submissions/complete?cc={cc}"
      params: { cc: { pattern: "[A-Z0-9]{4,12}" } }
```

`Ending` fields:

| Field | Type | Semantics |
|---|---|---|
| `title` | `Text \| None` | Heading. Default: the app's own translated "Thank you" |
| `body` | `Text \| None` | Rich text (the same inline markup pages already render: strong, em, lang; plus paragraphs). Piping as in §8 of semantics: `${q}`, variables, built-ins; piped values HTML-escaped; unanswered → empty string. **No HTML**: the renderer keeps using text nodes, never `{@html}` |
| `status` | `"auto" \| "none"` | The app's own truthful line under the body. `auto` (default): "Your answers have been sent." when a response was recorded, "Nothing was recorded." for `declined`. Researcher text can never replace it, so a participant is never told data was kept or discarded wrongly |
| `redirect` | `EndRedirect \| None` | §4.2 |
| `summary` | `"none" \| "answers"` | §4.4. Default `none` |

Rules:

- Outcomes used anywhere (end nodes, `onFull.outcome`, `declineOutcome`, the built-ins `complete` and `hook-failed`) may have an ending; an ending for an outcome nothing reaches is a validation **warning** (`ending.unreachable`); an outcome with no ending uses the defaults (`complete` defaults as today). No new ending kinds: the outcome identifier is the key, as the data already uses it.
- `declined` may have a `body` and a `redirect` but never `summary: answers` (nothing was recorded) and its `status` is always the "nothing recorded" line.
- Withdraw stays on every ending that recorded a response (semantics §11). It is not an option.
- The end node's `message` is rendered with the same rich-text renderer, above the body.
- Exports: XLSForm emits the `complete` ending's body as the final note group; LSS maps `complete.body` → `surveyls_endtext`, the `quota_full`-class ending → quota message, a redirect with literal-only params → `surveyls_url` + `autoredirect` (piped params `loss`); per-outcome bodies beyond those two are `approximated` (only one end text exists there). The capability tables get rows for every new field (golden rule 6). XP1's SurveyJS target maps endings to `completedHtmlOnCondition` on `osp_outcome` and redirects to `navigateToUrlOnCondition`; QSF to one End of Survey element per outcome.

### 4.2 Redirects without code

`EndRedirect`:

| Field | Type | Semantics |
|---|---|---|
| `template` | name | A key of `settings.redirectTemplates` (the existing `HookRedirect` shape and checks: https, no placeholder in the origin, one path, pattern per param). `hooks.redirects` becomes an alias of the same map so R11 surveys keep working |
| `params` | `{name: string}` | One entry per placeholder. A literal, or a piped `${…}` reference to a question, variable or built-in. The **filled** value must match the param's pattern (default `[A-Za-z0-9_-]{1,64}`), else the redirect is not followed and not shown, and a `redirect.param_rejected` paradata entry is written. Values are `encodeURIComponent`-encoded; they can never alter the origin or path because placeholders are only allowed after the origin |
| `delay` | integer seconds, 0 … 60 | Default **5**. `0` means navigate as soon as the submit is acknowledged, with no screen in between (the builder warns that the body will not be seen) |
| `mode` | `"auto" \| "link"` | `auto` (default): countdown then `location.assign`. `link`: no automatic navigation, the button is shown and the participant clicks |
| `label` | `Text \| None` | The button text. Default: the app's own "Continue to {host}" with the template's host name, so the participant knows where they are going |

Semantics and safety:

- A redirect fires only after the server acknowledged the submit (or the decline), exactly once, never in the builder preview (the debugger shows the resolved URL instead), and never when a param is rejected.
- **New built-ins for piping**, read-only, available only in endings and hooks: `${$response.id}` (the pseudonymous response id, as Qualtrics' `ResponseID`), `${$session.id}`, `${$outcome}`. URL parameters are already available as `embedded` variables (`EmbeddedVariable.source: url`), so `PROLIFIC_PID` is `${prolific_pid}` once declared. No built-in exposes the resume token.
- **Piped answers in a redirect are a data export**, exactly as hooks treat them: owner-only to add or change, listed in the codebook ("values sent to app.prolific.com: cc"), named in the consent-text template, audited. A param that pipes a *question* (not a variable or built-in) additionally shows a builder warning, because it sends an answer to a third party.
- The template origin is fixed at publish; the participant app re-checks the filled URL against the template before navigating (as the hooks sandbox does now). `Referrer-Policy: no-referrer` stays. The thank-you screen is served with the same CSP as today; the redirect is a top-level navigation, no iframe.
- Accessibility of the delay: the ending's heading takes focus as every page does; the body, the status line and the button are rendered **before** the countdown starts; one polite live-region announcement ("You will be taken to app.prolific.com in 5 seconds. Use the button to go now, or 'Stay on this page' to cancel."); the visible countdown text is `aria-hidden` so it is not read every second; a **Stay on this page** button cancels (3.2.5). With `prefers-reduced-motion` the countdown is a number, not an animation. Any key or click on the page does *not* pause the countdown (that would be surprising); only Stay cancels. After cancelling, the button stays as a plain link.
- A delay of `0` is allowed because panel providers want it, but the builder shows the WCAG note and the alternative `link` mode.

### 4.3 Closing, availability and limits

Server-side state the researcher controls, not part of the survey version (so a close is not a new version):

| Setting | Where | Semantics |
|---|---|---|
| Close / reopen | `POST /api/surveys/{id}/close`, `…/reopen`; builder Publish dialog button; audited | Sets / clears `closed_at` on the publication. New sessions get 410 `survey.closed`. **In-progress sessions may finish** (as Qualtrics' default; we already flag their submits `_after_close`) until their resume expiry; a `closeMode: "finish" \| "immediate"` on the close call lets the researcher cut them off (their next save gets 410 and the app shows the closed message) |
| Schedule | `settings.availability: { opensAt?, closesAt? }` (ISO instants, server clock) | Before `opensAt`: session start is refused with `survey.not_open` (as 410 `survey.closed` today) and the app shows the "not yet open" message; no session is created. At `closesAt`: the server closes exactly as the button would (a job, same as retention) |
| Messages | `settings.closedMessage`, `settings.notOpenMessage` (`Text`, rich text, **no piping**: there is no session) | Shown instead of the start; defaults are the app's own strings |
| Response limit | `settings.responseLimit: N` | Sugar for a survey-wide quota: `when: true`, `limit: N`, `onFull.outcome: quota_full`, checked at session start (not a flow node), so the participant is refused before answering, with the `quota_full` ending's body as the message. Counts completed responses only (semantics §6) |
| Paused | not proposed | Close + reopen covers it; a third state adds little and the export flag `_after_close` would need a twin |

### 4.4 Showing the answers

`summary: answers` renders, after the submit acknowledgement, the participant's own answers below the body: every answered question in path order, with display labels, as a definition list, plus a Print button (print stylesheet, no PDF library; the browser prints to PDF). Never in `declined`. The summary comes from the engine's view (the same values the record holds), is never fetched back from the server, and is not shown when the page is a resume of an already-submitted session in `end-only` + `memory` mode (nothing is left to show). Privacy note in the builder: on a shared device the answers stay on screen; the Withdraw button is next to them. A pre-submit review with Edit buttons (SurveyJS style) is a flow feature, not an ending, and is out of scope here.

*Built (EN5, 18 Oct 2026):* as above, with one rule made stricter: the list is shown only on the page whose **own** submit the server acknowledged (the same gate as the redirect), so any resume of a submitted session, in either save mode, shows the ending without it (whether the ended snapshot reached the server before the submit is a race, so showing it there would be hit and miss), and it goes once the response is withdrawn.

### 4.5 Data

- `responses.outcome` becomes a plain column (migration), written at submit from the record's `end.outcome`, indexed with `survey_version_id`. The results page then shows "N complete · N screened out · N quota full" at no decrypt cost, and the `status` filter can use it. The record stays the source of truth; a mismatch is a `verified: false` difference.
- `declined` stays uncounted except the anonymous counter (semantics C-2).
- A quota place taken at a `quotaCheck` is **released at submit when the outcome is not `complete`** (making the code match semantics §6). Test first; the fix is in `osp_runtime.session` submit.

### 4.6 Builder

- The End card gets "Ending for outcome X: edit" that opens the ending editor (shared when several nodes use the same outcome). Survey settings → **Endings**: one card per outcome in use, title/body rich-text editor (the existing `TextEditor`), status, redirect (template picker, params with piping, delay, mode, label, a "Preview URL" with dummy values), summary toggle. Diagnostics inline (`ending.*`, `redirect.*`).
- Settings → **Availability**: close/reopen button with the finish/immediate choice, opens/closes schedule, messages, response limit.
- A **quota editor** (list, add, limit, `when`, `onFull` block + outcome) is needed so quota-full endings can be authored at all; today only the JSON view can.

## 5. Decisions for the lead

1. **Endings keyed by outcome** (shared by every node with that outcome) rather than per end node. Recommended: by outcome; the data already keys on it and EX2's completion codes are per outcome. Per-node text stays via `message`.
2. **Default delay 5 s with a countdown**, `0` allowed. Alternative: default `link` mode (no automatic navigation at all) and make `auto` opt-in. Recommended: 5 s auto, because panel providers expect automatic return and the screen is read before the timer ends.
3. **Piped questions in redirect params as a data export** needing the owner's confirmation (as hooks). Recommended: yes, same rule, one code path.
4. **In-progress sessions may finish after close** by default (`closeMode: finish`). Recommended: yes; `_after_close` already exists for it.
5. **Quota place release on non-complete outcomes** (§4.5) is a behaviour change for running surveys; confirm before fixing.

## 6. Follow-up build tasks

Proposed rows for `planning/tasks.md` (Wave H), in build order. Effort is a rough size for one agent.

| id | title | depends on | acceptance criteria | effort |
|---|---|---|---|---|
| EN1 | Endings per outcome: spec, engine view, participant screen | – | `settings.endings` (`Ending`: title, body rich text with piping, status, summary flag reserved) in `osp-spec` + JSON Schema; validator `ending.unreachable` (warning), `ending.declined_summary`, piping reference checks; op `set_ending` (inverse, fuzz); plan compiler passes endings into the plan (inside the checksum); engine `view.end` carries the resolved ending; participant app renders title/body (RichText, never `{@html}`), truthful status line per outcome, end-node `message` above the body; fixtures `11-end-nodes` and `20-worked-example` get endings + expected traces; capability rows for XLSForm (`complete` body → final note) and LSS (`surveyls_endtext`, quota message); builder End card → ending editor + Settings → Endings; docs `docs/logic.md` / `docs/settings.md`; `make check` + web-e2e | M |
| EN2 | Declarative end redirects with an accessible delay | EN1 | `settings.redirectTemplates` (the `HookRedirect` shape; `hooks.redirects` kept as an alias, one validator), `Ending.redirect` {template, params (literal or piped), delay 0–60 default 5, mode auto/link, label}; built-ins `$response.id`, `$session.id`, `$outcome`; filled values pattern-checked and `encodeURIComponent`-encoded, origin re-checked in the app, rejected param → no redirect + paradata; countdown UI: focus on heading, one polite announcement, `aria-hidden` ticker, Go now / Stay on this page, reduced-motion; piped-question params are owner-confirmed data exports listed in codebook and consent template, audited; never in preview (debugger shows the URL); security tests: origin change via param, scheme change, encoded `/`, `..`, overlong value, placeholder in origin refused at publish, replayed redirect after resume; LSS `surveyls_url`/`autoredirect` for literal-only params; builder redirect editor with URL preview; docs | M |
| EN3 | Closing, availability and response limit | – | `POST /api/surveys/{id}/close` (`closeMode` finish/immediate) and `/reopen` (owner/editor, audited, `make contract`); in-progress sessions finish or get 410 by mode; `settings.availability` opens/closes instants applied by the server (job shared with retention) and `settings.closedMessage` / `notOpenMessage` (rich text, no piping) shown by the participant app; `settings.responseLimit` compiled to a start-time quota check with the `quota_full` ending; builder Publish dialog close/reopen + Settings → Availability; `_after_close` unchanged; tests across store/runtime/API/e2e; docs `docs/publishing.md` | M |
| EN4 | Outcome column and quota place release | EN1 | Migration adds `responses.outcome`, written at submit from the record, backfilled for existing rows by a one-off command; results route counts per outcome without decrypting (`status` filter uses the column); results page header "N complete · N screened out · …"; test that a session passing a `quotaCheck` and ending non-complete releases its place at submit, fix in `osp_runtime.session` if it fails (after the lead's decision 5); docs `docs/results.md` | S |
| EN5 | Show the answers after submit | EN1 | `Ending.summary: answers`: definition list of answered questions in path order with display labels from the engine view, Print button + print stylesheet, never for `declined`, not after a memory-only resume; builder toggle with the shared-device privacy note; axe + 320 px + print snapshot e2e; docs | S |
| EN6 | Quota editor in the builder | – | Settings → Quotas: list, add, rename, limit, `when` (condition editor), `onFull` block picker + outcome; ops `add_quota` / `set_quota` / `delete_quota` (own module, inverse, fuzz; `delete` refuses while a `quotaCheck` uses it unless `force`); Flow view's Quota check card links to it; e2e; docs `docs/logic.md` | S |

EX2 (external task step + Prolific) should depend on EN1 and EN2: with those, Prolific completion codes per ending are `settings.endings.<outcome>.redirect` with a literal `cc` param and `${prolific_pid}` from an embedded variable; EX2 then only adds the return step and the signed return token.

## Lead decisions (17 Oct 2026)

1. **Endings are keyed by outcome**, shared by every end node with that outcome; a node's own `message` still shows above the ending. Accepted as recommended.
2. **Redirects default to `auto` after 5 s with a visible countdown** (0 allowed; `link` mode available). Panel providers expect the automatic return; the countdown plus "Go now / Stay on this page" keeps it accessible.
3. **Piped answers in redirect parameters are a data export**: the owner confirms them, they are listed in the codebook and consent template, and audited, through the same code path as hooks.
4. **Closing defaults to `finish`**: participants already in progress may finish; `immediate` is opt-in.
5. **Quota places count completes only.** A session that passed a `quotaCheck` but ends with any non-complete outcome (screened out, quota full elsewhere, declined, withdrawn before submit) releases its place at submit. This fixes the behaviour for running surveys; recorded in `semantics.md` (quotas). A *submitted complete* response that is later withdrawn keeps its place (C-1, unchanged).

