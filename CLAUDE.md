Read `AGENTS.md` first and follow it. It is the guide for this repo.

## Coordinating with teammates (HubAI)

This project uses the HubAI MCP server to coordinate with teammates' agents.
Always pass agent="<short name for this agent, e.g. claude-backend>" to HubAI tools.
At the start of every task and between steps: call read_inbox, then list_tasks.
Claim a task (claim_task) before working on it. Mark it done or blocked with update_task.
Post a message (post_message) when you change something others depend on (APIs, schemas, shared files).
