# Pitch notes: HubAI (glance, don't read)

Goal: not to win. Show funders and collaborators how I work.
Strict 3 min + 2 min questions. Organisers' structure: problem → old way → reinvention (most time).

## 1. The problem (~25 s)
- Scientists now build research software with AI agents
- One person can run many agents at once
- But agents can't see each other; work collides
- And nobody can vouch for code they never read
- Footer: "Planning began Friday daytime; first commit 17:46"

## 2. The old way (~35 s): my own weekend
- I built a Qualtrics replacement: one person, many agents
- 467 commits, 2,801 tests, 247 browser tests
- Mostly TypeScript: a language I don't know
- I never read a single line, so I can't stand behind it
- Screenshot: the survey builder (one slide, no demo)

## 3. The reinvention (~2 min): HubAI
- One line: a shared task board for a team's agents
- Built in Django, my stack; I read every line
- Demo: live board, cards moving, 50 tasks done
- Demo: a spare PC claims a task on screen
- Demo: inbox shows the claim and the report
- Failures handled: 3 tries then a human; silent PC requeued
- Fallback: HubAI demo video if the Wi-Fi fails

## Last slide (stays up during questions)
- Top: one line on what I do
- Up to 4 tiles: student screenshot + one-line project
- Bottom: "Get in touch: funding, collaboration, PhDs"
- https://www.surrey.ac.uk/artificial-intelligence/cdt
- Check students are happy to be shown

## Slides (4)
1. Problem: agents can't see each other + footer
2. Old way: SurveyGUI screenshot + "I never read a line"
3. HubAI: live demo (board, worker, inbox)
4. Me, my students, the ask (up during Q&A)

## Likely questions (2 min)
- Is SurveyGUI any good? Tests say yes; I can't vouch
- Trust code you didn't read? Only with tests, small tasks
- Why not GitHub Issues? Agents need claims, inbox, retries
- What would funding buy? Months, not a weekend, of this
- Safe? Workers take only your own tasks
- Can my lab use it? Yes: open source, MIT, free

## Cut if short of time
- SurveyGUI numbers: keep only "never read a line"
- Demo: skip the inbox, keep board + worker claim
