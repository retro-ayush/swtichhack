import pytest

from app.engine.graph import CycleError, assert_acyclic, ready_tasks


def test_self_dependency_rejected():
    with pytest.raises(CycleError):
        assert_acyclic([(1, 1)])


def test_two_cycle_rejected():
    with pytest.raises(CycleError):
        assert_acyclic([(1, 2), (2, 1)])


def test_long_cycle_rejected():
    with pytest.raises(CycleError):
        assert_acyclic([(1, 2), (2, 3), (3, 4), (4, 2)])


def test_dag_accepted():
    assert_acyclic([(2, 1), (3, 2), (4, 2), (4, 3)])


def test_ready_tasks():
    edges = [(2, 1), (3, 2), (4, 2), (4, 3)]
    assert ready_tasks([1, 2, 3, 4], edges, completed=set()) == [1]
    assert ready_tasks([2, 3, 4], edges, completed={1}) == [2]
    assert ready_tasks([3, 4], edges, completed={1, 2}) == [3]
    assert ready_tasks([4], edges, completed={1, 2, 3}) == [4]
