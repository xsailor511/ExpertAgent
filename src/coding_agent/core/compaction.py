from __future__ import annotations

import json
import time
from pathlib import Path

from coding_agent.llm.base import LLMProvider, Message

TOOL_RESULTS_DIR = Path(".task_outputs") / "tool-results"
PERSIST_THRESHOLD = 30_000
KEEP_RECENT_TOOL_RESULTS = 3


def persist_large_output(tool_use_id: str, output: str) -> str:
    if len(output) <= PERSIST_THRESHOLD:
        return output
    TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = TOOL_RESULTS_DIR / f"{tool_use_id}.txt"
    path.write_text(output, encoding="utf-8")
    return (
        f"<persisted-output>\nFull output: {path}\nPreview:\n{output[:2000]}\n</persisted-output>"
    )


def snip_compact(messages: list[Message], max_messages: int = 50) -> list[Message]:
    if len(messages) <= max_messages:
        return messages
    head_end, tail_start = 3, len(messages) - (max_messages - 4)
    if head_end > 0 and messages[head_end - 1].role == "assistant":
        tc = messages[head_end - 1].tool_calls
        if tc:
            while head_end < len(messages) and messages[head_end].role == "tool":
                head_end += 1
    if (
        tail_start > 0
        and tail_start < len(messages)
        and messages[tail_start].role == "tool"
        and messages[tail_start - 1].role == "assistant"
    ):
        tail_start -= 1
    if head_end >= tail_start:
        return messages
    snipped = tail_start - head_end
    result = messages[:head_end]
    result.append(Message(role="user", content=f"[snipped {snipped} messages]"))
    result.extend(messages[tail_start:])
    return result


def micro_compact(messages: list[Message]) -> list[Message]:
    tool_msgs = [(i, m) for i, m in enumerate(messages) if m.role == "tool"]
    if len(tool_msgs) <= KEEP_RECENT_TOOL_RESULTS:
        return messages
    for _idx, msg in tool_msgs[:-KEEP_RECENT_TOOL_RESULTS]:
        if len(msg.content) > 120:
            msg.content = "[Earlier tool result compacted. Re-run if needed.]"
    return messages


def estimate_size(messages: list[Message]) -> int:
    return len(json.dumps([m.to_dict() for m in messages], default=str))


def write_transcript(messages: list[Message], transcript_dir: Path | None = None) -> Path:
    d = transcript_dir or Path(".transcripts")
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"transcript_{int(time.time())}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg.to_dict(), default=str) + "\n")
    return path


async def summary_compact(
    messages: list[Message],
    llm: LLMProvider,
    transcript_dir: Path | None = None,
) -> list[Message]:
    write_transcript(messages, transcript_dir)
    conversation = json.dumps([m.to_dict() for m in messages], default=str)[:80_000]
    prompt = (
        "Summarize this coding-agent conversation so work can continue. "
        "Preserve: current goal, key findings, changed files, remaining work, "
        "user constraints.\n\n" + conversation
    )
    response = await llm.chat(messages=[Message(role="user", content=prompt)])
    summary = response.content or "(empty summary)"
    return [Message(role="user", content=f"[Compacted]\n\n{summary}")]


def reactive_compact(
    messages: list[Message],
    transcript_dir: Path | None = None,
) -> list[Message]:
    write_transcript(messages, transcript_dir)
    tail_start = max(0, len(messages) - 5)
    if (
        tail_start > 0
        and tail_start < len(messages)
        and messages[tail_start].role == "tool"
        and messages[tail_start - 1].role == "assistant"
    ):
        tail_start -= 1
    return [
        Message(
            role="user",
            content="[Reactive compact]\n\n(original conversation saved to transcript)",
        )
    ]
