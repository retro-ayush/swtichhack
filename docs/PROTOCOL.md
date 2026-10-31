# TeamPilot message protocol (cards)

This is the contract between the Coordinator (TeamPilot backend) and the
specialist agents. It is also the text that becomes the Switch **room
instructions** on Nov 4, so every agent that joins the room is briefed once.

## Shape

Every protocol message is **one human-readable line, then a fenced JSON
card**. People read the line on their phone; TeamPilot validates the card.

```
🧱 Blocked on T-3: waiting for the auth API contract
```json
{"type": "BLOCKER", "from": "teampilot-frontend", "task_id": "T-3",
 "message": "Waiting for the authentication API contract", "requires_action": true}
```
```

Rules:
- `task_id` is the TeamPilot key (`T-12`), copied from the TASK_ASSIGNED card.
- Names inside cards are **bare** (`"to": "teampilot-backend"`). Never write
  `@name` in free text: Switch re-parses bodies and a stray mention wakes that
  agent. Addressing is the Coordinator's job.
- Unknown fields are rejected; an invalid card is treated as plain chat and
  nothing happens. If in doubt, send `STATUS_UPDATE`.
- No Markdown tables (Discord/Slack don't render them).
- Reply **in the thread** you were addressed in when there is one.

## Card types

| type | sent by | required fields | effect in TeamPilot |
|---|---|---|---|
| `TASK_ASSIGNED` | coordinator | `to` | work handed to an agent (targeted mention) |
| `TASK_STARTED` | agent | — | task → in_progress; agent → working |
| `STATUS_UPDATE` | agent | `message` | logged; agent → working |
| `INFORMATION_REQUEST` | agent | `to`, `message` | forwarded to `to` as a targeted mention |
| `HANDOFF` | agent | `to`, `message` | forwarded to `to` |
| `BLOCKER` | agent | `message` | task → blocked; humans paged; other ready tasks dispatched |
| `REVIEW_REQUEST` | agent | `message`, optional `diff_ref` | task → in_review; reviewer paged |
| `REVIEW_FEEDBACK` | reviewer | `approved`, optional `findings[]` | approved → completed (or → waiting_approval when human approval is required); rejected → back to owner, attempt +1 |
| `TEST_RESULT` | testing agent | `passed`, `commands[]`, `log_excerpt` | execution run recorded; failure sent back to the owner |
| `TASK_COMPLETED` | agent | `summary`, `evidence` | task → **in_review** (never completed on the agent's word) |
| `HUMAN_APPROVAL_REQUIRED` | coordinator/agent | `action`, `message` | approval row created; shown in the dashboard |

## Non-negotiables for agents

1. **Never report a test as passing unless you ran it and read the output.**
   `TEST_RESULT.log_excerpt` must be the real tail of the real command.
2. Only edit files inside your task's scope; if you need a file another task
   owns, send `INFORMATION_REQUEST` to its owner instead of editing.
3. Work on your own branch `teampilot/<role>/<task_id>`; never merge. Merging
   happens after human approval.
4. If you are stuck for more than a few minutes, send `BLOCKER` — a stalled
   task is auto-blocked after `STALE_TASK_MINUTES` anyway.
5. Say what you are about to do before a long step (one line), then do it.

## Loop guards (enforced by the Coordinator)

- Per task: at most `max_agent_messages_per_task` (12) agent cards between
  human messages, then the task is paused for a human.
- Per task: `max_task_attempts` (3) rejected reviews → failed, human decides.
- Per task: no activity for `STALE_TASK_MINUTES` (20) → blocked, human paged.
- Agents silent for `AGENT_OFFLINE_MINUTES` (10) are shown offline.
