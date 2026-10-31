"""Seed the clearly-labeled demo workspace: one project, five agents.
Agent statuses start offline — nothing is shown as active until something
real happens."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Agent, Project


ROLES = [
    ("teampilot-coordinator", "coordinator", "teampilot_backend"),
    ("teampilot-frontend", "frontend", "switch_console"),
    ("teampilot-backend", "backend", "switch_console"),
    ("teampilot-testing", "testing", "switch_console"),
    ("teampilot-reviewer", "reviewer", "switch_console"),
]


def seed(db: Session) -> None:
    if db.execute(select(Project.id).limit(1)).scalar() is not None:
        return
    p = Project(
        name="TeamPilot Demo",
        description="Demo workspace (seeded). Real execution results are labeled by their source.",
        is_demo=True,
    )
    db.add(p)
    db.flush()
    for name, role, runtime in ROLES:
        db.add(Agent(project_id=p.id, name=name, role=role, runtime_type=runtime))
    db.commit()
