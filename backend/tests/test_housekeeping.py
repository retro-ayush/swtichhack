from datetime import datetime, timedelta, timezone

from app.engine.housekeeping import mark_coordinator, sweep
from app.models import Agent, AgentStatus, Project, Task, TaskEvent, TaskStatus


def test_stalled_task_is_blocked_and_escalated(db):
    p = Project(name="hk")
    db.add(p)
    db.flush()
    agent = Agent(project_id=p.id, name="hk-backend", role="backend", status=AgentStatus.working.value,
                  last_seen_at=datetime.now(timezone.utc))
    db.add(agent)
    db.flush()
    t = Task(project_id=p.id, title="stuck", status=TaskStatus.in_progress.value, assigned_agent_id=agent.id)
    db.add(t)
    db.flush()
    db.add(TaskEvent(task_id=t.id, event_type="status:in_progress", actor="x",
                     created_at=datetime.now(timezone.utc) - timedelta(minutes=5)))
    db.commit()

    # Nothing is stale yet.
    assert sweep(db)["stalled"] == 0
    assert db.get(Task, t.id).status == TaskStatus.in_progress.value

    # Jump the clock past the stale window: blocked + a human-facing card.
    later = datetime.now(timezone.utc) + timedelta(minutes=60)
    result = sweep(db, now=later)
    db.commit()
    assert result["stalled"] == 1
    assert db.get(Task, t.id).status == TaskStatus.blocked.value
    from app.models import Message
    from sqlalchemy import select
    card = db.execute(select(Message).where(Message.task_id == t.id,
                                            Message.message_type == "HUMAN_APPROVAL_REQUIRED")).scalars().first()
    assert card is not None and "stalled" in card.content

    # Agent silent for an hour -> offline; the coordinator is exempt.
    assert result["offline"] >= 1
    assert db.get(Agent, agent.id).status == AgentStatus.offline.value


def test_quiet_review_nudges_reviewer_then_still_escalates(db):
    from sqlalchemy import select

    from app.models import Message
    p = Project(name="hk-nudge")
    db.add(p)
    db.flush()
    owner = Agent(project_id=p.id, name="n-backend", role="backend")
    reviewer = Agent(project_id=p.id, name="n-reviewer", role="reviewer")
    db.add_all([owner, reviewer])
    db.flush()
    t = Task(project_id=p.id, title="fix", status=TaskStatus.in_review.value, assigned_agent_id=owner.id)
    db.add(t)
    db.flush()
    t0 = datetime.now(timezone.utc)
    db.add(TaskEvent(task_id=t.id, event_type="status:in_review", actor="n-backend", created_at=t0))
    db.commit()

    def nudges():
        return db.execute(select(Message).where(Message.task_id == t.id,
                                                Message.recipient_id == "n-reviewer")).scalars().all()

    assert sweep(db, now=t0 + timedelta(minutes=2))["nudged"] == 0          # still fresh
    assert sweep(db, now=t0 + timedelta(minutes=6))["nudged"] == 1          # quiet -> reviewer pinged
    db.commit()
    assert len(nudges()) == 1 and "waiting for your review" in nudges()[0].content
    # The next sweep a minute later must not nudge again.
    real_now = datetime.now(timezone.utc)
    assert sweep(db, now=real_now + timedelta(minutes=1))["nudged"] == 0
    # Nudges are not activity: after 20 quiet minutes the task still escalates.
    assert sweep(db, now=t0 + timedelta(minutes=25))["stalled"] == 1
    db.commit()
    assert db.get(Task, t.id).status == TaskStatus.blocked.value


def test_coordinator_marked_online(db):
    p = Project(name="hk2")
    db.add(p)
    db.flush()
    c = Agent(project_id=p.id, name="hk2-coord", role="coordinator")
    db.add(c)
    db.commit()
    mark_coordinator(db, online=True)
    assert db.get(Agent, c.id).status == AgentStatus.idle.value
    later = datetime.now(timezone.utc) + timedelta(hours=2)
    sweep(db, now=later)
    assert db.get(Agent, c.id).status == AgentStatus.idle.value  # never swept offline
    mark_coordinator(db, online=False)
    assert db.get(Agent, c.id).status == AgentStatus.offline.value
