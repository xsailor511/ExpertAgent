"""Tests for MCP config loader."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from coding_agent.tools.mcp.config import (
    find_mcp_config,
    load_mcp_config,
)


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


def test_find_mcp_config_user_level_priority():
    """User-level ~/.coding-agent/mcp.json wins over project candidates."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        user_cfg = Path(tmp) / "user_mcp.json"
        user_cfg.write_text('{"mcpServers": {"a": {"command": "x"}}}', encoding="utf-8")
        project_dir = Path(tmp) / "proj"
        project_dir.mkdir()
        (project_dir / "mcp.json").write_text(
            '{"mcpServers": {"b": {"command": "y"}}}', encoding="utf-8"
        )
        with patch(
            "coding_agent.tools.mcp.config.MCP_CONFIG_USER", user_cfg
        ):
            found = find_mcp_config(project_dir)
        assert found == user_cfg


def test_find_mcp_config_falls_back_to_project():
    """Without user-level config, project candidate is used."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "proj"
        project_dir.mkdir()
        (project_dir / "mcp.json").write_text(
            '{"mcpServers": {"b": {"command": "y"}}}', encoding="utf-8"
        )
        with patch(
            "coding_agent.tools.mcp.config.MCP_CONFIG_USER",
            Path(tmp) / "nonexistent.json",
        ):
            found = find_mcp_config(project_dir)
        assert found == project_dir / "mcp.json"


def test_find_mcp_config_none_when_absent():
    """Returns None when neither user nor project config exists."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "proj"
        project_dir.mkdir()
        with patch(
            "coding_agent.tools.mcp.config.MCP_CONFIG_USER",
            Path(tmp) / "nonexistent.json",
        ):
            found = find_mcp_config(project_dir)
        assert found is None
