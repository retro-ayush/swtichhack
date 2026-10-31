# Demo script (2–3 minutes)

Setup before recording: backend + frontend running, Switch room `#teampilot`
on Discord with the five agents, dashboard open on a laptop, Discord open on a
phone. `demo-repo/` checked out by the agents with its seeded bug
(`python3 -m pytest demo-repo -q` → 2 failures).

| t | Screen | What happens | Say |
|---|---|---|---|
| 0:00 | phone, Discord | Type `@teampilot-coordinator Investigate the login validation bug, fix it, and verify the solution.` | "One request, from a phone, in the team's normal chat — a Switch room." |
| 0:15 | laptop, /tasks | Five cards appear: investigate → backend fix → frontend → tests → review 🔒. Dependencies gray out downstream cards. | "The coordinator decomposed it into a dependency graph. Nothing downstream can start early — the engine enforces that, not the agents' goodwill." |
| 0:35 | Discord | `teampilot-backend` replies `TASK_STARTED`, then posts findings; the room shows a real stack trace. | "Every message you see is a real Switch room message. TeamPilot is itself a Switch agent on the protocol." |
| 1:00 | Discord | Backend agent sends `BLOCKER` (needs the test command). Dashboard: card turns red, Overview shows "Attention needed". | "Blockers are explicit. Humans get paged; the other ready task keeps going in parallel." |
| 1:10 | phone | Human answers in the thread; `/tasks` → Unblock. | "Humans stay in the loop from wherever they are." |
| 1:25 | Discord | Testing agent runs pytest → `TEST_RESULT passed:false` with real log tail; coordinator bounces it back to the owner. | "The testing agent cannot say 'passing' without the output. Failed runs are recorded and routed back." |
| 1:50 | Discord | Fix pushed, `TEST_RESULT passed:true`, reviewer `REVIEW_FEEDBACK approved`. | "Reviewer is a separate agent session — independent eyes." |
| 2:10 | laptop, /approvals | Final task waits at **Needs Approval**. Type a reason, click Approve. Kanban moves to Completed; Activity shows the audit trail. | "Completion needs evidence *and* a human decision. API calls that skip the gate get a 409." |
| 2:30 | laptop, /agents | Statuses: idle/working/offline from real signals. End on README's 'How Switch is used'. | "Switch is the room, the identity and the delivery; TeamPilot is the coordination brain. Pull the plug on Switch and the badges say `local` — we never fake it." |

Backup plan if a live agent misbehaves: the same cards can be posted through
`POST /api/projects/1/agent-message` (recorded as `local`); say so on camera.
