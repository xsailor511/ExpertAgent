from __future__ import annotations

import random
import time
from typing import Any

from coding_agent.teams.bus import MessageBus

REQUEST_TTL = 300  # 5 minutes


def _new_request_id() -> str:
    return f"req_{int(time.time() * 1000)}_{random.randint(0, 9999):04d}"


class ProtocolState:
    """Manages pending requests and matches responses."""

    def __init__(self, agent_id: str, bus: MessageBus) -> None:
        self.agent_id = agent_id
        self.bus = bus
        self._pending: dict[str, dict[str, Any]] = {}

    # --- Request API ---

    def request_plan_approval(self, recipient: str, plan_summary: str) -> str:
        """Send a plan-approval request and return the request_id."""
        req_id = _new_request_id()
        msg = {
            "protocol": "plan_approval",
            "from": self.agent_id,
            "request_id": req_id,
            "plan_summary": plan_summary,
            "ts": time.time(),
        }
        self._pending[req_id] = {"recipient": recipient, "msg": msg, "ts": time.time()}
        self.bus.send(recipient, msg)
        return req_id

    def request_shutdown(self, recipient: str, reason: str = "completed") -> str:
        """Send a shutdown request and return the request_id."""
        req_id = _new_request_id()
        msg = {
            "protocol": "shutdown",
            "from": self.agent_id,
            "request_id": req_id,
            "reason": reason,
            "ts": time.time(),
        }
        self._pending[req_id] = {"recipient": recipient, "msg": msg, "ts": time.time()}
        self.bus.send(recipient, msg)
        return req_id

    # --- Response API ---

    def approve(self, request_id: str, to: str = "") -> None:
        """Send approval response.

        If ``to`` is provided, sends directly. Otherwise looks up the
        recipient from the pending outgoing request table (for the agent
        that originally sent the request).
        """
        if to:
            self.bus.send(
                to,
                {
                    "protocol": "plan_approval_response",
                    "to": to,
                    "request_id": request_id,
                    "approved": True,
                    "ts": time.time(),
                },
            )
            return
        pending = self._pending.get(request_id)
        if not pending:
            return
        self.bus.send(
            pending["recipient"],
            {
                "protocol": "plan_approval_response",
                "to": pending["recipient"],
                "request_id": request_id,
                "approved": True,
                "ts": time.time(),
            },
        )
        del self._pending[request_id]

    def reject(self, request_id: str, to: str = "", reason: str = "") -> None:
        """Send rejection response."""
        if to:
            self.bus.send(
                to,
                {
                    "protocol": "plan_approval_response",
                    "to": to,
                    "request_id": request_id,
                    "approved": False,
                    "reason": reason,
                    "ts": time.time(),
                },
            )
            return
        pending = self._pending.get(request_id)
        if not pending:
            return
        self.bus.send(
            pending["recipient"],
            {
                "protocol": "plan_approval_response",
                "to": pending["recipient"],
                "request_id": request_id,
                "approved": False,
                "reason": reason,
                "ts": time.time(),
            },
        )
        del self._pending[request_id]

    # --- Inbox Processing ---

    def consume_inbox(self) -> list[dict[str, Any]]:
        """Read and route incoming messages. Returns actionable items."""
        messages = self.bus.read(self.agent_id)
        actions: list[dict[str, Any]] = []
        for msg in messages:
            protocol = msg.get("protocol", "")
            if protocol == "plan_approval":
                actions.append({
                    "type": "plan_approval_request",
                    "from": msg["from"],
                    "request_id": msg["request_id"],
                    "plan_summary": msg["plan_summary"],
                })
            elif protocol == "shutdown":
                actions.append({
                    "type": "shutdown_request",
                    "from": msg["from"],
                    "request_id": msg["request_id"],
                    "reason": msg.get("reason", ""),
                })
            elif protocol == "plan_approval_response":
                self._handle_response(msg)
                actions.append({
                    "type": "plan_approval_response",
                    "request_id": msg.get("request_id", ""),
                    "approved": msg.get("approved", False),
                    "reason": msg.get("reason", ""),
                })
        return actions

    def _handle_response(self, msg: dict[str, Any]) -> None:
        req_id = msg.get("request_id", "")
        if req_id in self._pending:
            del self._pending[req_id]
