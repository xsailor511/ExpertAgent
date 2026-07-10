from __future__ import annotations

from pathlib import Path

from coding_agent.teams.teammate import TEAMMATE_PROMPT, Teammate


def test_teammate_prompt_has_agent_id():
    prompt = TEAMMATE_PROMPT.format(agent_id="test_bot")
    assert "test_bot" in prompt


def test_teammate_init(tmp_path: Path):
    """Test that teammate initializes without error."""
    from coding_agent.tasks.graph import TaskGraph
    from coding_agent.tasks.store import TaskStore
    from coding_agent.teams.bus import MessageBus

    store = TaskStore(tasks_dir=tmp_path)
    graph = TaskGraph(store)
    bus = MessageBus(mailboxes_dir=tmp_path / "mailboxes")

    tm = Teammate(
        agent_id="worker_1",
        llm=None,
        tools=None,
        task_store=store,
        task_graph=graph,
        bus=bus,
        idle_poll_interval=60.0,
    )
    assert tm.agent_id == "worker_1"
    assert not tm._running


def test_teammate_start_stop(tmp_path: Path):
    from coding_agent.tasks.graph import TaskGraph
    from coding_agent.tasks.store import TaskStore
    from coding_agent.teams.bus import MessageBus

    store = TaskStore(tasks_dir=tmp_path)
    graph = TaskGraph(store)
    bus = MessageBus(mailboxes_dir=tmp_path / "mailboxes")

    tm = Teammate(
        agent_id="worker_2",
        llm=None,
        tools=None,
        task_store=store,
        task_graph=graph,
        bus=bus,
        idle_poll_interval=60.0,
    )
    tm.start()
    assert tm._running
    assert tm._thread is not None
    assert tm._thread.is_alive()
    tm.stop()
    assert not tm._running
    tm._thread.join(timeout=2)
    assert not tm._thread.is_alive()


def test_teammate_start_idempotent(tmp_path: Path):
    from coding_agent.tasks.graph import TaskGraph
    from coding_agent.tasks.store import TaskStore
    from coding_agent.teams.bus import MessageBus

    store = TaskStore(tasks_dir=tmp_path)
    graph = TaskGraph(store)
    bus = MessageBus(mailboxes_dir=tmp_path / "mailboxes")

    tm = Teammate(
        agent_id="worker_3",
        llm=None,
        tools=None,
        task_store=store,
        task_graph=graph,
        bus=bus,
        idle_poll_interval=60.0,
    )
    tm.start()
    tm.start()  # should be no-op
    tm.stop()


def test_teammate_shutdown_via_inbox(tmp_path: Path):
    from coding_agent.tasks.graph import TaskGraph
    from coding_agent.tasks.store import TaskStore
    from coding_agent.teams.bus import MessageBus

    store = TaskStore(tasks_dir=tmp_path)
    graph = TaskGraph(store)
    bus = MessageBus(mailboxes_dir=tmp_path / "mailboxes")

    tm = Teammate(
        agent_id="worker_4",
        llm=None,
        tools=None,
        task_store=store,
        task_graph=graph,
        bus=bus,
        idle_poll_interval=0.1,
    )
    tm.start()

    bus.send("worker_4", {
        "protocol": "shutdown",
        "from": "leader",
        "request_id": "req1",
        "reason": "all done",
        "ts": __import__("time").time(),
    })

    import time
    time.sleep(0.5)
    assert not tm._running


def test_teammate_claims_available_task(tmp_path: Path):
    from coding_agent.tasks.graph import TaskGraph
    from coding_agent.tasks.models import Task
    from coding_agent.tasks.store import TaskStore
    from coding_agent.teams.bus import MessageBus

    store = TaskStore(tasks_dir=tmp_path)
    graph = TaskGraph(store)
    bus = MessageBus(mailboxes_dir=tmp_path / "mailboxes")

    store.save(Task(id="t1", subject="Do something"))

    tm = Teammate(
        agent_id="worker_5",
        llm=None,
        tools=None,
        task_store=store,
        task_graph=graph,
        bus=bus,
        idle_poll_interval=0.1,
    )

    tm._try_claim_task()
    task = store.load("t1")
    assert task.owner == "worker_5"
