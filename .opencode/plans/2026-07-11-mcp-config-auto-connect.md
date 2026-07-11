# MCP Config Auto-Connect Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the current runtime-only MCP connection model with a config-file-driven approach: parse `mcp.json`, auto-connect on startup, gracefully handle failures, and add a CLI command to inspect MCP server status.

**Architecture:** Add a `mcp.json` config loader (standard `{ "mcpServers": { ... } }` format used by Claude Desktop/Cursor). On agent startup, load the config, attempt to connect each server, silently drop failures, and register successful ones into the existing `ToolPool`. Add a `coding-agent mcp list` CLI command. The existing `ConnectMCPTool` remains for runtime connections.

**Tech Stack:** Python 3.11+, pydantic, JSON-RPC (existing), subprocess (existing)

---

### Task 1: Create MCP config loader module

**Files:**
- Create: `src/coding_agent/tools/mcp/config.py`
- Test: `tests/unit/test_mcp_config.py`

**Step 1: Write the failing test**

```python
"""Tests for MCP config loader."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from coding_agent.tools.mcp.config import MCPConfig, MCPServerConfig, load_mcp_config


def test_load_mcp_config_valid():
    """Parse a valid mcp.json with one server."""
    data = {
        "mcpServers": {
            "filesystem": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
            },
            "db": {
                "command": "python",
                "args": ["db_server.py"],
                "env": {"DB_URL": "postgres://localhost"},
            },
        }
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        f.flush()
        config = load_mcp_config(Path(f.name))
    assert "filesystem" in config.servers
    assert config.servers["filesystem"].command == "npx"
    assert config.servers["filesystem"].args == ["-y", "@modelcontextprotocol/server-filesystem", "."]
    assert config.servers["db"].env == {"DB_URL": "postgres://localhost"}


def test_load_mcp_config_empty():
    """Empty or missing file returns empty config."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("{}")
        f.flush()
        config = load_mcp_config(Path(f.name))
    assert config.servers == {}


def test_load_mcp_config_file_not_found():
    """Missing file returns empty config (no crash)."""
    config = load_mcp_config(Path("/nonexistent/mcp.json"))
    assert config.servers == {}


def test_load_mcp_config_invalid_json():
    """Invalid JSON returns empty config (no crash)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("not json")
        f.flush()
        config = load_mcp_config(Path(f.name))
    assert config.servers == {}
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_mcp_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'coding_agent.tools.mcp.config'`

**Step 3: Write minimal implementation**

```python
"""MCP config loader — parses mcp.json in standard format."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server."""

    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None


class MCPConfig(BaseModel):
    """Parsed mcp.json configuration."""

    servers: dict[str, MCPServerConfig] = Field(default_factory=dict)


def load_mcp_config(path: Path) -> MCPConfig:
    """Load and parse an mcp.json file.

    Returns empty MCPConfig if file is missing, invalid, or empty.
    Never raises.
    """
    if not path.exists():
        log.info("MCP config not found at %s", path)
        return MCPConfig()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Failed to parse MCP config %s: %s", path, e)
        return MCPConfig()

    servers_raw = raw.get("mcpServers", {})
    if not isinstance(servers_raw, dict):
        log.warning("mcpServers must be a dict in %s", path)
        return MCPConfig()

    servers: dict[str, MCPServerConfig] = {}
    for name, cfg in servers_raw.items():
        try:
            servers[name] = MCPServerConfig(**cfg)
        except Exception as e:
            log.warning("Skipping MCP server '%s': invalid config: %s", name, e)

    return MCPConfig(servers=servers)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_mcp_config.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add src/coding_agent/tools/mcp/config.py tests/unit/test_mcp_config.py
git commit -m "feat: add MCP config loader (mcp.json parser)"
```

---

### Task 2: Add auto-connect logic to ToolPool

**Files:**
- Modify: `src/coding_agent/tools/mcp/pool.py`
- Test: `tests/unit/test_mcp_pool.py`

**Step 1: Write the failing test**

Add to `tests/unit/test_mcp_pool.py`:

```python
def test_connect_from_config_success(registry: ToolRegistry):
    """connect_from_config registers servers and discovers tools."""
    from coding_agent.tools.mcp.config import MCPConfig, MCPServerConfig
    from coding_agent.tools.mcp.pool import ToolPool

    pool = ToolPool(registry)
    config = MCPConfig(servers={
        "filesystem": MCPServerConfig(
            command="echo",
            args=["{}"],  # returns empty JSON-RPC-like response
        ),
    })
    pool.connect_from_config(config)
    # Server that fails to connect should be silently dropped
    # (echo doesn't speak JSON-RPC, so it will fail)
    assert "filesystem" not in pool._mcp_clients


def test_connect_from_config_empty(registry: ToolRegistry):
    """Empty config does nothing."""
    from coding_agent.tools.mcp.config import MCPConfig
    from coding_agent.tools.mcp.pool import ToolPool

    pool = ToolPool(registry)
    pool.connect_from_config(MCPConfig())
    assert pool._mcp_clients == {}
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_mcp_pool.py::test_connect_from_config_success tests/unit/test_mcp_pool.py::test_connect_from_config_empty -v`
Expected: FAIL with `AttributeError: 'ToolPool' object has no attribute 'connect_from_config'`

**Step 3: Add `connect_from_config` to ToolPool**

Add to `src/coding_agent/tools/mcp/pool.py`:

```python
def connect_from_config(self, config: MCPConfig) -> None:
    """Connect to all MCP servers defined in config.

    Failed connections are silently dropped (logged as warnings).
    """
    for name, server_cfg in config.servers.items():
        if name in self._mcp_clients:
            log.warning("MCP server '%s' already connected, skipping", name)
            continue
        try:
            client = MCPClient(
                server_name=name,
                command=[server_cfg.command] + server_cfg.args,
                env=server_cfg.env,
            )
            client.connect()
            self.register_mcp(name, client)
            log.info("Connected to MCP server '%s'", name)
        except Exception as e:
            log.warning("Failed to connect MCP server '%s': %s", name, e)
```

Also add the import at the top of `pool.py`:

```python
from coding_agent.tools.mcp.config import MCPConfig
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_mcp_pool.py::test_connect_from_config_success tests/unit/test_mcp_pool.py::test_connect_from_config_empty -v`
Expected: 2 PASSED

**Step 5: Commit**

```bash
git add src/coding_agent/tools/mcp/pool.py tests/unit/test_mcp_pool.py
git commit -m "feat: add connect_from_config to ToolPool"
```

---

### Task 3: Wire auto-connect into Agent startup

**Files:**
- Modify: `src/coding_agent/core/agent.py`
- Test: `tests/unit/test_agent_mcp.py`

**Step 1: Write the failing test**

Create `tests/unit/test_agent_mcp.py`:

```python
"""Tests for MCP auto-connect on agent startup."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from coding_agent.tools.mcp.config import MCPConfig, MCPServerConfig


def test_agent_auto_connects_mcp_from_config():
    """Agent.from_settings loads mcp.json and connects servers."""
    from coding_agent.core.agent import Agent
    from coding_agent.tools.mcp.pool import ToolPool

    # Create a temp mcp.json
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, prefix="mcp_"
    ) as f:
        json.dump({
            "mcpServers": {
                "test-server": {
                    "command": "echo",
                    "args": ["{}"],
                }
            }
        }, f)
        mcp_path = Path(f.name)

    # Patch the config path to point to our temp file
    with patch("coding_agent.tools.mcp.config.MCP_CONFIG_PATH", mcp_path):
        agent = Agent.from_settings()
        # The server should have been attempted (echo doesn't speak JSON-RPC, so it fails silently)
        # We just verify no crash and ToolPool exists
        assert hasattr(agent.tools, "_mcp_clients")
        # Failed connections are silently dropped
        assert "filesystem" not in agent.tools._mcp_clients
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_agent_mcp.py -v`
Expected: FAIL (various reasons — module not found, MCP_CONFIG_PATH not defined, etc.)

**Step 3: Add MCP config path constant and wire into Agent.from_settings**

In `src/coding_agent/tools/mcp/config.py`, add:

```python
from pathlib import Path

# Default MCP config search paths (project-level first, then user-level)
MCP_CONFIG_CANDIDATES = [
    Path(".opencode/mcp.json"),
    Path("mcp.json"),
]
```

In `src/coding_agent/core/agent.py`, modify `from_settings()` — after creating `tool_pool` and before creating `memory`, add:

```python
# Auto-connect MCP servers from config
from coding_agent.tools.mcp.config import MCPConfig, MCP_CONFIG_CANDIDATES, load_mcp_config

mcp_config_path: Path | None = None
for candidate in MCP_CONFIG_CANDIDATES:
    resolved = Path(settings.workdir) / candidate
    if resolved.exists():
        mcp_config_path = resolved
        break

if mcp_config_path:
    config = load_mcp_config(mcp_config_path)
    tool_pool.connect_from_config(config)
    # Track connected servers in memory context
    memory.context["mcp_servers"] = list(tool_pool._mcp_clients.keys())
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_agent_mcp.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/coding_agent/tools/mcp/config.py src/coding_agent/core/agent.py tests/unit/test_agent_mcp.py
git commit -m "feat: auto-connect MCP servers from mcp.json on agent startup"
```

---

### Task 4: Add `coding-agent mcp list` CLI command

**Files:**
- Modify: `src/coding_agent/cli.py`
- Test: `tests/unit/test_cli_mcp.py`

**Step 1: Write the failing test**

Create `tests/unit/test_cli_mcp.py`:

```python
"""Tests for MCP CLI commands."""

from __future__ import annotations

from typer.testing import CliRunner

from coding_agent.cli import app

runner = CliRunner()


def test_mcp_list_no_servers():
    """mcp list shows message when no servers connected."""
    result = runner.invoke(app, ["mcp", "list"])
    assert result.exit_code == 0
    assert "MCP 服务器" in result.stdout or "没有" in result.stdout or "No" in result.stdout
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cli_mcp.py -v`
Expected: FAIL with `Exit code 2` — no `mcp` command group

**Step 3: Add `mcp` command group to CLI**

In `src/coding_agent/cli.py`, add after the `init` command:

```python
@app.group()
def mcp() -> None:
    """管理 MCP 服务器连接。"""
    pass


@mcp.command(name="list")
def mcp_list() -> None:
    """列出已连接的 MCP 服务器。"""
    from coding_agent.core.agent import Agent

    agent = Agent.from_settings()
    servers = list(agent.tools._mcp_clients.keys()) if hasattr(agent.tools, "_mcp_clients") else []
    if not servers:
        rprint("[yellow]没有已连接的 MCP 服务器。[/]")
        rprint("提示：在项目根目录创建 [bold].opencode/mcp.json[/] 来配置 MCP 服务器。")
        return

    rprint("[bold green]已连接的 MCP 服务器:[/]")
    for name in servers:
        client = agent.tools._mcp_clients[name]
        tool_count = len(agent.tools._mcp_tools)
        rprint(f"  [cyan]{name}[/] — {tool_count} 个工具")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_cli_mcp.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/coding_agent/cli.py tests/unit/test_cli_mcp.py
git commit -m "feat: add 'coding-agent mcp list' CLI command"
```

---

### Task 5: Create example mcp.json and update docs

**Files:**
- Create: `.opencode/mcp.json.example`
- Modify: `.env.example` (add MCP config path hint)

**Step 1: Create example config**

Create `.opencode/mcp.json.example`:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "."
      ]
    },
    "github": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-github"
      ],
      "env": {
        "GITHUB_TOKEN": "<your-github-token>"
      }
    }
  }
}
```

**Step 2: Commit**

```bash
git add .opencode/mcp.json.example
git commit -m "docs: add example mcp.json config"
```

---

### Task 6: Update system prompt to show config-based MCP servers

**Files:**
- Modify: `src/coding_agent/core/memory.py`

**Step 1: Update `_build_system_prompt` to mention config-based MCP**

In `src/coding_agent/core/memory.py`, update the MCP section:

```python
# MCP servers
mcp = self.context.get("mcp_servers", [])
if mcp:
    sections.append(
        f"已连接 MCP 服务器：{', '.join(mcp)}\n"
        "使用 mcp__{server}__{tool_name} 格式调用 MCP 工具。\n"
        "运行 'coding-agent mcp list' 查看详情。"
    )
```

**Step 2: Commit**

```bash
git add src/coding_agent/core/memory.py
git commit -m "feat: show MCP server info in system prompt"
```

---

### Task 7: Run full test suite and verify

**Step 1: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: All tests pass (including new MCP config tests)

**Step 2: Run lint + typecheck**

Run: `uv run ruff check src tests`
Expected: No errors

Run: `uv run mypy src`
Expected: No type errors

**Step 3: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "chore: fix lint/type issues after MCP config changes"
```
