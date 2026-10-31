# Switch integration — verified facts and setup

Facts verified 2026-10-31 against the published docs (https://docs.switchagents.ai,
index at `/llms.txt`) and the `sandbox-quantum/switch` repository (clone at
`../switch-ref-src/switch`, commit `a620ab6`). No invented APIs: every call the
adapter makes is listed below with its source.

## What Switch is (one paragraph)

Switch puts AI coding agents and people together in **rooms** bridged to
Slack/Discord/Mattermost/Telegram/Teams channels. Agents act only when
**@addressed**. Switch Console (desktop app) registers agents, runs their
sessions (Claude Code/Codex/OpenCode) on demand, and a server (`switch-core`)
holds rooms and history. A custom program can join as an agent through the
**agent protocol**. [docs: switch-rooms/using/*, internals/*]

## The agent protocol (what our adapter implements)

Source: `docs.switchagents.ai/switch-rooms/internals/agent-protocol` (mirrored
at `docs/official/internals/agent-protocol.md` in the repo).

- **Transport:** one SSE stream down (`GET /agents/{agent_id}/events`), plain
  HTTP up. Auth: `Authorization: Bearer <agent API key>` on every call.
- **Stream open params:** `connection_id` (client-generated UUID, reused on
  reconnect), `scope=single|all`, `filter=all|addressed`, optional
  `rooms=<id>`, `start_from`, `Last-Event-ID` header for resume.
  First frame is `connection_state`.
- **Heartbeat:** `POST /agents/{agent_id}/connection/beat`
  `{"connection_id", "cursor"}` **every 2 s** (TTL 6 s). 404/409 ⇒ reopen the
  stream, don't back off.
- **Events:** `message` (payload: `addressed`, `sender`, `sender_name`,
  `body`, `message_id`, `thread_id`, `timestamp`), `command`, `room_join`,
  task events (the task protocol is explicitly "present but not ready for
  use" — we don't build on it). Control frames: `connection_state`, `gap`,
  `evicted`, `subscription_changed`, `room_released`.
- **Operations:** `POST /agents/{agent_id}/ops/{name}` with header
  `X-Switch-Connection-Id`, body = bare JSON args, response
  `{"result": …}`. Catalog from `GET /agents/{agent_id}/ops`. We use:
  `connect_to_room`, `post_message`, `send_targeted_message` (args
  `target_names`, `body`, optional `thread_id`), `read_context`,
  `list_participants`.
- **Simple post without a connection:** `POST /agents/{agent_id}/message`
  `{"room_id", "content"}` (documented in "Writing a client").
- **Registration:** done once by Switch Console; it writes credentials to
  `.switch/agents/<name>.json` in the agent's working directory:
  `{"env": {"SWITCH_API_ENDPOINT", "SWITCH_API_TOKEN", "SWITCH_AGENT_ID"}}`
  [docs: internals/connectors-and-runtime]. Our backend reads those env vars.

## Rules that shape TeamPilot

1. **Mention-driven:** an agent acts only when a message addresses it
   (`@name`, alias, or role); other agents' posts are not delivered unless it
   reads context. ⇒ the Coordinator sends every assignment/feedback as a
   **targeted message**, and specialist agents are instructed to reply in
   thread. [using/mention-and-message]
2. **Never put `@name` in free text** — Switch re-parses bodies and a stray
   mention wakes that agent; the JSON card thus carries bare names, and
   addressing happens only via `send_targeted_message`. [Console switch-skill]
3. **Approvals in the room:** a coding agent's permission prompts appear in
   the room; whoever may address the agent may answer. [switch-skill
   "Questions and approvals"]
4. **Session control commands** from chat: `!agents-status`, `!interrupt @x`,
   `!reset @x`. [resources/room-commands]
5. **Formatting:** Discord/Slack render no Markdown tables → cards are
   line-based. [switch-skill "Formatting"]

## Nov-4 provisioning (done during the hackathon, ~30 min)

1. Install Switch Console (macOS) → local server → connect Discord/Mattermost
   → link account. [getting-started/*]
2. Register 4 agents (frontend/backend/testing/reviewer) as Claude Code
   agents, instructions from `agents/<role>.md`, addressing **anyone**,
   auto-mode on.
3. Register `teampilot-coordinator` as an agent **without** a Console session
   (TeamPilot's backend is its "session" via the protocol). Copy the env vars
   from `.switch/agents/teampilot-coordinator.json` into `backend/.env`.
4. Create room `#teampilot` with all five agents + the team; room
   instructions = the card protocol (generated from `docs/PROTOCOL.md`).
5. Set `SWITCH_ROOM_ID`, restart the backend → the dashboard header shows
   **Switch: connected**.

## Honesty contract

Every persisted message records `delivered_via`: `"switch"` (confirmed op
result) or `"local"` (dashboard-only mode). The UI badges them; the README
and demo narrate the difference. We never claim Switch delivery we didn't get.
