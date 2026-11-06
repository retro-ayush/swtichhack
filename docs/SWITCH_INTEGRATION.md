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

## Provisioning

The full checklist, with a check after each step, is in
[TODO_NOV4.txt](../TODO_NOV4.txt), part A. In short:

1. Install Switch Console (macOS) → local server → connect Discord or
   Mattermost → link your account. [getting-started/*]
2. `python3 scripts/build_agent_prompts.py <demo-repo-url>`, then register
   `teampilot-frontend|backend|testing|reviewer` as Claude Code agents using
   `agents/dist/teampilot-<role>.txt`, with addressing **Anyone** and auto
   mode on.
3. Register `teampilot-coordinator` **without** a Console session. The
   TeamPilot backend is its client over the protocol. Then
   `python3 scripts/switch_env.py` copies its credentials into `backend/.env`.
4. Create room `teampilot` with all five agents. Its instructions are
   `agents/dist/room-instructions.txt`.
5. `python3 scripts/switch_env.py --room <ROOM_ID>`, then restart the backend.
   The dashboard shows **Switch: connected**.

## How the integration is verified without a live server

`backend/tests/test_switch_e2e.py` starts a fake agent bridge that implements
the endpoints above, then runs the real adapter and connector against it over
HTTP. It asserts:

- the stream opens with `connection_id`, `filter=all` and `rooms=<id>`
- a heartbeat runs and `connect_to_room` is called
- a human @mention becomes tasks, and the coordinator answers with
  `send_targeted_message` (TASK_ASSIGNED to the right agent) and
  `post_message`, recorded as `delivered_via=switch`
- an agent's card from the room changes task state
- a chat command (`status`) is answered in the room
- after a dropped socket it reconnects with the same `connection_id` and
  `Last-Event-ID`

This proves the client matches the documented protocol. It cannot prove the
real server behaves as documented; step A6 of the checklist does that.

## Honesty contract

Every persisted message records `delivered_via`: `"switch"` (confirmed op
result) or `"local"` (dashboard-only mode). The UI badges them; the README
and demo narrate the difference. We never claim Switch delivery we didn't get.
