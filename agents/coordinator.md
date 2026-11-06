# teampilot-coordinator (no Console session)

This identity belongs to the **TeamPilot backend**, which speaks the Switch
agent protocol directly. Register it in Switch Console so it gets an identity
and credentials, but **do not start a Claude Code session for it**.

Instructions field to paste in Console:

> Managed by the TeamPilot backend. Do not start a session for this agent.
> If you are reading this inside a session, stop and reply once:
> "teampilot-coordinator runs in the TeamPilot backend; start it with
> uvicorn app.main:app."

Humans talk to it in the room:
- `@teampilot-coordinator <request>` plans tasks
- `@teampilot-coordinator status`
- `@teampilot-coordinator approve T-5 <reason>` / `reject T-5 <reason>`
- `@teampilot-coordinator unblock T-3` / `cancel T-3` / `retry T-3` /
  `reassign T-3 teampilot-frontend`
- `@teampilot-coordinator help`
