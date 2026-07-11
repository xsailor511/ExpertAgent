"""MCP config loader — parses mcp.json in standard format."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# Default MCP config search paths (project-level first)
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
    """Search for mcp.json in the workdir using the candidate relative paths.

    Returns the first that exists, or None.
    """
    for candidate in MCP_CONFIG_CANDIDATES:
        resolved = workdir / candidate
        if resolved.exists():
            log.info("Found MCP config at %s", resolved)
            return resolved
    return None
