from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TZDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend. SQLite drops the offset,
    so values come back naive; this re-attaches UTC so JSON carries +00:00
    and browsers parse the instant correctly instead of as local time."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class TaskStatus(str, enum.Enum):
    backlog = "backlog"
    ready = "ready"
    in_progress = "in_progress"
    blocked = "blocked"
    in_review = "in_review"
    waiting_approval = "waiting_approval"
    completed = "completed"
    cancelled = "cancelled"
    failed = "failed"


class AgentStatus(str, enum.Enum):
    idle = "idle"
    working = "working"
    waiting = "waiting"
    blocked = "blocked"
    reviewing = "reviewing"
    offline = "offline"


class ApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(40), default="member")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    repository_url: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(40), default="active")
    is_demo: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    agents: Mapped[list["Agent"]] = relationship(back_populates="project")
    tasks: Mapped[list["Task"]] = relationship(back_populates="project")


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(120))  # Switch registered name
    role: Mapped[str] = mapped_column(String(40))  # coordinator|frontend|backend|testing|reviewer
    runtime_type: Mapped[str] = mapped_column(String(40), default="switch_console")
    status: Mapped[str] = mapped_column(String(20), default=AgentStatus.offline.value)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    last_seen_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="agents")


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(30), default="feature")  # feature|investigation|test|review|merge
    assigned_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default=TaskStatus.backlog.value, index=True)
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    requires_approval: Mapped[bool] = mapped_column(default=False)
    attempts: Mapped[int] = mapped_column(default=0)
    agent_message_count: Mapped[int] = mapped_column(default=0)
    created_by: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, onupdate=utcnow)
    completion_summary: Mapped[str] = mapped_column(Text, default="")

    project: Mapped["Project"] = relationship(back_populates="tasks")
    assigned_agent: Mapped["Agent | None"] = relationship()

    @property
    def key(self) -> str:
        return f"T-{self.id}"


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    depends_on_task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), primary_key=True)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    sender_type: Mapped[str] = mapped_column(String(20))  # human|agent|coordinator|system
    sender_id: Mapped[str] = mapped_column(String(200), default="")
    sender_name: Mapped[str] = mapped_column(String(200), default="")
    recipient_id: Mapped[str] = mapped_column(String(200), default="")
    message_type: Mapped[str] = mapped_column(String(40), default="CHAT")
    content: Mapped[str] = mapped_column(Text, default="")
    structured: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # validated card, if any
    delivered_via: Mapped[str] = mapped_column(String(20), default="local")  # switch|local|pending
    switch_message_id: Mapped[str] = mapped_column(String(200), default="")
    thread_id: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)


class TaskEvent(Base):
    __tablename__ = "task_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(60))
    actor: Mapped[str] = mapped_column(String(200), default="system")
    event_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    requested_by: Mapped[str] = mapped_column(String(200))
    approved_by: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default=ApprovalStatus.pending.value)
    decision_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)


class ExecutionRun(Base):
    __tablename__ = "execution_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # passed|failed|error|running
    started_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    output_summary: Mapped[str] = mapped_column(Text, default="")
    error_summary: Mapped[str] = mapped_column(Text, default="")


Index("ix_msg_project_created", Message.project_id, Message.created_at)
