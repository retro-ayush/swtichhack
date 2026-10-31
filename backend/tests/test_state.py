import pytest

from app.engine.state import TransitionError, transition
from app.models import Approval, ApprovalStatus, ExecutionRun, Project, Task, TaskDependency, TaskStatus

S = TaskStatus


@pytest.fixture()
def project(db):
    p = Project(name="state-tests")
    db.add(p)
    db.commit()
    return p


def _task(db, project, **kw):
    t = Task(project_id=project.id, title=kw.pop("title", "t"), **kw)
    db.add(t)
    db.commit()
    return t


def test_illegal_jump_rejected(db, project):
    t = _task(db, project)
    with pytest.raises(TransitionError):
        transition(db, t, S.completed, "test")
    with pytest.raises(TransitionError):
        transition(db, t, S.in_progress, "test")  # backlog -> in_progress not allowed


def test_dependency_gates_start_and_completion(db, project):
    t1 = _task(db, project, title="dep", status=S.ready.value)
    t2 = _task(db, project, title="main", status=S.ready.value)
    db.add(TaskDependency(task_id=t2.id, depends_on_task_id=t1.id))
    db.commit()

    with pytest.raises(TransitionError):
        transition(db, t2, S.in_progress, "test")

    transition(db, t1, S.in_progress, "test")
    transition(db, t1, S.in_review, "test")
    transition(db, t1, S.completed, "test")
    db.commit()

    transition(db, t2, S.in_progress, "test")  # now allowed
    assert t2.status == S.in_progress.value


def test_completion_promotes_backlog_dependents(db, project):
    t1 = _task(db, project, status=S.ready.value)
    t2 = _task(db, project, status=S.backlog.value)
    db.add(TaskDependency(task_id=t2.id, depends_on_task_id=t1.id))
    db.commit()
    transition(db, t1, S.in_progress, "test")
    transition(db, t1, S.in_review, "test")
    transition(db, t1, S.completed, "test")
    db.commit()
    db.refresh(t2)
    assert t2.status == S.ready.value


def test_test_task_requires_passing_run(db, project):
    t = _task(db, project, kind="test", status=S.in_review.value)
    with pytest.raises(TransitionError):
        transition(db, t, S.completed, "test")
    db.add(ExecutionRun(task_id=t.id, status="failed"))
    db.commit()
    with pytest.raises(TransitionError):
        transition(db, t, S.completed, "test")
    db.add(ExecutionRun(task_id=t.id, status="passed"))
    db.commit()
    transition(db, t, S.completed, "test")
    assert t.status == S.completed.value


def test_approval_required_blocks_completion(db, project):
    t = _task(db, project, requires_approval=True, status=S.waiting_approval.value)
    with pytest.raises(TransitionError):
        transition(db, t, S.completed, "test")
    db.add(Approval(task_id=t.id, requested_by="x", status=ApprovalStatus.approved.value))
    db.commit()
    transition(db, t, S.completed, "test")
    assert t.status == S.completed.value


def test_terminal_states_frozen(db, project):
    t = _task(db, project, status=S.completed.value)
    with pytest.raises(TransitionError):
        transition(db, t, S.in_progress, "test")
