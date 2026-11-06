"""The Coordinator: turns requests into tasks, routes agent cards, enforces
limits, and escalates to humans. State lives in the DB; the Switch room is the
communication bus (adapter delivers when connected, otherwise messages are
recorded as local — never claimed as delivered)."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import events
from ..config import settings
from ..models import (
    Agent, AgentStatus, Approval, ApprovalStatus, ExecutionRun, Message, Project,
    Task, TaskDependency, TaskStatus,
)
from ..schemas import AgentCard
from ..switchbridge import adapter as switch
from . import decompose as dec
from .state import TransitionError, record_event, transition

log = logging.getLogger(__name__)
COORDINATOR_NAME = "teampilot-coordinator"
_card_adapter: TypeAdapter[AgentCard] = TypeAdapter(AgentCard)

_FENCE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


# ------------------------------------------------------------------ messaging
def extract_card(body: str) -> AgentCard | None:
    m = _FENCE.search(body)
    raw = m.group(1) if m else (body.strip() if body.strip().startswith("{") else None)
    if not raw:
        return None
    try:
        return _card_adapter.validate_python(json.loads(raw))
    except (json.JSONDecodeError, ValidationError):
        return None


def card_error(body: str) -> str | None:
    """Why a message that *tried* to carry a card (has a ```json fence) is
    invalid, in one line an agent can act on. None when there is no card
    attempt or the card is valid."""
    m = _FENCE.search(body)
    if not m:
        return None
    try:
        _card_adapter.validate_python(json.loads(m.group(1)))
        return None
    except json.JSONDecodeError as e:
        return f"card is not valid JSON ({e.msg} at char {e.pos})"
    except ValidationError as e:
        parts = []
        for err in e.errors()[:4]:
            loc = ".".join(str(x) for x in err["loc"] if not str(x).endswith("Card"))
            parts.append(f"{loc or 'card'}: {err['msg']}")
        return "card rejected: " + "; ".join(parts)


def reject_invalid_card(db: Session, project_id: int, sender: str, error: str, thread_id: str = "") -> None:
    """Tell the agent its card was ignored and why (bounded by the per-task
    message budget the agent's retries count against)."""
    text = (f"⚠️ Your last message was not applied: {error}. Resend it with exactly one ```json card "
            "using only the documented fields (see the room instructions).")
    via = switch.deliver(text, target=sender, thread_id=thread_id or None)
    _persist_message(db, project_id, sender_type="coordinator", sender_name=COORDINATOR_NAME,
                     content=text, message_type="CARD_REJECTED", delivered_via=via,
                     recipient=sender, thread_id=thread_id)


def _persist_message(
    db: Session, project_id: int, *, sender_type: str, sender_name: str,
    content: str, message_type: str = "CHAT", task_id: int | None = None,
    structured: dict | None = None, delivered_via: str = "local",
    recipient: str = "", thread_id: str = "", switch_message_id: str = "",
) -> Message:
    msg = Message(
        project_id=project_id, task_id=task_id, sender_type=sender_type,
        sender_id=sender_name, sender_name=sender_name, recipient_id=recipient,
        message_type=message_type, content=content, structured=structured,
        delivered_via=delivered_via, thread_id=thread_id,
        switch_message_id=switch_message_id,
    )
    db.add(msg)
    db.flush()
    events.publish({"kind": "message", "project_id": project_id, "id": msg.id,
                    "sender_name": sender_name, "sender_type": sender_type,
                    "message_type": message_type, "content": content,
                    "task_id": task_id, "delivered_via": delivered_via})
    return msg


def _send_card(db: Session, project_id: int, card: dict, *, to_agent: str | None,
               human_line: str, task_id: int | None, thread_id: str = "") -> Message:
    """Post a coordinator card into the room (targeted when to_agent is set).
    delivered_via records what actually happened."""
    body = f"{human_line}\n```json\n{json.dumps(card, indent=2)}\n```"
    via = switch.deliver(body, target=to_agent, thread_id=thread_id or None)
    return _persist_message(
        db, project_id, sender_type="coordinator", sender_name=COORDINATOR_NAME,
        content=body, message_type=card.get("type", "CHAT"), task_id=task_id,
        structured=card, delivered_via=via, recipient=to_agent or "", thread_id=thread_id,
    )


def reply(db: Session, project_id: int, text: str, thread_id: str = "") -> Message:
    """Plain coordinator reply (command results, help) into the room."""
    via = switch.deliver(text, target=None, thread_id=thread_id or None)
    return _persist_message(db, project_id, sender_type="coordinator", sender_name=COORDINATOR_NAME,
                            content=text, message_type="CHAT", delivered_via=via, thread_id=thread_id)


# ----------------------------------------------------------------- assignment
def pick_agent(db: Session, project_id: int, role: str) -> Agent | None:
    """Transparent rule-based assignment: matching role, prefer non-blocked,
    then fewest open tasks."""
    agents = db.execute(
        select(Agent).where(Agent.project_id == project_id, Agent.role == role)
    ).scalars().all()
    if not agents:
        return None

    def open_tasks(a: Agent) -> int:
        return db.execute(
            select(func.count(Task.id)).where(
                Task.assigned_agent_id == a.id,
                Task.status.in_([s.value for s in (
                    TaskStatus.ready, TaskStatus.in_progress, TaskStatus.in_review)]),
            )
        ).scalar_one()

    return sorted(agents, key=lambda a: (a.status == AgentStatus.blocked.value, open_tasks(a)))[0]


# ------------------------------------------------------------- user requests
def handle_user_request(db: Session, project: Project, text: str, requested_by: str) -> list[Task]:
    decomposition = dec.decompose(text)
    specs = decomposition.subtasks

    tasks: list[Task] = []
    for spec in specs:
        agent = pick_agent(db, project.id, spec.role)
        t = Task(
            project_id=project.id, title=spec.title, description=spec.description,
            kind=spec.kind, priority=spec.priority, requires_approval=spec.requires_approval,
            assigned_agent_id=agent.id if agent else None, created_by=requested_by,
            status=TaskStatus.backlog.value,
        )
        db.add(t)
        tasks.append(t)
    db.flush()

    for spec, t in zip(specs, tasks):
        for idx in spec.depends_on:
            db.add(TaskDependency(task_id=t.id, depends_on_task_id=tasks[idx].id))
    db.flush()

    for spec, t in zip(specs, tasks):
        agent_name = t.assigned_agent.name if t.assigned_agent else "(unassigned)"
        record_event(db, t, "created", requested_by, {
            "decomposition_source": decomposition.source,
            "assigned_to": agent_name,
            "assignment_rule": f"role={spec.role}, least-loaded",
        })
        if not spec.depends_on:
            transition(db, t, TaskStatus.ready, COORDINATOR_NAME, "no dependencies")

    summary_lines = [f"Created {len(tasks)} task(s) from the request ({decomposition.source} decomposition):"]
    summary_lines += [
        f"- {t.key} [{s.role}] {t.title}" + (f" (after {', '.join(tasks[i].key for i in s.depends_on)})" if s.depends_on else "")
        for s, t in zip(specs, tasks)
    ]
    via = switch.deliver("\n".join(summary_lines), target=None)
    _persist_message(db, project.id, sender_type="coordinator", sender_name=COORDINATOR_NAME,
                     content="\n".join(summary_lines), message_type="STATUS_UPDATE",
                     delivered_via=via)
    dispatch_ready_tasks(db, project)
    return tasks


def dispatch_ready_tasks(db: Session, project: Project) -> int:
    """Send TASK_ASSIGNED for every ready, assigned, not-yet-dispatched task.

    Idempotent, so the housekeeping sweep calls it too. While Switch is
    configured, only a Switch-delivered assignment counts as dispatched: one
    recorded "local" (the adapter was reconnecting) is sent again."""
    db.flush()
    ready = db.execute(
        select(Task).where(Task.project_id == project.id, Task.status == TaskStatus.ready.value)
    ).scalars().all()
    must_reach_switch = switch.get_adapter() is not None
    sent = 0
    for t in ready:
        if not t.assigned_agent:
            continue
        q = select(Message.id).where(Message.task_id == t.id, Message.message_type == "TASK_ASSIGNED")
        if must_reach_switch:
            q = q.where(Message.delivered_via == "switch")
        already = db.execute(q.limit(1)).scalar()
        if already:
            continue
        card = {
            "type": "TASK_ASSIGNED", "from": COORDINATOR_NAME, "to": t.assigned_agent.name,
            "task_id": t.key,
            "message": f"{t.title}. {t.description} Reply with TASK_STARTED, then STATUS_UPDATE / BLOCKER / REVIEW_REQUEST / TEST_RESULT cards.",
        }
        _send_card(db, project.id, card, to_agent=t.assigned_agent.name,
                   human_line=f"📋 {t.key} assigned to {t.assigned_agent.name}: {t.title}",
                   task_id=t.id)
        record_event(db, t, "dispatched", COORDINATOR_NAME, {"to": t.assigned_agent.name})
        sent += 1
    return sent


# -------------------------------------------------------------- agent cards
def _task_by_key(db: Session, project_id: int, key: str | None) -> Task | None:
    if not key:
        return None
    m = re.fullmatch(r"T-(\d+)", key.strip())
    if not m:
        return None
    t = db.get(Task, int(m.group(1)))
    return t if t is not None and t.project_id == project_id else None


def _touch_agent(db: Session, project_id: int, name: str, status: AgentStatus | None = None) -> Agent | None:
    agent = db.execute(
        select(Agent).where(Agent.project_id == project_id, Agent.name == name)
    ).scalars().first()
    if agent:
        agent.last_seen_at = datetime.now(timezone.utc)
        if status:
            agent.status = status.value
        events.publish({"kind": "agent", "project_id": project_id, "name": agent.name,
                        "status": agent.status})
    return agent


_PRESENCE: dict[str, AgentStatus] = {
    "TASK_STARTED": AgentStatus.working, "STATUS_UPDATE": AgentStatus.working,
    "INFORMATION_REQUEST": AgentStatus.waiting, "HANDOFF": AgentStatus.waiting,
    "BLOCKER": AgentStatus.blocked, "REVIEW_REQUEST": AgentStatus.waiting,
    "REVIEW_FEEDBACK": AgentStatus.idle, "TEST_RESULT": AgentStatus.idle,
    "TASK_COMPLETED": AgentStatus.idle, "HUMAN_APPROVAL_REQUIRED": AgentStatus.waiting,
}


def handle_card(db: Session, project: Project, card: AgentCard, msg: Message) -> None:
    """Apply one validated agent card to project state. Unknown/invalid cards
    never reach this function."""
    task = _task_by_key(db, project.id, card.task_key)
    sender = card.from_agent
    # Every card is a liveness signal for its sender.
    _touch_agent(db, project.id, sender, _PRESENCE.get(card.type, AgentStatus.idle))

    if task is not None:
        task.agent_message_count += 1
        if task.agent_message_count > settings.max_agent_messages_per_task and \
                task.status not in (TaskStatus.blocked.value, TaskStatus.completed.value):
            try:
                transition(db, task, TaskStatus.blocked, COORDINATOR_NAME,
                           "agent message budget exceeded — human input required")
            except TransitionError:
                pass
            _send_card(db, project.id, {
                "type": "HUMAN_APPROVAL_REQUIRED", "from": COORDINATOR_NAME,
                "task_id": task.key,
                "action": "Message budget exceeded; a human must unblock or cancel this task.",
                "message": f"{task.key} exceeded {settings.max_agent_messages_per_task} agent messages.",
            }, to_agent=None, human_line=f"🚦 {task.key} paused: message budget exceeded, human needed.",
               task_id=task.id)
            return

    kind = card.type
    try:
        if kind == "TASK_STARTED" and task:
            transition(db, task, TaskStatus.in_progress, sender)
            task.attempts += 1
            _touch_agent(db, project.id, sender, AgentStatus.working)

        elif kind == "STATUS_UPDATE" and task:
            record_event(db, task, "status_update", sender, {"message": card.message})
            _touch_agent(db, project.id, sender)

        elif kind in ("INFORMATION_REQUEST", "HANDOFF"):
            to = card.to  # type: ignore[union-attr]
            if task:
                record_event(db, task, kind.lower(), sender, {"to": to, "message": card.message})
            _send_card(db, project.id, {
                "type": kind, "from": COORDINATOR_NAME, "to": to,
                "task_id": card.task_key,
                "message": f"(forwarded from {sender}) {card.message}",
            }, to_agent=to, human_line=f"↪️ {sender} → {to}: {card.message[:140]}",
               task_id=task.id if task else None, thread_id=msg.thread_id)
            _touch_agent(db, project.id, sender, AgentStatus.waiting)

        elif kind == "BLOCKER" and task:
            transition(db, task, TaskStatus.blocked, sender, card.message)
            _touch_agent(db, project.id, sender, AgentStatus.blocked)
            others = dispatch_ready_tasks(db, project)
            _send_card(db, project.id, {
                "type": "HUMAN_APPROVAL_REQUIRED", "from": COORDINATOR_NAME,
                "task_id": task.key,
                "action": "Resolve blocker or reassign",
                "message": f"{sender} is blocked on {task.key}: {card.message}. "
                           f"{others} other task(s) continue in parallel.",
            }, to_agent=None, human_line=f"🧱 Blocker on {task.key} from {sender}: {card.message[:140]}",
               task_id=task.id)

        elif kind == "REVIEW_REQUEST" and task:
            transition(db, task, TaskStatus.in_review, sender, card.message)
            _touch_agent(db, project.id, sender, AgentStatus.waiting)
            reviewer = pick_agent(db, project.id, "reviewer")
            if reviewer:
                _send_card(db, project.id, {
                    "type": "REVIEW_REQUEST", "from": COORDINATOR_NAME, "to": reviewer.name,
                    "task_id": task.key,
                    "message": f"Review requested by {sender}. "
                               + (f"Ref: {card.diff_ref}. " if getattr(card, "diff_ref", "") else "")
                               + card.message,
                }, to_agent=reviewer.name, human_line=f"👀 {task.key} ready for review ({reviewer.name})",
                   task_id=task.id, thread_id=msg.thread_id)
                _touch_agent(db, project.id, reviewer.name, AgentStatus.reviewing)

        elif kind == "REVIEW_FEEDBACK" and task:
            approved_flag = card.approved  # type: ignore[union-attr]
            record_event(db, task, "review_feedback", sender,
                         {"approved": approved_flag, "findings": getattr(card, "findings", [])})
            if approved_flag:
                if task.requires_approval:
                    transition(db, task, TaskStatus.waiting_approval, sender)
                    db.add(Approval(task_id=task.id, requested_by=sender))
                    db.flush()
                    _send_card(db, project.id, {
                        "type": "HUMAN_APPROVAL_REQUIRED", "from": COORDINATOR_NAME,
                        "task_id": task.key, "action": "approve or reject in the TeamPilot dashboard",
                        "message": f"Review passed for {task.key}; human approval required before completion.",
                    }, to_agent=None, human_line=f"✅ Review passed — {task.key} awaits human approval.",
                       task_id=task.id)
                else:
                    transition(db, task, TaskStatus.completed, sender, "review approved")
                    task.completion_summary = card.message or "Approved by reviewer."
                    dispatch_ready_tasks(db, project)
            else:
                transition(db, task, TaskStatus.in_progress, sender, "changes requested")
                owner = task.assigned_agent.name if task.assigned_agent else None
                if task.attempts >= settings.max_task_attempts:
                    transition(db, task, TaskStatus.failed, COORDINATOR_NAME, "attempt limit reached")
                    _send_card(db, project.id, {
                        "type": "HUMAN_APPROVAL_REQUIRED", "from": COORDINATOR_NAME,
                        "task_id": task.key, "action": "retry, reassign or cancel",
                        "message": f"{task.key} failed review {task.attempts} times; human decision needed.",
                    }, to_agent=None, human_line=f"❌ {task.key} hit the attempt limit; human needed.",
                       task_id=task.id)
                elif owner:
                    _send_card(db, project.id, {
                        "type": "REVIEW_FEEDBACK", "from": COORDINATOR_NAME, "to": owner,
                        "task_id": task.key, "approved": False,
                        "findings": getattr(card, "findings", []),
                        "message": f"Reviewer requested changes: {card.message}",
                    }, to_agent=owner, human_line=f"🔁 {task.key}: changes requested, back to {owner}.",
                       task_id=task.id, thread_id=msg.thread_id)

        elif kind == "TEST_RESULT" and task:
            passed = card.passed  # type: ignore[union-attr]
            db.add(ExecutionRun(
                task_id=task.id, agent_id=task.assigned_agent_id,
                status="passed" if passed else "failed",
                finished_at=datetime.now(timezone.utc),
                output_summary=getattr(card, "log_excerpt", "")[:4000],
                error_summary="" if passed else card.message[:2000],
            ))
            record_event(db, task, "test_result", sender,
                         {"passed": passed, "commands": getattr(card, "commands", [])})
            if not passed and task.assigned_agent and task.assigned_agent.name != sender:
                _send_card(db, project.id, {
                    "type": "REVIEW_FEEDBACK", "from": COORDINATOR_NAME,
                    "to": task.assigned_agent.name, "task_id": task.key, "approved": False,
                    "findings": [card.message], "message": f"Tests failed: {card.message}",
                }, to_agent=task.assigned_agent.name,
                   human_line=f"🧪 {task.key} tests FAILED — sent back to {task.assigned_agent.name}.",
                   task_id=task.id, thread_id=msg.thread_id)

        elif kind == "TASK_COMPLETED" and task:
            # An agent saying "done" never completes a task: it goes to review.
            if task.status == TaskStatus.in_progress.value:
                transition(db, task, TaskStatus.in_review, sender, "agent reports done")
            record_event(db, task, "agent_reported_done", sender,
                         {"summary": getattr(card, "summary", ""), "evidence": getattr(card, "evidence", "")})
            _touch_agent(db, project.id, sender, AgentStatus.idle)
            reviewer = pick_agent(db, project.id, "reviewer")
            if reviewer and reviewer.name != sender:
                _send_card(db, project.id, {
                    "type": "REVIEW_REQUEST", "from": COORDINATOR_NAME, "to": reviewer.name,
                    "task_id": task.key,
                    "message": f"{sender} reports {task.key} done. Verify against the evidence: "
                               f"{getattr(card, 'evidence', '(none provided)')}",
                }, to_agent=reviewer.name, human_line=f"👀 {task.key} reported done; review requested.",
                   task_id=task.id, thread_id=msg.thread_id)

        elif kind == "HUMAN_APPROVAL_REQUIRED" and task:
            db.add(Approval(task_id=task.id, requested_by=sender))
            record_event(db, task, "approval_requested", sender, {"action": getattr(card, "action", "")})

    except TransitionError as e:
        record_event(db, task, "transition_refused", COORDINATOR_NAME, {"error": str(e)}) if task else None
        _send_card(db, project.id, {
            "type": "STATUS_UPDATE", "from": COORDINATOR_NAME, "to": sender,
            "task_id": card.task_key, "message": f"Refused: {e}",
        }, to_agent=sender, human_line=f"⚠️ {e}", task_id=task.id if task else None,
           thread_id=msg.thread_id)


# ---------------------------------------------------------------- approvals
def decide_approval(db: Session, approval: Approval, approve: bool, decided_by: str, reason: str) -> Approval:
    if approval.status != ApprovalStatus.pending.value:
        raise TransitionError("approval already decided")
    approval.status = (ApprovalStatus.approved if approve else ApprovalStatus.rejected).value
    approval.approved_by = decided_by
    approval.decision_reason = reason
    approval.decided_at = datetime.now(timezone.utc)
    db.flush()  # the completion guard below queries this row (autoflush is off)
    task = db.get(Task, approval.task_id)
    if task:
        record_event(db, task, f"approval_{approval.status}", decided_by, {"reason": reason})
        project = db.get(Project, task.project_id)
        if approve and task.status == TaskStatus.waiting_approval.value:
            transition(db, task, TaskStatus.completed, decided_by, "human approved")
            task.completion_summary = task.completion_summary or f"Approved by {decided_by}. {reason}".strip()
            if project:
                dispatch_ready_tasks(db, project)
        elif not approve and task.status == TaskStatus.waiting_approval.value:
            transition(db, task, TaskStatus.in_progress, decided_by, f"rejected: {reason}")
            owner = task.assigned_agent.name if task.assigned_agent else None
            if project and owner:
                _send_card(db, project.id, {
                    "type": "REVIEW_FEEDBACK", "from": COORDINATOR_NAME, "to": owner,
                    "task_id": task.key, "approved": False, "findings": [reason],
                    "message": f"Human rejected the change: {reason}",
                }, to_agent=owner, human_line=f"🙅 {task.key} rejected by {decided_by}: {reason}",
                   task_id=task.id)
    return approval
