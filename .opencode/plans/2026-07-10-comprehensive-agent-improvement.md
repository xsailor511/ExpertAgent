# Comprehensive Agent Improvement Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform the current coding agent from a single-user ReAct loop into a production-grade multi-capability system with hooks, compaction, recovery, task graph, skill loading, background/cron, multi-agent teams, worktree isolation, and MCP external tool integration.

**Architecture:** New capabilities are added as **independent modules** under existing top-level packages (`core/`, `tools/`, `tasks/`, `skills/`, `teams/`), each owning its own subdirectory. The `Agent` and `AgentLoop` classes are **enriched via composition** (not inheritance explosion) — hooks, compaction, recovery, and background dispatch are wired into the loop as pluggable pipelines. The tool registry gains a `ToolPool` layer that merges builtin + MCP tools dynamically each round.

**Tech Stack:** Python 3.11+, asyncio, pydantic, anthropic SDK, git (subprocess), JSONL mailboxes, threading for cron/background, `yaml` for skill frontmatter

---

## Architecture Analysis: Gap Summary

| Area | Current State | Target State | Priority |
|------|-------------|-------------|----------|
| **Hooks/Extensions** | None. Permission is hardcoded in loop | `HookRegistry` with 4 events: `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop` | P0 |
| **Context Compaction** | Basic `_maybe_compress` — drops oldest messages | Layered pipeline: persist-large → snip → micro → summary (LLM) → reactive (for 413 errors) | P0 |
| **Error Recovery** | `try/except` in tools only | `RetryState` with 429/529 backoff, model fallback, `max_tokens` escalation, prompt-too-long reactive compact | P0 |
| **Task Graph** | None | JSON-backed `Task` dataclass with dependency blocking, ownership, status lifecycle | P1 |
| **Skill System** | None | `SKILL_REGISTRY` scanning skills/*/SKILL.md, frontmatter parsing, `load_skill` tool | P1 |
| **Background Tasks** | None | `BackgroundTaskManager` — slow bash ops run in daemon thread, results injected as notifications | P2 |
| **Cron Scheduler** | None | `CronScheduler` with 5-field cron parser, durable JSON persistence, daemon thread | P2 |
| **Multi-Agent Teams** | None | `MessageBus` (JSONL mailboxes), `TeammateThread`, plan-approval/shutdown protocol | P3 |
| **Worktree Isolation** | None | Git worktree create/remove/keep, task-binding, path-scoped execution | P3 |
| **MCP Integration** | None | `MCPClient`, `ToolPool.assemble()` merging builtin + MCP tools, name normalization | P3 |
| **Codebase RAG** | Empty placeholder | Tree-sitter indexing, code search with scope, symbol resolution | P3 |
| **E2B Sandbox** | Declared in enum, not implemented | E2B Python SDK integration | P3 |
| **Native Anthropic Provider** | Routes through OpenAI compatible | Direct Anthropic SDK with native tool_use + streaming | P3 |

---

## New File Structure

```
src/coding_agent/
├── core/
│   ├── agent.py              # MODIFY: integrate hooks during run()
│   ├── loop.py               # MODIFY: add compaction, recovery, background, cron pipelines
│   ├── memory.py             # MODIFY: add compaction pipeline methods
│   ├── hooks.py              # CREATE: HookRegistry + builtin hooks
│   ├── compaction.py         # CREATE: layered compaction pipeline
│   ├── recovery.py           # CREATE: error recovery with retry/backoff
│   ├── background.py         # CREATE: background task manager
│   └── cron.py               # CREATE: cron scheduler
├── tasks/                    # CREATE MODULE
│   ├── __init__.py
│   ├── models.py             # Task dataclass
│   ├── store.py              # JSON file-backed persistence
│   ├── graph.py              # Dependency graph (can_start, unblocked)
│   └── tools.py              # Tool wrappers (create_task, claim_task, etc.)
├── skills/                   # CREATE MODULE
│   ├── __init__.py
│   ├── frontmatter.py        # YAML frontmatter parser
│   ├── registry.py           # SKILL_REGISTRY scan + query
│   └── tool.py               # load_skill Tool
├── teams/                    # CREATE MODULE
│   ├── __init__.py
│   ├── bus.py                # MessageBus (JSONL inboxes)
│   ├── protocol.py           # ProtocolState (plan_approval, shutdown)
│   ├── teammate.py           # Teammate thread spawn + run loop
│   └── worktree.py           # Git worktree isolation
├── tools/
│   ├── mcp/                  # CREATE MODULE
│   │   ├── __init__.py
│   │   ├── client.py         # MCPClient (connect, discover, call)
│   │   └── pool.py           # ToolPool — merges builtin + MCP tools
│   ├── registry.py           # MODIFY: add ToolPool layer
│   └── (existing tools unchanged)
├── llm/
│   ├── anthropic_provider.py # CREATE: native Anthropic SDK provider
│   └── ... (existing files)
└── sandbox/
    └── e2b.py                # CREATE: E2B cloud sandbox
```

---

## Phase 0: Foundation Infrastructure (P0 — must ship first)

---

### Task 0.1: Hook System

**Files:**
- Create: `src/coding_agent/core/hooks.py`
- Modify: `src/coding_agent/core/loop.py:46-86` (integrate hooks in tool loop)
- Modify: `src/coding_agent/core/agent.py:57-63` (add hook registry to Agent)
- Test: `tests/unit/test_hooks.py`

**Step 1: Write hooks.py**

```python
from __future__ import annotations

import enum
from typing import Any, Callable

HookCallback = Callable[..., str | None]


class HookEvent(str, enum.Enum):
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

    def trigger(self, event: HookEvent, *args: Any, **kwargs: Any) -> str | None:
        for cb in self._hooks[event]:
            result = cb(*args, **kwargs)
            if result is not None:
                return result
        return None


# Builtin permission hook
DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if="]
DESTRUCTIVE = ["rm ", "> /etc/", "chmod 777"]


def build_permission_hook(permissions: Any) -> HookCallback:
    async def hook(block_name: str, block_input: dict[str, Any]) -> str | None:
        if block_name in ("write_file", "edit_file"):
            path = block_input.get("path", "")
            from coding_agent.utils.security import safe_resolve
            try:
                safe_resolve(Path.cwd(), path)
            except Exception as e:
                return f"Permission denied: {e}"
        if block_name == "bash":
            command = block_input.get("command", "")
            for pattern in DENY_LIST:
                if pattern in command:
                    return f"Permission denied: '{pattern}' is on the deny list"
            if any(token in command for token in DESTRUCTIVE):
                if not await permissions.check(block_name, block_input, "bash"):
                    return f"Permission denied by user"
        return None
    return hook


def build_log_hook(logger: Any) -> HookCallback:
    def hook(block_name: str, **kwargs: Any) -> None:
        logger.debug(f"[hook] {block_name}")
        return None
    return hook
```

**Step 2: Write failing tests**

```python
import pytest
from coding_agent.core.hooks import HookRegistry, HookEvent

@pytest.fixture
def registry():
    return HookRegistry()

def test_register_and_trigger_no_block(registry):
    results = []
    registry.register(HookEvent.PRE_TOOL_USE, lambda **kw: (results.append(kw), None)[1])
    registry.trigger(HookEvent.PRE_TOOL_USE, block_name="bash")
    assert len(results) == 1

def test_trigger_blocks_on_first_non_none(registry):
    registry.register(HookEvent.PRE_TOOL_USE, lambda **kw: "blocked")
    registry.register(HookEvent.PRE_TOOL_USE, lambda **kw: (pytest.fail("should not run"), None)[1])
    result = registry.trigger(HookEvent.PRE_TOOL_USE, block_name="bash")
    assert result == "blocked"

def test_unregistered_event_returns_none(registry):
    result = registry.trigger(HookEvent.PRE_TOOL_USE, block_name="bash")
    assert result is None

def test_user_prompt_submit_event(registry):
    registry.register(HookEvent.USER_PROMPT_SUBMIT, lambda msg: None)
    result = registry.trigger(HookEvent.USER_PROMPT_SUBMIT, msg="hello")
    assert result is None

def test_multiple_hooks_all_run(registry):
    results = []
    registry.register(HookEvent.STOP, lambda: (results.append("a"), None)[1])
    registry.register(HookEvent.STOP, lambda: (results.append("b"), None)[1])
    registry.trigger(HookEvent.STOP)
    assert results == ["a", "b"]
```

**Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_hooks.py -v`
Expected: ImportError (hooks.py doesn't exist yet)

**Step 4: Create hooks.py with all code from Step 1**

**Step 5: Integrate into AgentLoop**

In `loop.py`:
- Add `hooks: HookRegistry | None = None` to `__init__`
- In `_execute_tool_call`, call `hooks.trigger(HookEvent.PRE_TOOL_USE, ...)` before each tool
- After execution, call `hooks.trigger(HookEvent.POST_TOOL_USE, ...)`
- On loop exit, call `hooks.trigger(HookEvent.STOP, ...)`

**Step 6: Integrate into Agent**

In `agent.py`:
- Add `self.hooks = HookRegistry()` to `__init__`
- Register `build_permission_hook(self.permissions)` and `build_log_hook(log)`
- Pass `hooks=self.hooks` to `AgentLoop`

**Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_hooks.py -v`
Expected: 5 passed

**Step 8: Commit**

```bash
git add src/coding_agent/core/hooks.py tests/unit/test_hooks.py
git commit -m "feat(core): add hook system with HookEvent/HookRegistry"
```

---

### Task 0.2: Context Compaction Pipeline

**Files:**
- Create: `src/coding_agent/core/compaction.py`
- Modify: `src/coding_agent/core/loop.py` (call compaction before each LLM call)
- Modify: `src/coding_agent/core/memory.py` (integrate compaction pipeline)
- Test: `tests/unit/test_compaction.py`

**Step 1: Write compaction.py**

```python
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from coding_agent.llm.base import Message

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
        f"<persisted-output>\nFull output: {path}\n"
        f"Preview:\n{output[:2000]}\n</persisted-output>"
    )


def snip_compact(messages: list[Message], max_messages: int = 50) -> list[Message]:
    if len(messages) <= max_messages:
        return messages
    head_end, tail_start = 3, len(messages) - (max_messages - 3)
    if head_end > 0 and messages[head_end - 1].role == "assistant":
        tc = messages[head_end - 1].tool_calls
        if tc:
            while head_end < len(messages) and messages[head_end].role == "tool":
                head_end += 1
    if (tail_start > 0 and tail_start < len(messages)
            and messages[tail_start].role == "tool"
            and messages[tail_start - 1].role == "assistant"):
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
    for idx, msg in tool_msgs[:-KEEP_RECENT_TOOL_RESULTS]:
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
    llm: Any,
    transcript_dir: Path | None = None,
) -> list[Message]:
    transcript = write_transcript(messages, transcript_dir)
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
    transcript = write_transcript(messages, transcript_dir)
    tail_start = max(0, len(messages) - 5)
    if (tail_start > 0 and tail_start < len(messages)
            and messages[tail_start].role == "tool"
            and messages[tail_start - 1].role == "assistant"):
        tail_start -= 1
    return [Message(role="user", content=f"[Reactive compact]\n\n(Compressed)")]
```

**Step 2-4: Write tests for each function, implement, verify**

Test cases:
- `persist_large_output` with short vs long content
- `snip_compact` with various message counts
- `micro_compact` keeps recent 3 tool results, shortens older ones
- `estimate_size` returns positive int
- `write_transcript` creates file with correct format

**Step 5: Integrate into loop.py**

Before each LLM call:
```python
self.memory.messages = snip_compact(self.memory.messages)
self.memory.messages = micro_compact(self.memory.messages)
if estimate_size(self.memory.messages) > self.memory.max_tokens:
    self.memory.messages = await summary_compact(self.memory.messages, self.llm)
```

**Step 6: Commit**

```bash
git add src/coding_agent/core/compaction.py tests/unit/test_compaction.py
git commit -m "feat(core): add compaction pipeline (persist-large, snip, micro, summary)"
```

---

### Task 0.3: Error Recovery with Retry

**Files:**
- Create: `src/coding_agent/core/recovery.py`
- Modify: `src/coding_agent/core/loop.py` (wrap LLM calls with recovery)
- Test: `tests/unit/test_recovery.py`

```python
from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Callable


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
    base = min(500 * (2**attempt), 32_000) / 1000
    return base + random.uniform(0, base * 0.25)


def is_rate_limit(e: Exception) -> bool:
    name = type(e).__name__.lower()
    msg = str(e).lower()
    return "ratelimit" in name or "429" in msg


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
    max_retries: int = 3,
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
                if state.consecutive_529 >= 2 and state.fallback:
                    state.current_model = state.fallback
                    state.consecutive_529 = 0
                await asyncio.sleep(retry_delay(attempt))
                continue
            raise
    raise RuntimeError(f"Max retries ({max_retries}) exceeded")
```

**Integration in loop.py:**

```python
# Replace direct LLM call with:
try:
    response = await with_retry(
        lambda: self.llm.chat(messages=self.memory.messages, tools=tool_schemas),
        self.recovery_state,
    )
except Exception as e:
    if is_prompt_too_long(e) and not self.recovery_state.has_attempted_reactive_compact:
        self.memory.messages = reactive_compact(self.memory.messages)
        self.recovery_state.has_attempted_reactive_compact = True
        continue
    raise
```

---

### Task 0.4: Wire Everything into AgentLoop

**Files:**
- Modify: `src/coding_agent/core/loop.py` — major refactor

The refactored `run()` method orchestrates all subsystems:

```python
async def run(self, user_input: str) -> str:
    self.hooks.trigger(HookEvent.USER_PROMPT_SUBMIT, user_input=user_input)
    self.memory.add_user(user_input)

    for iteration in range(self.max_iterations):
        # 1. Inject scheduled/background work
        for job in self.cron.pop_fired():
            self.memory.add_user(f"[Scheduled] {job.prompt}")
        for note in self.bg_manager.collect_results():
            self.memory.add_user(note)

        # 2. Compaction pipeline
        self.memory.messages = snip_compact(self.memory.messages)
        self.memory.messages = micro_compact(self.memory.messages)
        if estimate_size(self.memory.messages) > self.memory.max_tokens:
            self.memory.messages = await summary_compact(self.memory.messages, self.llm)

        # 3. Assemble tools
        tool_schemas = self.tool_pool.schemas()

        # 4. Call LLM with recovery
        max_tokens = self.escalated_max_tokens if self.recovery_state.has_escalated else self.default_max_tokens
        try:
            response = await with_retry(
                lambda: self.llm.chat(
                    messages=self.memory.messages,
                    tools=tool_schemas,
                ),
                self.recovery_state,
            )
        except Exception as e:
            if is_prompt_too_long(e) and not self.recovery_state.has_attempted_reactive_compact:
                self.memory.messages = reactive_compact(self.memory.messages)
                self.recovery_state.has_attempted_reactive_compact = True
                continue
            raise

        # 5. Handle max_tokens
        if response.finish_reason == "max_tokens":
            if not self.recovery_state.has_escalated:
                self.recovery_state.has_escalated = True
                continue
            self.memory.add_assistant(content=response.content, tool_calls=[])
            self.memory.add_user("Continue from where you left off.")
            continue

        self.recovery_state.has_escalated = False

        # 6. Record response
        self.memory.add_assistant(content=response.content, tool_calls=...)

        # 7. Exit if no tool calls
        if not response.tool_calls:
            self.hooks.trigger(HookEvent.STOP)
            return response.content or ""

        # 8. Execute tools
        for tc in response.tool_calls:
            await self._execute_tool_call(tc)

    self.hooks.trigger(HookEvent.STOP)
    return "Max iterations reached"
```

**Commit at the end of Phase 0:**

```bash
git add -A
git commit -m "feat(core): integrate hooks, compaction, recovery into AgentLoop"
```

---

## Phase 1: Core Agent Features

---

### Task 1.1: Task Graph System

**Files:**
- Create: `src/coding_agent/tasks/__init__.py`
- Create: `src/coding_agent/tasks/models.py`
- Create: `src/coding_agent/tasks/store.py`
- Create: `src/coding_agent/tasks/graph.py`
- Create: `src/coding_agent/tasks/tools.py`
- Modify: `src/coding_agent/tools/registry.py` (register task tools)
- Test: `tests/unit/test_tasks.py`

**Step 1: models.py**

```python
from __future__ import annotations

import random
import time
from dataclasses import asdict, dataclass, field


@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str  # pending | in_progress | completed | cancelled
    owner: str | None
    blocked_by: list[str] = field(default_factory=list)
    worktree: str | None = None
    created_at: float = field(default_factory=time.time)

    @staticmethod
    def new_id() -> str:
        return f"task_{int(time.time())}_{random.randint(0, 9999):04d}"

    def to_dict(self) -> dict:
        return asdict(self)
```

**Step 2: store.py**

```python
from __future__ import annotations

import json
from pathlib import Path
from coding_agent.tasks.models import Task

TASKS_DIR = Path(".tasks")


class TaskStore:
    def __init__(self, tasks_dir: Path = TASKS_DIR):
        self.tasks_dir = tasks_dir
        self.tasks_dir.mkdir(exist_ok=True)

    def _path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.json"

    def save(self, task: Task) -> None:
        self._path(task.id).write_text(json.dumps(task.to_dict(), indent=2), encoding="utf-8")

    def load(self, task_id: str) -> Task:
        return Task(**json.loads(self._path(task_id).read_text("utf-8")))

    def list_all(self) -> list[Task]:
        tasks = []
        for path in sorted(self.tasks_dir.glob("task_*.json")):
            tasks.append(Task(**json.loads(path.read_text("utf-8"))))
        return tasks

    def delete(self, task_id: str) -> None:
        self._path(task_id).unlink(missing_ok=True)
```

**Step 3: graph.py**

```python
from coding_agent.tasks.models import Task
from coding_agent.tasks.store import TaskStore


class TaskGraph:
    def __init__(self, store: TaskStore):
        self.store = store

    def can_start(self, task: Task) -> bool:
        for dep_id in task.blocked_by:
            try:
                dep = self.store.load(dep_id)
                if dep.status != "completed":
                    return False
            except FileNotFoundError:
                return False
        return True

    def claimable(self) -> list[Task]:
        return [t for t in self.store.list_all()
                if t.status == "pending" and not t.owner and self.can_start(t)]

    def unblocked_by(self, task_id: str) -> list[str]:
        completed = self.store.load(task_id)
        if completed.status != "completed":
            return []
        return [t.subject for t in self.store.list_all()
                if t.status == "pending" and task_id in t.blocked_by and self.can_start(t)]
```

**Step 4: tools.py** — Five Tool subclasses following the existing Tool pattern.

Each tool wraps store/graph operations:
- `CreateTaskTool` — creates Task, saves to store
- `ListTasksTool` — lists all tasks
- `GetTaskTool` — single task by id
- `ClaimTaskTool` — sets owner + status=in_progress
- `CompleteTaskTool` — sets status=completed, returns unblocked tasks

**Step 5: Register in create_default_registry()**

```python
from coding_agent.tasks.tools import CreateTaskTool, ListTasksTool, ...
from coding_agent.tasks.store import TaskStore
from coding_agent.tasks.graph import TaskGraph

def create_default_registry(workdir):
    registry = ToolRegistry()
    # ... existing tools ...

    store = TaskStore()
    graph = TaskGraph(store)
    registry.register(CreateTaskTool(store=store))
    registry.register(ListTasksTool(store=store))
    registry.register(GetTaskTool(store=store))
    registry.register(ClaimTaskTool(store=store, graph=graph))
    registry.register(CompleteTaskTool(store=store, graph=graph))
    return registry
```

---

### Task 1.2: Skill System

**Files:**
- Create: `src/coding_agent/skills/__init__.py`
- Create: `src/coding_agent/skills/frontmatter.py`
- Create: `src/coding_agent/skills/registry.py`
- Create: `src/coding_agent/skills/tool.py`
- Modify: `src/coding_agent/core/agent.py` (scan skills on init, inject catalog)
- Modify: `src/coding_agent/core/memory.py` (include skill catalog in system prompt)
- Test: `tests/unit/test_skills.py`

**Key design:** Skills are stored as `skills/{name}/SKILL.md` with YAML frontmatter. At agent startup, `SkillRegistry.scan()` loads them all. The catalog (names + descriptions) is appended to the system prompt. Full content is loaded on-demand via the `load_skill` tool.

```python
class SkillRegistry:
    def scan(self) -> None: ...
    def list_skills(self) -> str: ...    # catalog string for system prompt
    def load_skill(self, name: str) -> str | None: ...  # full content
```

---

## Phase 2: Advanced Features

---

### Task 2.1: Background Task Manager

**Files:**
- Create: `src/coding_agent/core/background.py`
- Modify: `src/coding_agent/core/loop.py` (run slow ops in background)
- Test: `tests/unit/test_background.py`

Detects slow bash commands (install, build, test, deploy, compile, pip install, etc.) and runs them in a daemon thread. The main loop gets a placeholder `[Background task bg_0001 started]` immediately. When the thread completes, a `<task_notification>` is injected before the next LLM call.

---

### Task 2.2: Cron Scheduler

**Files:**
- Create: `src/coding_agent/core/cron.py`
- Modify: `src/coding_agent/core/loop.py` (check cron queue before LLM)
- Modify: `src/coding_agent/core/agent.py` (start cron on init)
- Test: `tests/unit/test_cron.py`

5-field cron (min hour dom month dow). Daemon thread checks every second. Durable jobs persist to `.scheduled_tasks.json`. Fired jobs are consumed via `pop_fired()`.

---

## Phase 3: Multi-Agent & Isolation

---

### Task 3.1: MessageBus

**Files:**
- Create: `src/coding_agent/teams/__init__.py`
- Create: `src/coding_agent/teams/bus.py`
- Create: `src/coding_agent/teams/protocol.py`

Append-only JSONL mailboxes under `.mailboxes/`. Each agent has one mailbox file. Reading clears it. Protocol layer adds request-response matching (plan approval, shutdown).

---

### Task 3.2: Teammate Threads

**Files:**
- Create: `src/coding_agent/teams/teammate.py`

Each teammate is a daemon thread with its own LLM call loop, a restricted tool set (bash, read/write file, task ops), inbox polling, and idle task claiming. Teammates cannot spawn other teammates.

---

### Task 3.3: Worktree Isolation

**Files:**
- Create: `src/coding_agent/teams/worktree.py`

Git worktree operations: `create(name)` → `git worktree add -b wt/{name} HEAD`, `remove(name)` → `git worktree remove --force`, `keep(name)` → log event but keep. Tasks can be bound to worktrees. Teammates work transparently inside the bound directory.

---

### Task 3.4: MCP Tool Integration

**Files:**
- Create: `src/coding_agent/tools/mcp/__init__.py`
- Create: `src/coding_agent/tools/mcp/client.py`
- Create: `src/coding_agent/tools/mcp/pool.py`
- Modify: `src/coding_agent/tools/registry.py` (integrate ToolPool)
- Test: `tests/unit/test_mcp_pool.py`

`ToolPool` merges builtin tools + MCP tools. MCP tools are prefixed `mcp__{server}__{tool}`. Each round, `pool.schemas()` generates the combined list. `pool.execute(name, args)` routes to the right handler.

---

## Phase 4: Polish

---

### Task 4.1: Codebase RAG (placeholder → real)

Implement tree-sitter-based indexing (the project already has `tree-sitter` and `tree-sitter-languages` in pyproject.toml). Support symbol search, file-level summaries, and scope-aware code lookup.

### Task 4.2: E2B Sandbox

Implement `Sandbox` ABC using `e2b-code-interpreter`. Currently `SandboxType.E2B` is declared but has no implementation.

### Task 4.3: Native Anthropic Provider

Create `LLMProvider` subclass using the Anthropic Python SDK directly. Properly handle native `tool_use` content blocks and streaming. Update `router.py` to route `anthropic:` prefix to this provider.

---

## Testing Strategy

| Module | File | Key Tests |
|--------|------|-----------|
| Hooks | `test_hooks.py` | register, trigger, block chain, all 4 event types |
| Compaction | `test_compaction.py` | persist_large_file, snip_compact_keeps_recent, micro_compact_shortens_old, estimate_size |
| Recovery | `test_recovery.py` | retry_delay_values, is_rate_limit_matches_429, with_retry_succeeds, with_retry_fallback_model |
| Tasks | `test_tasks.py` | create_task, save_load, dependency_blocking, unblocked_list, claim_task_requires_completed_deps |
| Skills | `test_skills.py` | frontmatter_parse, scan_directory, load_skill_by_name, catalog_format |
| Cron | `test_cron.py` | field_matches_all, validate_cron, schedule_and_cancel, durable_persistence |
| Background | `test_background.py` | is_slow_detects_keywords, start_and_collect, collect_returns_empty_when_none |
| MCP | `test_mcp_pool.py` | schemas_includes_builtin, schemas_includes_mcp_prefix, execute_routes_correctly |
| Bus | `test_teams_bus.py` | send_and_read, read_empty_returns_list, multiple_agents |
| Protocol | `test_teams_protocol.py` | request_id_generation, match_response, consume_inbox_routes_protocol |
| Worktree | `test_worktree.py` | valid_name, invalid_name_rejected, create_calls_git |

---

## Execution Order Recommendation

```
Phase 0 (Foundation) — 2-3 sessions
├── Task 0.1: Hook system
├── Task 0.2: Compaction pipeline
├── Task 0.3: Error recovery
└── Task 0.4: Wire everything into loop

Phase 1 (Core Features) — 2-3 sessions
├── Task 1.1: Task graph system
└── Task 1.2: Skill system

Phase 2 (Advanced Features) — 2-3 sessions
├── Task 2.1: Background task manager
└── Task 2.2: Cron scheduler

Phase 3 (Multi-Agent) — 3-4 sessions
├── Task 3.1: MessageBus + Protocol
├── Task 3.2: Teammate threads
├── Task 3.3: Worktree isolation
└── Task 3.4: MCP tool integration

Phase 4 (Polish) — 2-3 sessions
├── Task 4.1: Codebase RAG
├── Task 4.2: E2B sandbox
└── Task 4.3: Native Anthropic provider
```

Total estimated: 11-16 implementation sessions, each 20-40 minutes.

---

## Key Design Principles Applied

1. **Composition over inheritance** — Agent gains capabilities by composing subsystems, not via deep class hierarchies
2. **File-backed state** — Tasks, mailboxes, cron, worktree events all use JSON/JSONL; inspectable on disk, no DB required
3. **Threads for concurrency** — Background and cron use daemon threads; asyncio event loop is never blocked
4. **Progressive compaction** — Try cheapest reduction first (snip, micro) before calling LLM for summarization
5. **MCP naming convention** — `mcp__{server}__{tool}` avoids collisions; model sees clear prefix for external tools
6. **Hook-driven extension** — Permission, logging, audit are hooks; adding custom pre/post checks never modifies core
7. **TDD throughout** — Every component starts with a failing test, minimal implementation, then passing test
8. **YAGNI** — No feature is added without a concrete use case from the reference code analysis
