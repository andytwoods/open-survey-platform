# Pitch notes (glance, don't read)

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

## The project
- One line: a free, open Qualtrics for researchers
- Problem: Qualtrics licence costs keep rising
- Problem: studies locked in; can't replay or move
- Builder: drag, undo, palette, 9 question types
- Logic, randomisers, quotas, consent, languages, resume
- Results charts, figure export, saved layouts
- Import Qualtrics / LimeSurvey / SurveyJS; export XLSForm
- AI drafts surveys via MCP; can't publish
- OSF preregistration bundle; replay any response

## Architecture
- Python core + FastAPI; Svelte builder and runtime
- Engine runs in the browser; server saves only
- Your app signs researchers in; no passwords here
- SQLite or Postgres; answers encrypted at rest

## Verified numbers (log/devlog.md entry)
- 2801 pytest (V4), 817 vitest (UI1)
- 194 builder e2e passed (V5b)
- 40 fixture surveys, 79 scripts, real browsers (CI1)
- 10k responses: 0.40 s, cached 4 ms (V1)
- 100k responses: 5.3 s, cached 38 ms (V1)
- CI on Ubuntu + Windows, under 6 min (CI1)

## Build story
- One person, no team
- Me as lead; AI agents write the code
- HubAI = the agents' shared task board
- Worker PCs (Windows too) claim tasks, push branches
- Spikes first: LimeSurvey, Enketo, then our own runtime
- Every task: `make check` green before merge

## Impact: it deploys
- Tutorial chapter: Hetzner server + Dokku
- Real server, own domain, HTTPS
- Two apps: Django study app + osp-api
- Tested end to end on a real server, 17 Oct 2026
- jsPsych → PsychoPy → survey, one participant ID

## Demo beats
- Build: add questions, condition, randomiser, undo
- Publish: checks, consent, theme, copy link
- Participant: refresh mid-page, resume on phone
- Results: charts, export a figure (live only, no video)
- Fallback: `.build/demo/` videos 01, 02, 03

## Slides
1. Problem in one picture + footer line
2. What it is: builder screenshot, 3 numbers
3. Live demo (or videos)
4. Deploy + build story + PhD close

## Friday daytime start: decided
- Say it, don't hide it: slide 1 footer
- Footer: "Planning began Friday daytime; first commit 17:46"

## Likely judge questions
- Why not LimeSurvey? Spiked it: order, replay lost
- Who uses it? Any lab tired of licence fees
- Data safe? Encrypted, retention enforced, self-hosted
- Is it real? 194 e2e, deploys on Hetzner
- What did AI do? Wrote code; I set tasks, reviewed
- Next? Rich text, endings, live results

## Close (last slide)
- "Get in touch about PhDs"
- https://www.surrey.ac.uk/artificial-intelligence/cdt
