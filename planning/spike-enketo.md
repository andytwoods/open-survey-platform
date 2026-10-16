# Spike: Enketo as the participant runtime

**Status:** plan · **Time-box:** 1–2 days of agent time · **Runs:** unattended by one agent
**Decides:** how we embed Enketo, and which features need workarounds. Replaces spike 1 (LimeSurvey) as the gate before the builder.

## 1. Questions

Answer each in `spikes/spike-enketo/FINDINGS.md` with evidence.

| # | Question | Why |
|---|---|---|
| E1 | Can `enketo-core` render a form on a plain page we serve, **without** Enketo Express, KoboToolbox or ODK Central? Bundle size? | One backend, ours |
| E2 | Where does XForm → HTML transformation run: `enketo-transformer` in Node at publish time, or in the browser? | Whether our Python server needs a Node step |
| E3 | Can we get the submitted instance (XML) on submit and POST it to our own endpoint? | Response storage |
| E4 | Can our server inject `cond` and `seed` into the form instance before render (preload/default values)? | Condition assignment without a redirect |
| E5 | `randomize(nodeset, seed)`: does our Python reimplementation (Fisher–Yates inside-out + Park–Miller, per the ODK XForms spec) produce **identical** orders to Enketo for 1,000 seeds? | Replayable randomisation |
| E6 | Can **question order** within a page, and **block order**, be randomised? XForms `randomize` is defined for itemsets (choices); find a workaround or confirm unsupported | Experimental designs |
| E7 | Pages: does a `field-list` group per page plus the `pages` theme give one-page-at-a-time navigation with back? | Survey feel |
| E8 | When an answered question becomes irrelevant, is its value removed from the submitted instance? (ODK says non-relevant nodes are excluded on submit **[verify]**) | `semantics.md` §3 |
| E9 | Do relevance, required, constraints and piping match `semantics.md` for the test survey? | Our engine as the oracle |
| E10 | Accessibility quick check: keyboard-only completion, labels exposed to screen readers (axe-core scan) | WCAG before pilot |
| E11 | Licences of every package pulled in by `enketo-core` (licence checker). Any GPL/AGPL? | MIT project |

## 2. Setup

- Node 24 (installed) for Enketo packages. Python 3.14 + uv for our side. Playwright (Python) for participants. **No Docker needed.**
- Source: the `enketo/enketo` monorepo (`packages/enketo-core`, `enketo-transformer`, `openrosa-xpath-evaluator`). Pin an exact commit or npm version.
- Test survey: the spike 1 survey (consent, age, condition, stimulus A/B, 3 Likert items with random order, conditional required follow-up) written as **XLSForm**, converted with `pyxform`.
- A minimal Python server (stdlib or FastAPI) that serves the page, injects `cond`/`seed`, and receives submissions as files.
- One command reruns everything: `make -C spikes/spike-enketo run`.

## 3. Scripted participants

Same 7 scripts as spike 1 (`spike-1-limesurvey.md` §4), adapted. P4 becomes "server injects `cond=B`, `seed=123`". Add **P8**: run 1,000 seeds through Enketo's `randomize` in a headless browser and compare with our Python implementation (E5).

## 4. Deliverables

1. `spikes/spike-enketo/` with the XLSForm, server, scripts and one-command runner.
2. `FINDINGS.md`: E1–E11 answered, plus **go / go-with-limits / no-go**.
3. Draft **Enketo capability table** (feature → native / lowered / approximated / unsupported).
4. A proposed embed architecture (1 page): where the transform runs, how a session starts, how responses are stored.

## 5. Pass / fail

- **Go:** E1, E3, E4, E5, E9 yes. E2 has a workable answer. E11 has no copyleft.
- **Go with limits:** E6 not possible. Block/question order randomisation is then deferred or lowered, and documented.
- **No-go:** can't run standalone (E1), can't capture submissions (E3), or `randomize` can't be reproduced (E5).

## 6. Rules

Same as `spike-1-limesurvey.md` §7. Apache-2.0 code may be used as a dependency, but don't copy Enketo source into our repo. Throwaway code stays in `spikes/`. No git commits unless the user approves.
