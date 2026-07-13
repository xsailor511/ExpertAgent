from __future__ import annotations

import random
import time
from typing import Any

from coding_agent.teams.bus import MessageBus


class TeamCoordinator:
    """Central coordinator for multi-agent protocol state and teammate registry."""

    def __init__(self, bus: MessageBus, memory: Any = None) -> None:
        self.bus = bus
        self._pending_requests: dict[str, dict[str, Any]] = {}
        self._active_teammates: dict[str, bool] = {}
        # 已派生但结果尚未被主队友收取的队友 (解决"快速完成"竞态)
        self._pending_result_teammates: set[str] = set()
        self._memory = memory

    # --- Request API ---

    def send_shutdown_request(self, teammate: str, reason: str = "") -> str:
        req_id = self._new_request_id()
        msg = {
            "type": "shutdown_request",
            "from": "lead",
            "request_id": req_id,
            "reason": reason,
            "ts": time.time(),
        }
        self._pending_requests[req_id] = {
            "type": "shutdown",
            "sender": "lead",
            "target": teammate,
        }
        self.bus.send(teammate, msg)
        return req_id

    def send_plan_request(self, teammate: str, task: str) -> None:
        msg = {"type": "message", "from": "lead", "content": f"Submit plan for: {task}"}
        self.bus.send(teammate, msg)

    def send_plan_response(self, request_id: str, approve: bool, feedback: str = "") -> str | None:
        pending = self._pending_requests.get(request_id)
        if not pending:
            return None
        is_plan = pending.get("type") == "plan_approval"
        target = pending.get("sender") if is_plan else pending.get("target")
        if not target:
            return None
        self.bus.send(target, {
            "type": "plan_approval_response",
            "from": "lead",
            "request_id": request_id,
            "approve": approve,
            "content": feedback or ("Approved" if approve else "Rejected"),
        })
        del self._pending_requests[request_id]
        return request_id

    def register_pending_plan(self, request_id: str, sender: str, plan_summary: str) -> None:
        self._pending_requests[request_id] = {
            "type": "plan_approval",
            "sender": sender,
            "target": "lead",
            "plan_summary": plan_summary,
        }

    def consume_lead_inbox(self) -> list[dict[str, Any]]:
        """Read lead's inbox and route protocol messages."""
        msgs = self.bus.read("lead")
        actions = []
        for msg in msgs:
            msg_type = msg.get("type", "message")
            req_id = msg.get("request_id", "")
            if msg_type == "plan_approval_request":
                self.register_pending_plan(
                    req_id, msg.get("from", ""), msg.get("content", ""))
                actions.append(msg)
            elif msg_type == "plan_approval_response":
                self._match_response(req_id, msg.get("approve", False))
                actions.append(msg)
            elif msg_type in ("shutdown_response", "result"):
                if msg_type == "result":
                    self._pending_result_teammates.discard(msg.get("from", ""))
                actions.append(msg)
            else:
                actions.append(msg)
        return actions

    def get_pending_request(self, request_id: str) -> dict[str, Any] | None:
        return self._pending_requests.get(request_id)

    def list_pending_requests(self) -> list[dict[str, Any]]:
        return [
            {"request_id": rid, **data}
            for rid, data in self._pending_requests.items()
        ]

    # --- Teammate registry ---

    def register_teammate(self, name: str) -> None:
        self._active_teammates[name] = True
        self._pending_result_teammates.add(name)
        self._sync_memory()

    def unregister_teammate(self, name: str) -> None:
        self._active_teammates.pop(name, None)
        self._sync_memory()

    def has_pending_results(self) -> bool:
        """是否有已派生队友的结果尚未被主队友收取。"""
        return bool(self._pending_result_teammates)

    def _sync_memory(self) -> None:
        if self._memory is not None:
            self._memory.context["active_teammates"] = self.get_active_teammates()
            self._memory.refresh_system_prompt()

    def get_active_teammates(self) -> list[str]:
        return list(self._active_teammates.keys())

    def is_teammate_active(self, name: str) -> bool:
        return name in self._active_teammates

    # --- Internal ---

    def _new_request_id(self) -> str:
        return f"req_{int(time.time() * 1000)}_{random.randint(0, 9999):04d}"

    def _match_response(self, request_id: str, approve: bool) -> None:
        pending = self._pending_requests.get(request_id)
        if not pending:
            return
        if pending["type"] in ("shutdown", "plan_approval"):
            del self._pending_requests[request_id]
