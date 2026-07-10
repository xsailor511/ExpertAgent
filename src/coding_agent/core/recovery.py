from __future__ import annotations

import asyncio
import random
from collections.abc import Callable
from typing import Any

MAX_RETRIES = 3
MAX_CONSECUTIVE_529 = 2
BASE_DELAY_MS = 500


class RecoveryState:
    def __init__(self, primary: str, fallback: str | None = None):
        self.has_escalated = False
        self.recovery_count = 0
        self.consecutive_529 = 0
        self.has_attempted_reactive_compact = False
        self.current_model = primary
        self.primary = primary
        self.fallback = fallback


def retry_delay(attempt: int) -> float:
    base = min(BASE_DELAY_MS * (2**attempt), 32_000) / 1000
    return base + random.uniform(0, base * 0.25)


def is_rate_limit(e: Exception) -> bool:
    name = type(e).__name__.lower()
    msg = str(e).lower()
    return "ratelimit" in name or "ratelimit" in msg or "429" in msg


def is_overloaded(e: Exception) -> bool:
    name = type(e).__name__.lower()
    msg = str(e).lower()
    return "overloaded" in name or "529" in msg or "overloaded" in msg


def is_prompt_too_long(e: Exception) -> bool:
    msg = str(e).lower()
    return (("prompt" in msg and "long" in msg)
            or "context_length_exceeded" in msg
            or "max_context_window" in msg)


async def with_retry(
    fn: Callable[[], Any],
    state: RecoveryState,
    max_retries: int = MAX_RETRIES,
) -> Any:
    for attempt in range(max_retries):
        try:
            result = await fn()
            state.consecutive_529 = 0
            return result
        except Exception as e:
            if is_rate_limit(e):
                await asyncio.sleep(retry_delay(attempt))
                continue
            if is_overloaded(e):
                state.consecutive_529 += 1
                if state.consecutive_529 >= MAX_CONSECUTIVE_529 and state.fallback:
                    state.current_model = state.fallback
                    state.consecutive_529 = 0
                await asyncio.sleep(retry_delay(attempt))
                continue
            raise
    raise RuntimeError(f"Max retries ({max_retries}) exceeded")
