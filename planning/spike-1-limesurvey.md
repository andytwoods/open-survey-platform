# Spike 1: drive LimeSurvey end to end from code

**Status:** plan, not started · **Time-box:** 3–5 days of agent time · **Runs:** unattended by one agent (see `automation.md`)
**Decides:** whether LimeSurvey can be the default runtime (`review.md` §2.5). If it fails, stop and rethink before any builder work.

## 1. Questions this spike must answer

Each gets a yes/no/partial answer plus evidence (log, screenshot, response row) in `spikes/spike-1/FINDINGS.md`.

| # | Question | Why it matters |
|---|---|---|
| Q1 | Can a `.lss` file be imported, activated and opened by participants purely through the RemoteControl 2 API? | Automated deploy (MVP item 4) |
| Q2 | Can responses be exported through the API with stable column names we can map back to our variable IDs? | Codebook, response pull (MVP item 11) |
| Q3 | Can we read the LimeSurvey version through the API? | Repro package records the runtime version |
| Q4 | Where is the realised question order stored, if anywhere? Is the per-response `seed` exported? | Whether we can *record* orders in native mode |
| Q5 | Can URL parameters prefill hidden questions (for `cond` and `seed` in `osp-redirect` mode)? Do they persist across refresh and back? | `osp-redirect` mode |
| Q6 | When an answered question becomes irrelevant (via back navigation and a changed answer), is its value kept, cleared on submit, or exported? | Defines `semantics.md` §3 |
| Q7 | Does random question order stay the same after refresh, back and re-entry with the same token? | Reproducibility claims |
| Q8 | Do relevance, required, and piping behave exactly as our planned semantics say for the test survey? | Whether our engine can be the oracle |
| Q9 | How long does a full harness run take (start containers → import → 5 participants → export)? | Whether agents can run it on every change |

## 2. Setup

- **LimeSurvey 6.x** (pin an exact image tag and record it) + MariaDB or PostgreSQL via `docker compose`. Candidate image: the community `martialblog/limesurvey` image **[A — confirm it is maintained and has a 6.x tag]**.
- RemoteControl 2 (JSON-RPC) enabled through config or a seeded settings row, so no manual admin clicks are needed.
- Python 3.14 + `httpx` for JSON-RPC, **Playwright (Python)** for scripted participants. All in `spikes/spike-1/`.
- One command runs everything: `make spike1` (or `uv run python -m spike1`). It must work from a clean checkout with Docker installed.
- **No real personal data.** Fake participants only.

## 3. Test survey (hand-written `.lss`)

A cut-down version of the `review.md` §2.3 example:

1. Consent (yes/no). "No" → end.
2. Age (integer, 18–120, required).
3. Hidden `cond` and `seed` questions (prefilled from URL in redirect mode).
4. Condition assignment: **native mode** uses LimeSurvey randomisation between two groups; **redirect mode** uses `cond` from the URL.
5. Stimulus group A or B, shown by condition.
6. Attitudes group: 3 Likert items, **random order**. Item 1 pipes in the condition text.
7. A follow-up question shown only if att1 ≥ 4, required when shown.
8. End.

## 4. Scripted participants (Playwright)

| Script | Path | Checks |
|---|---|---|
| P1 | Consent no | Ends immediately; no other answers stored |
| P2 | Native mode, straight through, att1 = 5 | Follow-up shown and required; condition recorded; order recorded? (Q4) |
| P3 | Native mode, att1 = 2 | Follow-up not shown, not required |
| P4 | Redirect mode `?cond=B&seed=123` | Prefill works (Q5); stimulus B shown |
| P5 | att1 = 5, answer follow-up, go **back**, change att1 to 2, submit | Q6: what happens to the follow-up value |
| P6 | Refresh mid-page and resume with token | Q7: same order, same condition |
| P7 | Re-enter the survey link after finishing | No reallocation; correct LimeSurvey behaviour |

Each script writes the page sequence it saw to JSON. After all scripts, export responses via the API and save them raw.

## 5. Deliverables

1. `spikes/spike-1/` with `docker-compose.yml`, `.lss`, scripts and one-command runner.
2. `spikes/spike-1/FINDINGS.md`: Q1–Q9 answered with evidence.
3. Updates to `planning/semantics.md`: every "verify in spike 1" item marked confirmed or changed.
4. An initial **LimeSurvey capability table** draft (feature → native / lowered / approximated / unsupported).
5. Timings (Q9) and a recommendation: **go / go-with-limits / no-go** for LimeSurvey as default runtime.

## 6. Pass / fail

- **Go:** Q1, Q2, Q8 yes; Q5 yes or a workable alternative; Q6 and Q7 behaviour known and documentable; Q9 under ~5 minutes.
- **Go with limits:** Q4 no (we record only condition, not order, in native mode). That is acceptable if documented.
- **No-go:** deploy can't be automated (Q1), responses can't be mapped back (Q2), or behaviour is inconsistent between runs (Q7/Q8). Then evaluate alternatives (manual `.lss` import only, or another runtime) before any builder work.

## 7. Rules for the agent running this

- Clean-room: read LimeSurvey's docs and observe behaviour. Don't copy LimeSurvey (GPL) code into our repo.
- Spike code is throwaway. It goes in `spikes/`, never imported by product code.
- Stop and write the question into `FINDINGS.md` under "Needs human" rather than guessing, if a result needs a product decision.
- Commit after each answered question, with the evidence file, so an interrupted run can resume.
