from __future__ import annotations

from pathlib import Path

import pytest

from coding_agent.teams.bus import MessageBus
from coding_agent.teams.protocol import ProtocolState


@pytest.fixture
def alice(tmp_path: Path) -> ProtocolState:
    bus = MessageBus(mailboxes_dir=tmp_path)
    return ProtocolState("alice", bus)


@pytest.fixture
def bob(tmp_path: Path) -> ProtocolState:
    bus = MessageBus(mailboxes_dir=tmp_path)
    return ProtocolState("bob", bus)


def test_request_plan_approval(alice: ProtocolState, bob: ProtocolState):
    req_id = alice.request_plan_approval("bob", "Refactor auth module")
    actions = bob.consume_inbox()
    assert len(actions) == 1
    assert actions[0]["type"] == "plan_approval_request"
    assert actions[0]["plan_summary"] == "Refactor auth module"
    assert actions[0]["request_id"] == req_id


def test_approve_response(alice: ProtocolState, bob: ProtocolState):
    req_id = alice.request_plan_approval("bob", "Add tests")
    actions = bob.consume_inbox()
    assert len(actions) == 1
    bob.approve(req_id, to=actions[0]["from"])
    actions = alice.consume_inbox()
    assert len(actions) == 1  # response is routed back


def test_shutdown_request(alice: ProtocolState, bob: ProtocolState):
    alice.request_shutdown("bob", "all done")
    actions = bob.consume_inbox()
    assert len(actions) == 1
    assert actions[0]["type"] == "shutdown_request"
    assert actions[0]["reason"] == "all done"


def test_consume_empty_inbox(alice: ProtocolState):
    assert alice.consume_inbox() == []
