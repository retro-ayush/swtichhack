"""Guarded task state machine. Every status change goes through transition();
the API and the coordinator are both held to the same rules, so neither can
skip review, dependencies, evidence, or approvals."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import events
from ..models import (
    Approval, ApprovalStatus, ExecutionRun, Task, TaskDependency, TaskEvent, TaskStatus,
)

S = TaskStatus

ALLOWED: dict[TaskStatus, set[TaskStatus]] = {
    S.backlog: {S.ready, S.cancelled},
    S.ready: {S.in_progress, S.blocked, S.backlog, S.cancelled},
    S.in_progress: {S.blocked, S.in_review, S.failed, S.cancelled},
    S.blocked: {S.ready, S.in_progress, S.failed, S.cancelled},
    S.in_review: {S.in_progress, S.waiting_approval, S.completed, S.cancelled},
    S.waiting_approval: {S.completed, S.in_progress, S.cancelled},
    S.failed: {S.ready, S.cancelled},
    S.completed: set(),
    S.cancelled: set(),
}


class TransitionError(ValueError):
    pass


def _dep_ids(db: Session, task_id: int) -> list[int]:
    rows = db.execute(
        select(TaskDependency.depends_on_task_id).where(TaskDependency.task_id == task_id)
    ).scalars().all()
    return list(rows)


def unmet_dependencies(db: Session, task: Task) -> list[int]:
    dep_ids = _dep_ids(db, task.id)
    if not dep_ids:
        return []
    done = db.execute(
        select(Task.id).where(Task.id.in_(dep_ids), Task.status == S.completed.value)
    ).scalars().all()
    return [d for d in dep_ids if d not in set(done)]


def has_passing_run(db: Session, task_id: int) -> bool:
    return db.execute(
        select(ExecutionRun.id).where(
            ExecutionRun.task_id == task_id, ExecutionRun.status == "passed"
        ).limit(1)
    ).scalar() is not None


def approved(db: Session, task_id: int) -> bool:
    return db.execute(
        select(Approval.id).where(
            Approval.task_id == task_id, Approval.status == ApprovalStatus.approved.value
        ).limit(1)
    ).scalar() is not None


def record_event(db: Session, task: Task, event_type: str, actor: str, data: dict | None = None) -> None:
    db.add(TaskEvent(task_id=task.id, event_type=event_type, actor=actor, event_data=data or {}))
    events.publish({
        "kind": "task_event", "task_id": task.id, "task_key": task.key,
        "event_type": event_type, "actor": actor, "data": data or {},
        "project_id": task.project_id,
    })


def transition(db: Session, task: Task, new: TaskStatus, actor: str, reason: str = "") -> Task:
    cur = TaskStatus(task.status)
    if new == cur:
        return task
    if new not in ALLOWED[cur]:
        raise TransitionError(f"{task.key}: illegal transition {cur.value} -> {new.value}")

    if new in (S.in_progress, S.ready):
        unmet = unmet_dependencies(db, task)
        if unmet:
            raise TransitionError(
                f"{task.key}: cannot move to {new.value}, unmet dependencies: "
                f"{', '.join(f'T-{d}' for d in unmet)}"
            )

    if new == S.completed:
        unmet = unmet_dependencies(db, task)
        if unmet:
            raise TransitionError(f"{task.key}: cannot complete with unmet dependencies")
        if task.kind == "test" and not has_passing_run(db, task.id):
            raise TransitionError(
                f"{task.key}: test task cannot complete without a recorded passing execution run"
            )
        if task.requires_approval and not approved(db, task.id):
            raise TransitionError(f"{task.key}: requires an approved human approval first")

    task.status = new.value
    task.updated_at = datetime.now(timezone.utc)
    db.flush()  # session runs autoflush=False; queries below must see this change
    record_event(db, task, f"status:{new.value}", actor, {"from": cur.value, "reason": reason})

    if new == S.completed:
        _promote_dependents(db, task, actor)
    return task


def _promote_dependents(db: Session, completed_task: Task, actor: str) -> None:
    dependents = db.execute(
        select(Task).join(TaskDependency, TaskDependency.task_id == Task.id).where(
            TaskDependency.depends_on_task_id == completed_task.id,
            Task.status == S.backlog.value,
        )
    ).scalars().all()
    for t in dependents:
        if not unmet_dependencies(db, t):
            t.status = S.ready.value
            record_event(db, t, "status:ready", actor, {"unlocked_by": completed_task.key})
