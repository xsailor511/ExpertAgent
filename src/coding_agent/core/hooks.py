from __future__ import annotations

import enum
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from coding_agent.permissions.policy import PermissionPolicy

HookCallback = Callable[..., str | None]


class HookEvent(enum.StrEnum):
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    STOP = "stop"


class HookRegistry:
    def __init__(self) -> None:
        self._hooks: dict[HookEvent, list[HookCallback]] = {
            event: [] for event in HookEvent
        }

    def register(self, event: HookEvent, callback: HookCallback) -> None:
        self._hooks[event].append(callback)

    async def trigger(
        self, event: HookEvent, *args: Any, **kwargs: Any
    ) -> str | None:
        for cb in self._hooks[event]:
            result = cb(*args, **kwargs)
            if inspect.iscoroutine(result):
                result = await result
            if result is not None:
                return result
        return None


DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if="]
DESTRUCTIVE = ["rm ", "> /etc/", "chmod 777"]


def build_permission_hook(
    permissions: PermissionPolicy,
) -> HookCallback:
    from coding_agent.utils.security import safe_resolve

    async def hook(
        block_name: str, block_input: dict[str, Any]
    ) -> str | None:
        if block_name in ("write_file", "edit_file"):
            path = block_input.get("path", "")
            try:
                safe_resolve(Path.cwd(), path)
            except Exception as e:
                return f"Permission denied: {e}"
        if block_name == "bash":
            command = block_input.get("command", "")
            for pattern in DENY_LIST:
                if pattern in command:
                    return f"Permission denied: '{pattern}' is on the deny list"
            if any(token in command for token in DESTRUCTIVE) and not await permissions.check(
                block_name, block_input, "bash"
            ):
                return "Permission denied by user"
        return None

    return hook


def build_log_hook(logger: Any) -> HookCallback:
    def hook(block_name: str, **kwargs: Any) -> str | None:
        logger.debug(f"[hook] {block_name}")
        return None

    return hook
