# TeamPilot AI

**One team. Multiple AI agents. Coordinated execution. Human control.**

TeamPilot is a team-coordination platform for the *Flip the Switch* hackathon
(WeMakeDevs × DevTools Academy, powered by [Switch](https://docs.switchagents.ai)).
A human posts a request in the team chat; a Coordinator decomposes it into a
dependency-aware task graph, assigns the work to specialist AI agents
(frontend / backend / testing / reviewer), routes their structured messages,
detects blockers, records real test evidence, and gates completion behind
human approval — all visible live on a dashboard.

## How Switch is used

- The **team chat is a Switch room** (bridged to Discord/Mattermost). The
  dashboard mirrors it; we don't build a parallel chat.
- The **Coordinator is a Switch agent**: the backend implements the documented
  [agent protocol](https://docs.switchagents.ai/switch-rooms/internals/agent-protocol)
  — one SSE stream down, heartbeat every 2 s, HTTP ops
  (`post_message`, `send_targeted_message`, `connect_to_room`) up. See
  [backend/app/switchbridge/adapter.py](backend/app/switchbridge/adapter.py) and
  [docs/SWITCH_INTEGRATION.md](docs/SWITCH_INTEGRATION.md) for the
  fact-checked protocol notes.
- The **specialist agents are Claude Code agents run by Switch Console** and
  addressed by targeted mentions (Switch's mention-driven model is why every
  assignment is a targeted message).
- **Honesty rule:** every message records `delivered_via: switch | local`.
  Without Switch credentials the app runs in clearly-labeled **local mode**
  and never claims a Switch delivery it didn't get. ⚠️ *Per the hackathon
  rules, the Switch setup itself (server, agents, room) is created during
  Nov 4–7 — the 30-minute provisioning runbook is in
  [docs/SWITCH_INTEGRATION.md](docs/SWITCH_INTEGRATION.md).*

## Run it

Backend (Python 3.11+):
```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # fill in SWITCH_* / ANTHROPIC_API_KEY when you have them
.venv/bin/python -m uvicorn app.main:app --port 8000
```

Frontend (Node 20+):
```bash
cd frontend
npm install
npm run dev                      # http://localhost:3000 (proxies /api to :8000)
```

Tests (21, includes a full end-to-end workflow and the stall sweep):
```bash
cd backend && .venv/bin/python -m pytest -q
```

Schema is managed by Alembic and upgraded to head on startup
(`backend/alembic/versions/`). To add a migration after a model change:
`cd backend && .venv/bin/alembic revision --autogenerate -m "describe change"`.
(A `teampilot.db` created before migrations existed must be deleted once.)

## Try the demo flow (no credentials needed)

1. Open http://localhost:3000/chat and send
   *“Investigate the login validation bug, fix it, and verify the solution.”*
   with **plan tasks** checked → the Coordinator creates a 5-task DAG
   (investigate → backend fix → frontend → tests → review+approval).
2. Watch `/tasks` (kanban), `/agents`, `/activity` update live (SSE).
3. Agent replies arrive via Switch when connected; in local mode you can
   submit the same JSON cards through
   `POST /api/projects/1/agent-message` (clearly recorded as `local`).
4. The review task parks at **Needs Approval** — approve or reject it in
   `/approvals`; the decision and reason are written to the audit log.
5. `demo-repo/` contains the deliberately introduced, safe bug the agents fix
   live during the hackathon demo (`python3 -m pytest demo-repo -q` → 2
   failures until fixed).

## Guarantees the engine enforces (tested)

- Dependencies form a DAG; cycles are rejected at creation.
- A task cannot start or complete with unmet dependencies.
- An agent saying “done” moves a task to **review**, never to completed.
- Test tasks cannot complete without a recorded **passing** execution run.
- `requires_approval` tasks cannot complete without a human decision — the
  API returns 409 if you try.
- Loop guards: per-task agent-message budget and attempt limits escalate to
  humans instead of retrying forever.
- Time guards: a housekeeping sweep blocks tasks with no activity for
  `STALE_TASK_MINUTES` (20) and pages a human; agents silent for
  `AGENT_OFFLINE_MINUTES` (10) are shown offline. The coordinator is online
  exactly while the backend process runs.

## Message cards

Agents speak in one human-readable line plus a fenced JSON card, validated
against strict schemas (`TASK_ASSIGNED, TASK_STARTED, STATUS_UPDATE,
INFORMATION_REQUEST, BLOCKER, HANDOFF, REVIEW_REQUEST, REVIEW_FEEDBACK,
TEST_RESULT, TASK_COMPLETED, HUMAN_APPROVAL_REQUIRED`). Invalid or unknown
cards are stored as chat and never executed.

## Repo map

```
backend/    FastAPI + SQLAlchemy: coordination engine, Switch adapter, SSE
frontend/   Next.js dashboard: overview, chat, kanban, agents, approvals, activity
demo-repo/  tiny app with the seeded bug for the live demo
docs/       ARCHITECTURE.md · SWITCH_INTEGRATION.md · PROTOCOL.md · DEMO_SCRIPT.md
agents/     (created Nov 4+) role instructions for the Claude Code agents
```

## Current limitations (honest list)

- Switch provisioning happens Nov 4 (hackathon rule); until then the adapter
  reports `disabled` and everything is `local`.
- One Switch room binds to the first project (single-project bridge).
- LLM decomposition needs `ANTHROPIC_API_KEY`; otherwise a transparent
  rule-based planner runs (the UI records which one produced the plan).
- Auth is a single optional bearer token (`TEAMPILOT_API_TOKEN`) — fine for a
  demo, not multi-user auth.
- Agent presence is inferred from their cards plus a time-based sweep; with
  Switch connected, `!agents-status` in the room remains the ground truth for
  session liveness.
