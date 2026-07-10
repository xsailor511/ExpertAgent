from __future__ import annotations

import logging

import pytest

from coding_agent.core.hooks import (
    DENY_LIST,
    DESTRUCTIVE,
    HookEvent,
    HookRegistry,
    build_log_hook,
)


@pytest.fixture
def registry():
    return HookRegistry()


async def test_register_and_trigger_no_block(registry):
    results = []
    registry.register(
        HookEvent.PRE_TOOL_USE, lambda **kw: (results.append(kw), None)[1]
    )
    await registry.trigger(HookEvent.PRE_TOOL_USE, block_name="bash")
    assert len(results) == 1
    assert results[0]["block_name"] == "bash"


async def test_trigger_blocks_on_first_non_none(registry):
    registry.register(HookEvent.PRE_TOOL_USE, lambda **kw: "blocked")
    registry.register(
        HookEvent.PRE_TOOL_USE,
        lambda **kw: (pytest.fail("should not run"), None)[1],
    )
    result = await registry.trigger(HookEvent.PRE_TOOL_USE, block_name="bash")
    assert result == "blocked"


async def test_unregistered_event_returns_none(registry):
    result = await registry.trigger(HookEvent.PRE_TOOL_USE, block_name="bash")
    assert result is None


async def test_user_prompt_submit_event(registry):
    registry.register(HookEvent.USER_PROMPT_SUBMIT, lambda msg: None)
    result = await registry.trigger(
        HookEvent.USER_PROMPT_SUBMIT, msg="hello"
    )
    assert result is None


async def test_multiple_hooks_all_run(registry):
    results = []
    registry.register(
        HookEvent.STOP, lambda: (results.append("a"), None)[1]
    )
    registry.register(
        HookEvent.STOP, lambda: (results.append("b"), None)[1]
    )
    await registry.trigger(HookEvent.STOP)
    assert results == ["a", "b"]


async def test_post_tool_use_event(registry):
    results = []
    registry.register(
        HookEvent.POST_TOOL_USE, lambda **kw: (results.append(kw), None)[1]
    )
    await registry.trigger(
        HookEvent.POST_TOOL_USE, block_name="bash", result="ok"
    )
    assert results[0]["block_name"] == "bash"


def test_hook_event_enum_values():
    assert HookEvent.USER_PROMPT_SUBMIT.value == "user_prompt_submit"
    assert HookEvent.PRE_TOOL_USE.value == "pre_tool_use"
    assert HookEvent.POST_TOOL_USE.value == "post_tool_use"
    assert HookEvent.STOP.value == "stop"


def test_deny_list_blocks_dangerous_commands():
    assert "sudo" in DENY_LIST
    assert "rm -rf /" in DENY_LIST
    assert "shutdown" in DENY_LIST
    assert "reboot" in DENY_LIST
    assert "mkfs" in DENY_LIST
    assert "dd if=" in DENY_LIST


def test_destructive_patterns():
    assert "rm " in DESTRUCTIVE
    assert "> /etc/" in DESTRUCTIVE
    assert "chmod 777" in DESTRUCTIVE


def test_build_log_hook_logs_and_returns_none():
    logger = logging.getLogger("test_hook_logger")
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    hook = build_log_hook(logger)
    result = hook(block_name="bash", block_input={"command": "ls"})

    assert result is None

    logger.removeHandler(handler)


def test_build_log_hook_returns_callable():
    logger = logging.getLogger("test_hook_callable")
    hook = build_log_hook(logger)
    assert callable(hook)
