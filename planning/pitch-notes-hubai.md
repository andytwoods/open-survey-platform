# Pitch notes: HubAI (glance, don't read)

Goal: not to win. Show funders and collaborators how I work.
Strict 3 min + 2 min questions. Organisers' structure: problem → old way → reinvention (most time).

## 1. The problem (~25 s)
- Scientists now build research software with AI agents
- One person can run many agents at once
- A lab or hackathon team runs many more
- But agents can't see each other; work collides
- Footer: "Planning began Friday daytime; first commit 17:46"

## 2. The old way (~35 s): one screenshot slide
- Kanban apps for agents: Vibe Kanban, Kanbots, Kanban Code
  - one person, one machine, one card = one agent
- Agent messaging: MCP Agent Mail
  - agents talk and reserve files; no shared task board
- Vendor clouds: assign a GitHub issue to Copilot
  - paid, their machines, one agent per issue
- Gap: a team of people, their agents and spare PCs, one board

## 3. The reinvention (~2 min): HubAI
- One line: a shared task board for a team's agents
- Any agent joins over MCP: one line to add
- Claims: two agents can't take the same task
- Inbox: agents and people message each other
- Spare PCs become workers, on Windows or Mac
- Failures handled: 3 tries then a human; silent PC requeued
- Built in Django, my stack; open source, self-hosted, free

## Demo beats (inside part 3)
- Live board: this weekend's tasks, 50 done
- Say: "three PCs built an app overnight through this"
- A spare PC claims a task on screen
- Inbox: the claim lands, the agent reports back
- Fallback: screen recording if the Wi-Fi fails

## Last slide (stays up during questions)
- Top: one line on what I do
- Up to 4 tiles: student screenshot + one-line project
- Bottom: "Get in touch: funding, collaboration, PhDs"
- https://www.surrey.ac.uk/artificial-intelligence/cdt
- Check students are happy to be shown

## Slides (4)
1. Problem: many agents, no shared view + footer
2. Old way: the four tools, one line each, the gap
3. HubAI: live demo (board, worker, inbox)
4. Me, my students, the ask (up during Q&A)

## Likely questions (2 min)
- Why not Vibe Kanban? One person's laptop; HubAI is a team
- Why not Agent Mail? Messages, but no board or workers
- Why not GitHub Issues + Copilot? Paid cloud; HubAI uses your PCs
- Trust code agents wrote? Small tasks, tests, a human merges
- What would funding buy? Months, not a weekend, of this
- Can my lab use it? Yes: open source, MIT, free

## Cut if short of time
- Old way: name the tools, skip the sub-bullets
- Demo: skip the inbox, keep board + worker claim

## Sources (checked 18 Oct 2026)
- https://www.vibekanban.com/
- https://github.com/langwatch/kanban-code
- https://ai-tldr.dev/tools/kanbots/
- https://github.com/Dicklesworthstone/mcp_agent_mail
- https://docs.github.com/en/copilot/using-github-copilot/coding-agent/using-copilot-to-work-on-an-issue
