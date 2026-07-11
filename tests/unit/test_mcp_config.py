"""Tests for MCP config loader."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from coding_agent.tools.mcp.config import load_mcp_config


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
    assert config.servers["filesystem"].args == [
        "-y", "@modelcontextprotocol/server-filesystem", ".",
    ]
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
