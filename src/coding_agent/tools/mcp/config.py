"""MCP config loader — parses mcp.json in standard format."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# User-level MCP config (highest priority, shared across projects)
MCP_CONFIG_USER = Path.home() / ".coding-agent" / "mcp.json"

# Project-level MCP config candidates (searched relative to workdir)
MCP_CONFIG_CANDIDATES = [
    Path(".opencode/mcp.json"),
    Path("mcp.json"),
]


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


def find_mcp_config(workdir: Path) -> Path | None:
    """Search for mcp.json and return the first existing path.

    Priority:
        1. User-level ``~/.coding-agent/mcp.json`` (shared across projects)
        2. Project candidates relative to ``workdir`` (.opencode/mcp.json, mcp.json)

    Returns None if no config exists.
    """
    if MCP_CONFIG_USER.exists():
        log.info("Found user-level MCP config at %s", MCP_CONFIG_USER)
        return MCP_CONFIG_USER
    for candidate in MCP_CONFIG_CANDIDATES:
        resolved = workdir / candidate
        if resolved.exists():
            log.info("Found MCP config at %s", resolved)
            return resolved
    return None
