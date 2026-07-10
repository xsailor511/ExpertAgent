from __future__ import annotations

import pytest

from coding_agent.core.recovery import (
    RecoveryState,
    is_overloaded,
    is_prompt_too_long,
    is_rate_limit,
    retry_delay,
    with_retry,
)


class _TestRateLimitError(Exception):
    pass


class _TestOverloadedError(Exception):
    pass


class _TestOtherError(Exception):
    pass


class _TestPromptTooLongError(Exception):
    pass


def test_retry_delay_increases_with_attempt():
    d1 = retry_delay(0)
    d2 = retry_delay(1)
    d3 = retry_delay(2)
    assert 0 < d1 < d2 < d3


def test_is_rate_limit_matches_429():
    assert is_rate_limit(_TestRateLimitError("ratelimit error"))
    assert not is_rate_limit(_TestOtherError("other error"))


def test_is_overloaded_matches_529():
    assert is_overloaded(_TestOverloadedError("overloaded"))
    assert not is_overloaded(_TestOtherError("other error"))


def test_is_prompt_too_long():
    assert is_prompt_too_long(_TestPromptTooLongError("prompt too long"))
    assert is_prompt_too_long(_TestPromptTooLongError("context_length_exceeded"))
    assert not is_prompt_too_long(_TestOtherError("other error"))


def test_recovery_state_defaults():
    state = RecoveryState(primary="gpt-4", fallback="gpt-3.5")
    assert state.current_model == "gpt-4"
    assert state.fallback == "gpt-3.5"
    assert not state.has_escalated


async def test_with_retry_succeeds_on_first_try():
    state = RecoveryState(primary="gpt-4")
    call_count = 0

    async def fn():
        nonlocal call_count
        call_count += 1
        return "success"

    result = await with_retry(fn, state)
    assert result == "success"
    assert call_count == 1


async def test_with_retry_retries_on_429():
    state = RecoveryState(primary="gpt-4")
    call_count = 0

    async def fn():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise _TestRateLimitError("ratelimit error")
        return "success"

    result = await with_retry(fn, state)
    assert result == "success"


async def test_with_retry_fallback_on_consecutive_529():
    state = RecoveryState(primary="gpt-4", fallback="gpt-3.5")

    async def fn():
        raise _TestOverloadedError("overloaded")

    with pytest.raises(RuntimeError):
        await with_retry(fn, state)


async def test_with_retry_raises_on_non_retryable():
    state = RecoveryState(primary="gpt-4")

    async def fn():
        raise _TestOtherError("non-retryable error")

    with pytest.raises(_TestOtherError):
        await with_retry(fn, state)
