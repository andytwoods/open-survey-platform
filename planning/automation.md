# Automation plan: building with parallel Claude agents (Claude Max 20x)

**Goal:** most of the work runs unattended. The human role shrinks to roughly **30–60 minutes a day**: answer "Needs human" questions, review batched PRs, and decide. Agents verify their own work through tests, fixtures and the LimeSurvey harness.

## 1. Principle: machines judge, humans decide

Agents may only call a task done when an **automatic** check says so. Every check below exists so the human isn't the tester.

| Check | Proves | Who runs it |
|---|---|---|
| `make check` (tests, layers, contract, lint) | Code is correct and in its layer | Agent, before every commit; CI on every push |
| Fixtures (`fixtures/*.json`) | Engine behaviour matches `semantics.md` | Same |
| Enketo harness (Playwright) | Real Enketo pages behave like our engine | Agent for touched fixtures; CI nightly runs all |
| Licence check | No GPL/AGPL/BSL dependencies | CI |
| Completeness guard | No spec field silently dropped by an exporter | CI |

**Gate:** `main` is protected. Merges need green CI plus human approval. Agents never push to `main`.

## 2. Work queue: `planning/tasks.md`

One table, the only place work is assigned:

```text
| id | title | layer | depends on | acceptance criteria | status | owner | needs human |
```

- Status flow: `todo → doing → review → done` (or `blocked`).
- Tasks are sized so one agent finishes in one session (≈ 1–4 hours of agent time).
- Acceptance criteria must be machine-checkable: named tests or fixtures that must pass.
- I (the lead session) write and order tasks, and split any that come back too big.

## 3. Topology

```text
                 you (decisions, PR review, ~30–60 min/day)
                          │
                 lead session (plans tasks, reviews diffs,
                 summarises for you, merges after approval)
          ┌──────────┬──────────┬──────────┬──────────┐
       agent:spec  agent:engine agent:lss  agent:web  agent:qa
       (worktree)  (worktree)   (worktree) (worktree) (worktree)
```

- **3–5 agents in parallel.** That's enough to use Max 20x without them colliding. Layering is what makes this safe: agents work in different packages, joined by contracts.
- Each agent gets one task, its own git worktree and branch. It runs `make check`, opens a PR, writes a devlog entry, and stops.
- The lead session reviews each PR diff against the task. It sends back failures with reasons and gives you a short batched summary: what landed, what needs you.

## 4. Claude Code mechanics

| Need | Mechanism |
|---|---|
| Parallel isolated agents | Subagents with worktree isolation, or separate `claude` sessions each in its own `git worktree` |
| Unattended runs | Headless `claude -p "<task prompt>"` per task, driven by a small runner script reading `tasks.md` |
| Repeat until the queue is empty | `/loop` in the lead session, or a scheduled routine overnight |
| Agent can't skip checks | A Claude Code **Stop hook** that runs `make check` and blocks finishing if it fails |
| Notify you | Push notification / summary when a batch is ready for review or a task is `blocked` |
| Context between sessions | `AGENTS.md`, `semantics.md`, `tasks.md`, `log/devlog.md`: agents read these, not chat history |

## 5. Daily rhythm

| When | What | You |
|---|---|---|
| Morning | Read the lead session's summary. Answer "Needs human". Approve or bounce PRs | 30–60 min |
| Day | 3–5 agents work the queue | none |
| Evening | Lead session refills the queue for the overnight run | 5 min |
| Overnight | Long tasks + full nightly harness | none |

## 6. Phases

| Phase | Agents | Exit gate |
|---|---|---|
| **0. Enketo spike** (`spike-enketo.md`) | 1 | FINDINGS.md says go / go-with-limits; `semantics.md` updated. **You decide go.** (Spike 1 on LimeSurvey was stopped early when Enketo was chosen.) |
| **1. Scaffold** | 1 | Both workspaces, layer checks, `make check`, CI, Stop hook, `tasks.md` seeded, `AGENTS.md` at root. Empty but green |
| **2. Core** | 3–4: `spec`, `engine` + fixtures, `targets/xlsform` + `runtime` (Enketo), `harness` | 20 fixtures pass in the engine *and* in Enketo |
| **3. Builder** | 3–5: `ops`, `api`, `web` (2), `qa` | MVP items 6–8 pass in CI; you build the pilot survey yourself in the builder |
| **4. MVP complete** | 2–4 | All `review.md` §4 items green; a researcher tries it |

## 7. Guardrails

- **Usage:** cap parallel agents at 8 (raised from 5 by the user, 16 Oct 2026). If limits are hit, the lead session pauses lowest-priority tasks first.
- **Runaway loops:** an agent that fails the same check 3 times stops and marks the task `blocked` with notes.
- **Scope:** agents only do their task. New ideas go in `tasks.md` as `todo` suggestions for you to accept.
- **Secrets and data:** no real credentials or participant data in agent environments. The harness uses local throwaway instances only.
- **Kill switch:** delete or rename `planning/tasks.md` → the runner stops picking up work.

## 8. What still needs you

- Approving the go/no-go after spike 1.
- Answering new open questions in `semantics.md` as they arise.
- Reviewing PRs (batched).
- Finding a pilot researcher and starting ethics/IT conversations early. Those set the real end date.
