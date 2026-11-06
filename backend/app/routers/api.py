from __future__ import annotations

import asyncio
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import events
from ..config import settings
from ..db import get_db
from ..engine import commands, coordinator
from ..engine.state import TransitionError, record_event, transition
from ..models import (
    Agent, AgentStatus, Approval, ApprovalStatus, ExecutionRun, Message, Project,
    Task, TaskDependency, TaskEvent, TaskStatus,
)
from ..schemas import (
    AgentOut, ApprovalDecision, ApprovalOut, ChatIn, EventOut, MessageOut, Metrics,
    ProjectCreate, ProjectOut, RunOut, TaskCreate, TaskOut, TaskPatch,
)
from ..switchbridge import adapter as switch

def require_token(authorization: str = Header(default="")) -> None:
    """When TEAMPILOT_API_TOKEN is set, every /api route needs it. The
    dashboard's server-side proxy adds it; browsers never see it."""
    if settings.api_token and not hmac.compare_digest(
        authorization.encode(), f"Bearer {settings.api_token}".encode()
    ):
        raise HTTPException(401, "missing or invalid bearer token")


router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


def _project(db: Session, project_id: int) -> Project:
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(404, "project not found")
    return p


def _task(db: Session, task_id: int) -> Task:
    t = db.get(Task, task_id)
    if t is None:
        raise HTTPException(404, "task not found")
    return t


def _task_out(db: Session, t: Task) -> TaskOut:
    deps = db.execute(
        select(TaskDependency.depends_on_task_id).where(TaskDependency.task_id == t.id)
    ).scalars().all()
    out = TaskOut.model_validate(t)
    out.depends_on = list(deps)
    return out


# ------------------------------------------------------------------- projects
@router.post("/projects", response_model=ProjectOut, dependencies=[Depends(require_token)])
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    p = Project(name=body.name, description=body.description, repository_url=body.repository_url)
    db.add(p)
    db.commit()
    return p


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.execute(select(Project).order_by(Project.id)).scalars().all()


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    return _project(db, project_id)


# ---------------------------------------------------------------------- tasks
@router.post("/projects/{project_id}/tasks", response_model=TaskOut, dependencies=[Depends(require_token)])
def create_task(project_id: int, body: TaskCreate, db: Session = Depends(get_db)):
    from ..engine.graph import CycleError, assert_acyclic

    p = _project(db, project_id)
    agent = coordinator.pick_agent(db, p.id, body.assigned_role) if body.assigned_role else None
    t = Task(project_id=p.id, title=body.title, description=body.description,
             kind=body.kind, priority=body.priority, requires_approval=body.requires_approval,
             assigned_agent_id=agent.id if agent else None, created_by="api")
    db.add(t)
    db.flush()
    edges = [(t.id, dep) for dep in body.depends_on]
    existing = db.execute(select(TaskDependency.task_id, TaskDependency.depends_on_task_id)).all()
    try:
        assert_acyclic([*existing, *edges])
    except CycleError as e:
        db.rollback()
        raise HTTPException(422, str(e))
    for dep in body.depends_on:
        if db.get(Task, dep) is None:
            db.rollback()
            raise HTTPException(422, f"dependency T-{dep} does not exist")
        db.add(TaskDependency(task_id=t.id, depends_on_task_id=dep))
    record_event(db, t, "created", "api", {})
    if not body.depends_on:
        transition(db, t, TaskStatus.ready, "api", "no dependencies")
    db.commit()
    return _task_out(db, t)


@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
def list_tasks(project_id: int, db: Session = Depends(get_db)):
    tasks = db.execute(
        select(Task).where(Task.project_id == project_id).order_by(Task.id)
    ).scalars().all()
    return [_task_out(db, t) for t in tasks]


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)):
    return _task_out(db, _task(db, task_id))


@router.patch("/tasks/{task_id}", response_model=TaskOut, dependencies=[Depends(require_token)])
def patch_task(task_id: int, body: TaskPatch, db: Session = Depends(get_db)):
    t = _task(db, task_id)
    if body.priority:
        t.priority = body.priority
        record_event(db, t, "priority_changed", body.actor, {"priority": body.priority})
    if body.assigned_agent_id is not None:
        agent = db.get(Agent, body.assigned_agent_id)
        if agent is None or agent.project_id != t.project_id:
            raise HTTPException(422, "agent not found in this project")
        t.assigned_agent_id = agent.id
        record_event(db, t, "reassigned", body.actor, {"to": agent.name})
    if body.status:
        try:
            transition(db, t, TaskStatus(body.status), body.actor, body.reason)
        except ValueError as e:  # includes TransitionError
            raise HTTPException(409, str(e))
    db.commit()
    return _task_out(db, t)


@router.post("/tasks/{task_id}/cancel", response_model=TaskOut, dependencies=[Depends(require_token)])
def cancel_task(task_id: int, db: Session = Depends(get_db)):
    t = _task(db, task_id)
    try:
        transition(db, t, TaskStatus.cancelled, "human", "cancelled via API")
    except TransitionError as e:
        raise HTTPException(409, str(e))
    db.commit()
    return _task_out(db, t)


@router.get("/tasks/{task_id}/events", response_model=list[EventOut])
def task_events(task_id: int, db: Session = Depends(get_db)):
    return db.execute(
        select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.id)
    ).scalars().all()


@router.get("/tasks/{task_id}/runs", response_model=list[RunOut])
def task_runs(task_id: int, db: Session = Depends(get_db)):
    return db.execute(
        select(ExecutionRun).where(ExecutionRun.task_id == task_id).order_by(ExecutionRun.id)
    ).scalars().all()


# ----------------------------------------------------------------------- chat
@router.post("/projects/{project_id}/chat", response_model=list[TaskOut], dependencies=[Depends(require_token)])
def chat(project_id: int, body: ChatIn, db: Session = Depends(get_db)):
    """A human message from the dashboard. Mirrored to the Switch room when
    connected; with as_request=True the coordinator decomposes it into tasks."""
    p = _project(db, project_id)
    via = switch.deliver(f"[dashboard] {body.sender_name}: {body.content}", target=None)
    coordinator._persist_message(
        db, p.id, sender_type="human", sender_name=body.sender_name,
        content=body.content, delivered_via=via,
    )
    created: list[Task] = []
    result = commands.execute(db, p, body.content, body.sender_name)
    if result is not None:
        coordinator.reply(db, p.id, result.reply)
    elif body.as_request:
        created = coordinator.handle_user_request(db, p, body.content, body.sender_name)
    db.commit()
    return [_task_out(db, t) for t in created]


@router.get("/projects/{project_id}/messages", response_model=list[MessageOut])
def list_messages(project_id: int, limit: int = 200, db: Session = Depends(get_db)):
    msgs = db.execute(
        select(Message).where(Message.project_id == project_id)
        .order_by(Message.id.desc()).limit(min(limit, 500))
    ).scalars().all()
    return list(reversed(msgs))


# --------------------------------------------------------------------- agents
@router.get("/projects/{project_id}/agents", response_model=list[AgentOut])
def list_agents(project_id: int, db: Session = Depends(get_db)):
    return db.execute(
        select(Agent).where(Agent.project_id == project_id).order_by(Agent.id)
    ).scalars().all()


@router.get("/agents/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: int, db: Session = Depends(get_db)):
    a = db.get(Agent, agent_id)
    if a is None:
        raise HTTPException(404, "agent not found")
    return a


# ------------------------------------------------------------------ approvals
@router.get("/projects/{project_id}/approvals", response_model=list[ApprovalOut])
def list_approvals(project_id: int, db: Session = Depends(get_db)):
    return db.execute(
        select(Approval).join(Task, Task.id == Approval.task_id)
        .where(Task.project_id == project_id).order_by(Approval.id.desc())
    ).scalars().all()


def _decide(db: Session, task_id: int, approve: bool, body: ApprovalDecision) -> Approval:
    approval = db.execute(
        select(Approval).where(
            Approval.task_id == task_id, Approval.status == ApprovalStatus.pending.value
        ).order_by(Approval.id.desc())
    ).scalars().first()
    if approval is None:
        raise HTTPException(404, "no pending approval for this task")
    try:
        coordinator.decide_approval(db, approval, approve, body.decided_by, body.reason)
    except TransitionError as e:
        raise HTTPException(409, str(e))
    db.commit()
    return approval


@router.post("/tasks/{task_id}/approve", response_model=ApprovalOut, dependencies=[Depends(require_token)])
def approve_task(task_id: int, body: ApprovalDecision, db: Session = Depends(get_db)):
    return _decide(db, task_id, True, body)


@router.post("/tasks/{task_id}/reject", response_model=ApprovalOut, dependencies=[Depends(require_token)])
def reject_task(task_id: int, body: ApprovalDecision, db: Session = Depends(get_db)):
    return _decide(db, task_id, False, body)


# -------------------------------------------------- local agent-message inlet
@router.post("/projects/{project_id}/agent-message", dependencies=[Depends(require_token)])
def agent_message(project_id: int, body: ChatIn, db: Session = Depends(get_db)):
    """LOCAL-MODE inlet: lets a locally run agent (or a test) submit a card
    without Switch. Messages arriving this way are recorded delivered_via
    'local' — the UI shows the difference. With Switch connected, agents post
    in the room instead and arrive through the connector."""
    p = _project(db, project_id)
    agent = db.execute(
        select(Agent).where(Agent.project_id == p.id, Agent.name == body.sender_name)
    ).scalars().first()
    if agent is None:
        raise HTTPException(422, f"unknown agent '{body.sender_name}' in this project")
    card = coordinator.extract_card(body.content)
    msg = coordinator._persist_message(
        db, p.id, sender_type="agent", sender_name=body.sender_name,
        content=body.content, message_type=(card.type if card else "CHAT"),
        structured=card.model_dump(by_alias=True) if card else None,
        delivered_via="local",
    )
    error = None
    if card is not None:
        coordinator.handle_card(db, p, card, msg)
    elif error := coordinator.card_error(body.content):
        coordinator.reject_invalid_card(db, p.id, body.sender_name, error)
    db.commit()
    return {"card_recognized": card is not None, "card_type": card.type if card else None,
            "card_error": error}


# ----------------------------------------------------------- activity/metrics
@router.get("/projects/{project_id}/activity", response_model=list[EventOut])
def activity(project_id: int, limit: int = 100, db: Session = Depends(get_db)):
    return db.execute(
        select(TaskEvent).join(Task, Task.id == TaskEvent.task_id)
        .where(Task.project_id == project_id)
        .order_by(TaskEvent.id.desc()).limit(min(limit, 500))
    ).scalars().all()


@router.get("/projects/{project_id}/metrics", response_model=Metrics)
def metrics(project_id: int, db: Session = Depends(get_db)):
    def count(*where) -> int:
        return db.execute(select(func.count(Task.id)).where(Task.project_id == project_id, *where)).scalar_one()

    pending = db.execute(
        select(func.count(Approval.id)).join(Task, Task.id == Approval.task_id).where(
            Task.project_id == project_id, Approval.status == ApprovalStatus.pending.value)
    ).scalar_one()
    active = db.execute(
        select(func.count(Agent.id)).where(
            Agent.project_id == project_id,
            Agent.status.notin_([AgentStatus.offline.value]))
    ).scalar_one()
    return Metrics(
        total_tasks=count(),
        completed=count(Task.status == TaskStatus.completed.value),
        in_progress=count(Task.status.in_([TaskStatus.in_progress.value, TaskStatus.in_review.value])),
        blocked=count(Task.status == TaskStatus.blocked.value),
        pending_approvals=pending,
        active_agents=active,
    )


# -------------------------------------------------------------- switch + SSE
@router.get("/switch/status")
def switch_status():
    return switch.status()


@router.get("/stream")
async def stream():
    q = events.subscribe()

    async def gen():
        try:
            yield "data: {\"kind\": \"hello\"}\n\n"
            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15)
                    yield events.sse_format(evt)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            events.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
