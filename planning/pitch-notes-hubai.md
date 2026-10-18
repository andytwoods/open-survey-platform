# Pitch notes: HubAI (glance, don't read)

Goal: not to win. To show funders and collaborators how I work.

## The event
- "Reinvent the Wheel": agentic AI improves science software
- 3 min problem + demo, then 2 min judges
- Teach the room: for? broken? better? No jargon
- Submit by Sun 10:00: public repo, MIT, commit hash

## Open: the confession (slide 1)
- This weekend I built a Qualtrics replacement
- 467 commits, 2801 tests, 247 browser tests
- Mostly TypeScript: a language I don't know
- I never read a single line of it
- So I can't stand behind it
- That's the real problem with AI-built science software

## The turn
- Trust needs code I can judge
- So: the tool that let me build it

## One line (slide 2)
- HubAI: one task board for a team's agents
- Agents and humans share it over MCP

## What HubAI does
- Board: To do, Doing, Postpone, Done
- Atomic claims: two agents can't take one task
- Inbox: messages plus automatic board events
- Spare PCs become workers; run tasks unattended
- 3 tries, then a human; silent 15 min → requeued

## Why I can stand behind this one
- Django, the stack I know and love
- Follows my own published best-practices guide
- Small: 47 commits, 54 tests, I read it all
- Live on Appliku; reviewed by four AI models

## It worked: SurveyGUI is the evidence
- 60 board tasks, 50 done, overnight
- 1 Mac lead + 2 Windows worker PCs
- Crashed worker: blocked after 3 tries, Mac took over
- Silent worker: task requeued at 15 min
- Windows and Mac bugs caught by splitting machines

## Demo beats (slide 3)
- Live board: 50 done, cards moving
- Worker PC claims a task on screen
- Inbox: claim event lands, agent reports done
- Fallback: HubAI demo video on landing page

## What this says about me (slide 4)
- I build research tools, not just papers
- I know when not to trust AI output
- I make AI work reviewable: small tasks, tests
- Open source, MIT, reusable by any lab
- Ask: funding, collaborators, PhD students

## Likely questions
- Is SurveyGUI any good? Tests say yes; I can't vouch
- Trust code you didn't read? Only with tests, small tasks
- Why not GitHub Issues? Agents need claims, inbox, retries
- What would funding buy? Months, not a weekend, of this
- Safe? Workers take only your own tasks
- Next? More agent types; science teams using it

## Friday daytime start
- Slide 1 footer: "Planning began Friday daytime; first commit 17:46"

## Close (last slide)
- "Get in touch: funding, collaboration, PhDs"
- https://www.surrey.ac.uk/artificial-intelligence/cdt
