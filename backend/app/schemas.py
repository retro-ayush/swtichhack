"""Pydantic schemas: API payloads and the validated agent-message cards."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------- agent cards
# One human-readable line + a fenced JSON card is the wire format in the room.
# Everything below validates the JSON card. Invalid cards are stored as plain
# chat and never acted on.

Role = Literal["coordinator", "frontend", "backend", "testing", "reviewer"]


class _CardBase(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_agent: str = Field(alias="from")
    task_key: str | None = Field(default=None, alias="task_id")  # "T-3"
    message: str = ""


class TaskAssignedCard(_CardBase):
    type: Literal["TASK_ASSIGNED"]
    to: str


class TaskStartedCard(_CardBase):
    type: Literal["TASK_STARTED"]


class StatusUpdateCard(_CardBase):
    type: Literal["STATUS_UPDATE"]


class InformationRequestCard(_CardBase):
    type: Literal["INFORMATION_REQUEST"]
    to: str
    requires_action: bool = True


class BlockerCard(_CardBase):
    type: Literal["BLOCKER"]
    requires_action: bool = True


class HandoffCard(_CardBase):
    type: Literal["HANDOFF"]
    to: str


class ReviewRequestCard(_CardBase):
    type: Literal["REVIEW_REQUEST"]
    diff_ref: str = ""  # branch / commit / PR the reviewer should look at


class ReviewFeedbackCard(_CardBase):
    type: Literal["REVIEW_FEEDBACK"]
    approved: bool
    findings: list[str] = []


class TestResultCard(_CardBase):
    type: Literal["TEST_RESULT"]
    passed: bool
    commands: list[str] = []
    log_excerpt: str = ""


class TaskCompletedCard(_CardBase):
    type: Literal["TASK_COMPLETED"]
    summary: str = ""
    evidence: str = ""


class HumanApprovalCard(_CardBase):
    type: Literal["HUMAN_APPROVAL_REQUIRED"]
    action: str = ""


AgentCard = Annotated[
    Union[
        TaskAssignedCard, TaskStartedCard, StatusUpdateCard, InformationRequestCard,
        BlockerCard, HandoffCard, ReviewRequestCard, ReviewFeedbackCard,
        TestResultCard, TaskCompletedCard, HumanApprovalCard,
    ],
    Field(discriminator="type"),
]


class CardEnvelope(BaseModel):
    card: AgentCard


# ----------------------------------------------------------------- API models
class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    repository_url: str = ""


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str
    repository_url: str
    status: str
    is_demo: bool
    created_at: datetime


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    role: str
    runtime_type: str
    status: str
    last_seen_at: datetime | None


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    kind: str = "feature"
    priority: str = "medium"
    requires_approval: bool = False
    depends_on: list[int] = []
    assigned_role: Role | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    key: str
    title: str
    description: str
    kind: str
    status: str
    priority: str
    requires_approval: bool
    attempts: int
    assigned_agent_id: int | None
    created_by: str
    created_at: datetime
    updated_at: datetime
    completion_summary: str
    depends_on: list[int] = []


class TaskPatch(BaseModel):
    priority: str | None = None
    status: str | None = None  # validated against the state machine
    assigned_agent_id: int | None = None
    reason: str = ""
    actor: str = "human"


class ChatIn(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    sender_name: str = Field(default="human", min_length=1, max_length=120)
    as_request: bool = False  # True = ask the coordinator to decompose into tasks


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    task_id: int | None
    sender_type: str
    sender_name: str
    message_type: str
    content: str
    structured: dict | None
    delivered_via: str
    thread_id: str
    created_at: datetime


class ApprovalDecision(BaseModel):
    decided_by: str = "human"
    reason: str = ""


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    task_id: int
    requested_by: str
    approved_by: str
    status: str
    decision_reason: str
    created_at: datetime
    decided_at: datetime | None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    task_id: int
    event_type: str
    actor: str
    event_data: dict
    created_at: datetime


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    task_id: int
    agent_id: int | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    output_summary: str
    error_summary: str


class Metrics(BaseModel):
    total_tasks: int
    completed: int
    in_progress: int
    blocked: int
    pending_approvals: int
    active_agents: int
