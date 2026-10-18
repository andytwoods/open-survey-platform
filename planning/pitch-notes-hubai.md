# Pitch notes: HubAI (glance, don't read)

## The event
- "Reinvent the Wheel": agentic AI improves science software
- Four starts: interfaces, install, closed data, agent endpoints
- 3 min problem + demo, then 2 min judges
- Teach the room: for? broken? better? No jargon
- 30 points: impact, technical, presentation (10 each)
- Prizes: £1000 + HF Pro; £500 runner-up; £500 people's
- Submit by Sun 10:00: public repo, MIT, commit hash

## Judges
- Hasson (Apheris), Tsenkov (PDBe), Schröder (Ellison)
- Mroz (CuspAI), Hughes (Inherent), Sheppard (UCL)

## One line
- HubAI: one task board for a team's agents
- Agents and humans share it over MCP

## The problem
- Every hacker runs their own coding agent
- Agents can't see each other's work
- Two agents build the same feature
- One rewrites an API another needs
- Nobody notices until the merge
- Spare PCs sit idle; laptop does everything

## What HubAI does
- Board: To do, Doing, Postpone, Done
- Atomic claims: two agents can't take one task
- Inbox: messages plus automatic board events
- MCP: one `claude mcp add` line, 9 tools
- Worker PCs poll free, run `claude -p` per task
- 3 attempts, then Postpone; silent 15 min → requeued

## Why I trust it
- Follows my own Django best-practices guide
- Split settings, email-only user, uv, environ
- Django 6, HTMX, Bulma, self-hosted, no CDN
- 54 pytest tests; 47 commits
- Live on Appliku: Postgres 17, uvicorn
- Security reviewed by Claude, GPT, Gemini, Qwen

## The proof: SurveyGUI built through it
- Open academic survey builder (a free Qualtrics)
- Builder, logic, results, imports, rich text, MCP drafting
- 467 commits, Fri 17:46 → Sun 08:10
- 60 board tasks, 50 done
- 1 Mac lead + 2 Windows worker PCs
- 2801 pytest; 247 builder e2e on macOS
- Python + TypeScript/Svelte: I don't know TS
- I never read a line of it

## What went wrong; HubAI handled it
- Worker Claude exited instantly: blocked after 3 tries
- Lead Mac took over; 3 tasks done on attempt 3
- Worker PC went silent: task requeued at 15 min
- Windows workers found 26 Windows-only test failures
- Mac lead found Mac-only bug (hidden Bank pane)
- History restored mid-run; lead merged onto it

## Demo beats
- Live board: 50 done, cards moving
- Worker PC claims a task on screen
- Inbox: claim event lands, agent reports done
- Fail a task: card shows "attempt 2 of 3"
- Fallback: HubAI demo video on landing page

## Slides
1. Problem: agents can't see each other + footer
2. HubAI: board screenshot, 3 numbers
3. Live demo (board, worker, inbox)
4. Proof: SurveyGUI numbers + PhD close

## Friday daytime start: decided
- Say it, don't hide it: slide 1 footer
- Footer: "Planning began Friday daytime; first commit 17:46"

## Likely judge questions
- Is SurveyGUI any good? Tests say yes; I can't vouch
- Trust code you didn't read? Tests, review, small tasks
- Why not GitHub Issues? Agents need claims, inbox, retries
- Science link? Science teams build tools with agents
- Safe? Workers take only your own tasks
- Next? Codex/Gemini workers, smarter task splitting

## Close (last slide)
- "Get in touch about PhDs"
- https://www.surrey.ac.uk/artificial-intelligence/cdt
