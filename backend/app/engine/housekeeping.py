"""Time-based guards. The message/attempt budgets in the coordinator catch
chatty failures; this catches silent ones: a task nobody has touched for
STALE_TASK_MINUTES is blocked and escalated to humans, and an agent that has
not been heard from for AGENT_OFFLINE_MINUTES is shown offline (never green
on hope). Pure function + a thin runner so it is unit-testable."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import Agent, AgentStatus, Project, Task, TaskEvent, TaskStatus
from . import coordinator
from .state import TransitionError, transition

log = logging.getLogger(__name__)

ACTIVE = (TaskStatus.in_progress.value, TaskStatus.in_review.value)


def _aware(dt: datetime | None) -> datetime | None:
    # SQLite hands back naive datetimes; treat them as UTC.
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def sweep(db: Session, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(minutes=settings.stale_task_minutes)
    offline_cutoff = now - timedelta(minutes=settings.agent_offline_minutes)
    stalled = offline = 0

    for t in db.execute(select(Task).where(Task.status.in_(ACTIVE))).scalars().all():
        last = _aware(db.execute(
            select(func.max(TaskEvent.created_at)).where(TaskEvent.task_id == t.id)
        ).scalar()) or _aware(t.updated_at)
        if last is None or last >= stale_cutoff:
            continue
        try:
            transition(db, t, TaskStatus.blocked, coordinator.COORDINATOR_NAME,
                       f"no activity for {settings.stale_task_minutes} min (stalled)")
        except TransitionError as e:
            log.warning("stale sweep could not block %s: %s", t.key, e)
            continue
        stalled += 1
        owner = t.assigned_agent.name if t.assigned_agent else "(unassigned)"
        coordinator._send_card(db, t.project_id, {
            "type": "HUMAN_APPROVAL_REQUIRED", "from": coordinator.COORDINATOR_NAME,
            "task_id": t.key, "action": "unblock, reassign or cancel",
            "message": f"{t.key} ({owner}) had no activity for {settings.stale_task_minutes} minutes.",
        }, to_agent=None, human_line=f"⏱️ {t.key} stalled ({owner}); blocked pending human action.",
           task_id=t.id)

    for a in db.execute(select(Agent).where(
        Agent.status != AgentStatus.offline.value, Agent.role != "coordinator",
    )).scalars().all():
        seen = _aware(a.last_seen_at)
        if seen is None or seen < offline_cutoff:
            a.status = AgentStatus.offline.value
            offline += 1
            coordinator.events.publish({"kind": "agent", "project_id": a.project_id,
                                        "name": a.name, "status": a.status})
    return {"stalled": stalled, "offline": offline}


def run_sweep() -> dict[str, int]:
    db = SessionLocal()
    try:
        result = sweep(db)
        db.commit()
        if any(result.values()):
            log.info("housekeeping: %s", result)
        return result
    except Exception:
        db.rollback()
        log.exception("housekeeping sweep failed")
        return {"stalled": 0, "offline": 0}
    finally:
        db.close()


def mark_coordinator(db: Session, online: bool) -> None:
    """The coordinator *is* this backend: online while the process runs."""
    status = AgentStatus.idle.value if online else AgentStatus.offline.value
    for a in db.execute(select(Agent).where(Agent.role == "coordinator")).scalars().all():
        a.status = status
        a.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    # keep Project import used for type clarity of callers
    _ = Project
