from __future__ import annotations

from coding_agent.core.compaction import (
    estimate_size,
    micro_compact,
    persist_large_output,
    reactive_compact,
    snip_compact,
    write_transcript,
)
from coding_agent.llm.base import Message


def make_messages(count: int) -> list[Message]:
    msgs = [Message(role="system", content="system prompt")]
    for i in range(1, count):
        role = "user" if i % 2 == 1 else "assistant"
        msgs.append(Message(role=role, content=f"message {i}"))
    return msgs


def test_persist_large_output_short_content():
    short = "short content"
    result = persist_large_output("test_id", short)
    assert result == short


def test_persist_large_output_long_content():
    long = "x" * 40_000
    result = persist_large_output("test_id_long", long)
    assert result.startswith("<persisted-output>")
    assert "Preview" in result


def test_snip_compact_under_limit():
    msgs = make_messages(10)
    result = snip_compact(msgs, max_messages=20)
    assert len(result) == len(msgs)


def test_snip_compact_over_limit():
    msgs = make_messages(60)
    result = snip_compact(msgs, max_messages=50)
    assert len(result) <= 50


def test_micro_compact_keeps_recent():
    msgs = [Message(role="tool", content="x" * 200) for _ in range(5)]
    result = micro_compact(msgs)
    recent = [m for m in result if m.role == "tool"]
    assert any("Earlier tool result compacted" in m.content for m in recent[:-3])


def test_micro_compact_under_threshold():
    msgs = [Message(role="tool", content="short") for _ in range(2)]
    result = micro_compact(msgs)
    assert result == msgs


def test_estimate_size_returns_int():
    msgs = make_messages(5)
    size = estimate_size(msgs)
    assert isinstance(size, int)
    assert size > 0


def test_write_transcript_creates_file(tmp_path):
    msgs = make_messages(3)
    path = write_transcript(msgs, transcript_dir=tmp_path)
    assert path.exists()
    content = path.read_text("utf-8")
    lines = [ln for ln in content.strip().splitlines() if ln.strip()]
    assert len(lines) == len(msgs)


def test_reactive_compact_reduces_messages():
    msgs = make_messages(15)
    assert len(reactive_compact(msgs)) < len(msgs)
