from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.tasks.graph import TaskGraph
from coding_agent.tasks.models import Task
from coding_agent.tasks.store import TaskStore


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    return TaskStore(tasks_dir=tmp_path)


@pytest.fixture
def graph(store: TaskStore) -> TaskGraph:
    return TaskGraph(store)


def test_task_creation():
    task = Task(id="test_001", subject="Test task", description="A test")
    assert task.status == "pending"
    assert task.owner is None
    assert task.blocked_by == []


def test_task_new_id():
    task_id = Task.new_id()
    assert task_id.startswith("task_")
    assert len(task_id) >= 16


def test_task_to_dict():
    task = Task(id="t1", subject="test")
    d = task.to_dict()
    assert d["id"] == "t1"
    assert d["subject"] == "test"
    assert "created_at" in d


def test_store_save_and_load(store: TaskStore):
    task = Task(id="t1", subject="hello")
    store.save(task)
    loaded = store.load("t1")
    assert loaded.id == "t1"
    assert loaded.subject == "hello"


def test_store_list_all(store: TaskStore):
    store.save(Task(id="t1", subject="a"))
    store.save(Task(id="t2", subject="b"))
    tasks = store.list_all()
    assert len(tasks) == 2


def test_store_delete(store: TaskStore):
    store.save(Task(id="t1", subject="a"))
    store.delete("t1")
    assert len(store.list_all()) == 0


def test_graph_can_start_no_deps(graph: TaskGraph):
    task = Task(id="t1", subject="no deps")
    assert graph.can_start(task)


def test_graph_can_start_with_blocked_by(store: TaskStore, graph: TaskGraph):
    dep = Task(id="dep1", subject="dependency")
    dep.status = "completed"
    store.save(dep)
    task = Task(id="t1", subject="blocked", blocked_by=["dep1"])
    assert graph.can_start(task)


def test_graph_can_start_blocked_if_dep_incomplete(store: TaskStore, graph: TaskGraph):
    dep = Task(id="dep1", subject="incomplete dep")
    store.save(dep)  # status is "pending"
    task = Task(id="t1", subject="blocked", blocked_by=["dep1"])
    assert not graph.can_start(task)


def test_graph_claimable(store: TaskStore, graph: TaskGraph):
    store.save(Task(id="t1", subject="doable"))
    store.save(Task(id="t2", subject="owned", owner="someone"))
    claimable = graph.claimable()
    assert len(claimable) == 1
    assert claimable[0].id == "t1"


def test_graph_unblocked_by(store: TaskStore, graph: TaskGraph):
    dep = Task(id="dep1", subject="dep")
    store.save(dep)
    store.save(Task(id="t1", subject="waiting", blocked_by=["dep1"]))
    # dep not yet completed
    assert graph.unblocked_by("dep1") == []
    # complete dep
    dep.status = "completed"
    store.save(dep)
    unblocked = graph.unblocked_by("dep1")
    assert "waiting" in unblocked
