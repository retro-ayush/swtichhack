"""Human control commands typed in the team chat (Switch room or dashboard).

    approve T-5 [reason]     reject T-5 <reason>
    unblock T-3 [reason]     cancel T-3 [reason]
    reassign T-3 <agent>     retry T-3   (failed -> ready)
    status                   help

Anything that is not a command falls through to the coordinator as a new
request. Commands go through the same guarded engine functions as the
dashboard, so chat can never bypass a rule the API enforces."""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Agent, Approval, ApprovalStatus, Project, Task, TaskStatus
from . import coordinator
from .state import TransitionError, record_event, transition

_CMD = re.compile(
    r"^\s*(approve|reject|unblock|cancel|reassign|retry|status|help)\b\s*(T-\d+)?\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)

HELP = (
    "Commands: approve T-n [reason] · reject T-n <reason> · unblock T-n [reason] · "
    "cancel T-n [reason] · reassign T-n <agent-name> · retry T-n · status. "
    "Anything else is treated as a new request and planned into tasks."
)


@dataclass
class CommandResult:
    ok: bool
    reply: str


def parse(text: str) -> tuple[str, str | None, str] | None:
    m = _CMD.match(text)
    if not m:
        return None
    verb, key, rest = m.group(1).lower(), m.group(2), m.group(3).strip()
    if verb not in ("status", "help") and not key:
        return None  # "approve the plan" is prose, not a command
    return verb, key.upper() if key else None, rest


def _status(db: Session, project: Project) -> str:
    tasks = db.execute(select(Task).where(Task.project_id == project.id).order_by(Task.id)).scalars().all()
    if not tasks:
        return "No tasks yet."
    lines = [f"{t.key} · {t.status} · {t.assigned_agent.name if t.assigned_agent else 'unassigned'} · {t.title}"
             for t in tasks if t.status not in ("completed", "cancelled")]
    done = sum(t.status == "completed" for t in tasks)
    return f"{done}/{len(tasks)} done.\n" + ("\n".join(lines) if lines else "Nothing open.")


def execute(db: Session, project: Project, text: str, actor: str) -> CommandResult | None:
    """Returns None when `text` is not a command."""
    parsed = parse(text)
    if parsed is None:
        return None
    verb, key, rest = parsed
    if verb == "help":
        return CommandResult(True, HELP)
    if verb == "status":
        return CommandResult(True, _status(db, project))

    task = coordinator._task_by_key(db, project.id, key)
    if task is None:
        return CommandResult(False, f"{key} not found in this project.")
    try:
        if verb in ("approve", "reject"):
            if verb == "reject" and not rest:
                return CommandResult(False, f"Give a reason: reject {key} <reason>")
            approval = db.execute(
                select(Approval).where(Approval.task_id == task.id,
                                       Approval.status == ApprovalStatus.pending.value)
                .order_by(Approval.id.desc())
            ).scalars().first()
            if approval is None:
                return CommandResult(False, f"{key} has no pending approval (status: {task.status}).")
            coordinator.decide_approval(db, approval, verb == "approve", actor, rest)
            return CommandResult(True, f"{key} {verb}d by {actor}. Now: {task.status}.")
        if verb == "unblock":
            transition(db, task, TaskStatus.in_progress, actor, rest or "unblocked from chat")
            return CommandResult(True, f"{key} unblocked → in_progress.")
        if verb == "cancel":
            transition(db, task, TaskStatus.cancelled, actor, rest or "cancelled from chat")
            return CommandResult(True, f"{key} cancelled.")
        if verb == "retry":
            task.attempts = 0
            task.agent_message_count = 0
            transition(db, task, TaskStatus.ready, actor, "retry from chat")
            coordinator.dispatch_ready_tasks(db, project)
            return CommandResult(True, f"{key} reset to ready and re-dispatched.")
        if verb == "reassign":
            name = rest.lstrip("@").strip()
            agent = db.execute(select(Agent).where(Agent.project_id == project.id, Agent.name == name)).scalars().first()
            if agent is None or agent.role == "coordinator":
                return CommandResult(False, f"No specialist agent named '{name}'.")
            task.assigned_agent_id = agent.id
            record_event(db, task, "reassigned", actor, {"to": agent.name})
            return CommandResult(True, f"{key} reassigned to {agent.name}.")
    except TransitionError as e:
        return CommandResult(False, str(e))
    return None
