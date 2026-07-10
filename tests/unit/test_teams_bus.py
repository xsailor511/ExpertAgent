from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.teams.bus import MessageBus


@pytest.fixture
def bus(tmp_path: Path) -> MessageBus:
    return MessageBus(mailboxes_dir=tmp_path)


def test_send_and_read(bus: MessageBus):
    bus.send("agent_a", {"type": "hello"})
    msgs = bus.read("agent_a")
    assert len(msgs) == 1
    assert msgs[0]["type"] == "hello"


def test_read_clears_mailbox(bus: MessageBus):
    bus.send("agent_b", {"type": "msg1"})
    bus.send("agent_b", {"type": "msg2"})
    msgs = bus.read("agent_b")
    assert len(msgs) == 2
    assert bus.read("agent_b") == []


def test_read_empty_returns_list(bus: MessageBus):
    assert bus.read("nonexistent") == []


def test_count(bus: MessageBus):
    assert bus.count("agent_c") == 0
    bus.send("agent_c", {"type": "test"})
    assert bus.count("agent_c") == 1


def test_multiple_agents_isolated(bus: MessageBus):
    bus.send("alice", {"to": "alice"})
    bus.send("bob", {"to": "bob"})
    assert len(bus.read("alice")) == 1
    assert len(bus.read("bob")) == 1


def test_send_multiple_messages(bus: MessageBus):
    for i in range(5):
        bus.send("agent_d", {"idx": i})
    assert len(bus.read("agent_d")) == 5
