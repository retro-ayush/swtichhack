# TeamPilot AI

**One team. Multiple AI agents. Coordinated execution. Human control.**

TeamPilot is a team-coordination platform for the *Flip the Switch* hackathon
(WeMakeDevs × DevTools Academy, powered by [Switch](https://docs.switchagents.ai)).
A human posts a request in the team chat. A Coordinator breaks it into a
dependency-aware task graph and assigns the work to specialist AI agents
(frontend, backend, testing, reviewer). It then routes their structured
messages, detects blockers, records real test evidence, and gates completion
behind human approval. All of it is visible live on a dashboard.

## How Switch is used

- The **team chat is a Switch room** (bridged to Discord or Mattermost). The
  dashboard mirrors it; there is no parallel chat system.
- The **Coordinator is a Switch agent**. The backend implements the documented
  [agent protocol](https://docs.switchagents.ai/switch-rooms/internals/agent-protocol):
  one SSE stream down, a heartbeat every 2 s, and HTTP ops up
  (`connect_to_room`, `post_message`, `send_targeted_message`). It reconnects
  with the same connection id and resumes from `Last-Event-ID`. See
  [backend/app/switchbridge/adapter.py](backend/app/switchbridge/adapter.py) and
  [docs/SWITCH_INTEGRATION.md](docs/SWITCH_INTEGRATION.md).
- The **specialist agents are Claude Code agents run by Switch Console**.
  Their instructions are in [agents/](agents/). They are addressed with targeted
  mentions, because in Switch an agent acts only when addressed. Their
  permission prompts appear in the room, so a teammate can answer them from a phone.
- **Humans steer from the room:** `@teampilot-coordinator <request>` plans
  work; `approve T-5`, `reject T-5 <why>`, `unblock T-3`, `cancel`, `retry`,
  `reassign` and `status` control it.
- **Honesty rule:** every message records `delivered_via: switch | local`.
  Without Switch credentials the app runs in a clearly labeled **local
  mode**, and it never claims a Switch delivery it didn't get.

## Run it

Backend (Python 3.11+):
```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # optional: SWITCH_*, ANTHROPIC_API_KEY, TEAMPILOT_API_TOKEN
.venv/bin/python -m uvicorn app.main:app --port 8000
```

Frontend (Node 20+):
```bash
cd frontend
npm install
cp .env.example .env.local       # optional: BACKEND_URL, TEAMPILOT_API_TOKEN
npm run dev                      # http://localhost:3000
```

The dashboard reaches the backend through a server-side proxy
(`frontend/app/api/[...path]/route.ts`). When `TEAMPILOT_API_TOKEN` is set on
both sides, every `/api` route requires it, and the proxy adds it so it never
reaches the browser.

Tests: 33 backend tests, including a full workflow test and a real-HTTP test
against a fake Switch bridge.
```bash
cd backend && .venv/bin/python -m pytest -q
```
CI (`.github/workflows/ci.yml`) runs the backend tests, a migration from an
empty database, frontend lint, typecheck and build, and the helper scripts.

Alembic manages the schema and upgrades it to head on startup. A database
from before migrations existed is detected and stamped automatically. After a
model change: `cd backend && .venv/bin/alembic revision --autogenerate -m "..."`.

## Connect to Switch

Step by step, with a check at each step: [TODO_NOV4.txt](TODO_NOV4.txt). The
short version:
1. `python3 scripts/build_agent_prompts.py <demo-repo-url>` writes
   paste-ready instructions to `agents/dist/`.
2. In Switch Console, register `teampilot-frontend|backend|testing|reviewer`
   (Claude Code, "Anyone" may talk) and `teampilot-coordinator` (directory
   `backend/`, no session). Create a room with all five, and paste
   `agents/dist/room-instructions.txt` as its instructions.
3. Run `python3 scripts/switch_env.py --room <ROOM_ID>`. It copies the
   coordinator's credentials into `backend/.env`.
4. Restart the backend. The sidebar shows **Switch: connected**.

## Try the demo flow (no credentials needed)

1. Open http://localhost:3000/chat and send
   *"Investigate the login validation bug, fix it, and verify the solution."*
   with **plan tasks** checked. The Coordinator creates a 5-task DAG:
   investigate → backend fix → frontend → tests → review and approval.
2. Watch `/tasks` (kanban), `/agents` and `/activity` update live over SSE.
   Type `status` or `help` in the chat.
3. When Switch is connected, agent replies arrive through it. In local mode
   you can submit the same JSON cards with `POST /api/projects/1/agent-message`;
   they are recorded as `local`. A malformed card gets a reply that explains
   the problem, so the agent can resend it.
4. The review task waits at **Needs Approval**. Approve or reject it in
   `/approvals` or in chat. The decision and the reason go into the audit log.
5. `demo-repo/` contains a deliberately introduced, safe bug for the agents to
   fix (`python3 -m pytest demo-repo -q` reports 2 failures until it's fixed).
   It is published as its own repo for the agents to work on:
   [retro-ayush/teampilot-demo-app](https://github.com/retro-ayush/teampilot-demo-app).

## Guarantees the engine enforces (tested)

- Dependencies form a DAG; cycles are rejected at creation.
- A task cannot start or complete with unmet dependencies.
- An agent saying "done" moves a task to **review**, never to completed.
- Test tasks cannot complete without a recorded **passing** execution run.
- `requires_approval` tasks cannot complete without a human decision. The
  API returns 409, and chat commands use the same engine functions.
- Loop guards: a per-task agent-message budget (12) and an attempt limit (3)
  escalate to humans instead of retrying forever.
- Time guards: tasks with no activity for `STALE_TASK_MINUTES` (20) are
  blocked and a human is paged. Agents silent for `AGENT_OFFLINE_MINUTES` (10)
  are shown offline.
- Input limits: chat and card bodies max 20,000 characters; unknown card fields
  are rejected.

## Message cards

Agents post one human-readable line followed by a fenced JSON card, validated
against strict schemas: `TASK_ASSIGNED, TASK_STARTED, STATUS_UPDATE,
INFORMATION_REQUEST, BLOCKER, HANDOFF, REVIEW_REQUEST, REVIEW_FEEDBACK,
TEST_RESULT, TASK_COMPLETED, HUMAN_APPROVAL_REQUIRED`. The full contract is in
[docs/PROTOCOL.md](docs/PROTOCOL.md).

## Repo map

```
backend/    FastAPI + SQLAlchemy: coordination engine, chat commands, Switch adapter, SSE, Alembic
frontend/   Next.js dashboard: overview, chat, kanban, agents, approvals, activity; token proxy
agents/     role instructions for the Claude Code agents (+ coordinator note)
scripts/    build_agent_prompts.py, switch_env.py (standard library, cross-platform)
demo-repo/  tiny app with the seeded bug for the live demo
docs/       ARCHITECTURE · SWITCH_INTEGRATION · PROTOCOL · DEMO_SCRIPT · screenshots
```

## Limitations

- The live Switch round trip is tested against a protocol-faithful fake,
  not the real server. It is proven live by TODO_NOV4.txt step A6.
- One Switch room drives one TeamPilot project (`SWITCH_PROJECT_ID`).
- LLM decomposition needs `ANTHROPIC_API_KEY`. Without it, a transparent
  rule-based planner runs, and the activity log records which one ran.
- Auth is one shared bearer token, not per-user accounts. People are
  identified by their chat name.
- Agent presence is inferred from cards plus a time-based sweep. With Switch
  connected, `!agents-status` in the room is the ground truth.
- All agents run from one machine's Switch Console (a Console-run server is
  single-owner); teammates join from Discord on any device.
