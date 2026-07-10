"""Git worktree isolation — create, remove, and manage isolated working trees."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

VALID_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-./]+$")


def valid_name(name: str) -> bool:
    """Check if a worktree name is valid (no special chars, no path traversal)."""
    if not name or len(name) > 100:
        return False
    if ".." in name or name.startswith("/") or name.startswith("-"):
        return False
    return bool(VALID_NAME_RE.match(name))


class GitWorktree:
    """Manage git worktrees for isolated task execution."""

    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path.resolve()

    def create(self, name: str, branch: str | None = None) -> dict[str, Any]:
        """Create a new worktree at ../{name}/ checked out to wt/{name}."""
        if not valid_name(name):
            raise ValueError(f"Invalid worktree name: {name}")

        branch = branch or f"wt/{name}"
        worktree_path = self.repo_path.parent / name

        if worktree_path.exists():
            raise FileExistsError(f"Worktree already exists: {worktree_path}")

        result = subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(worktree_path), "HEAD"],
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git worktree add failed: {result.stderr.strip()}"
            )

        return {
            "name": name,
            "branch": branch,
            "path": str(worktree_path),
        }

    def remove(self, name: str, force: bool = False) -> dict[str, Any]:
        """Remove a worktree by name."""
        if not valid_name(name):
            raise ValueError(f"Invalid worktree name: {name}")

        worktree_path = self.repo_path.parent / name
        cmd = ["git", "worktree", "remove"]
        if force:
            cmd.append("--force")
        cmd.append(str(worktree_path))

        result = subprocess.run(
            cmd,
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git worktree remove failed: {result.stderr.strip()}"
            )

        return {"name": name, "removed": True}

    def list_worktrees(self) -> list[dict[str, Any]]:
        """List all worktrees."""
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []
        return self._parse_porcelain(result.stdout)

    def _parse_porcelain(self, output: str) -> list[dict[str, Any]]:
        """Parse `git worktree list --porcelain` output."""
        worktrees: list[dict[str, Any]] = []
        current: dict[str, Any] = {}
        for line in output.strip().split("\n"):
            line = line.strip()
            if not line:
                if current:
                    worktrees.append(current)
                    current = {}
                continue
            if line.startswith("worktree "):
                current["path"] = line[len("worktree "):]
            elif line.startswith("HEAD "):
                current["head"] = line[len("HEAD "):]
            elif line.startswith("branch "):
                current["branch"] = line[len("branch "):]
            elif line.startswith("bare"):
                current["bare"] = True
            elif line.startswith("detached"):
                current["detached"] = True
        if current:
            worktrees.append(current)
        return worktrees

    def exists(self, name: str) -> bool:
        """Check if a worktree exists."""
        worktree_path = self.repo_path.parent / name
        return worktree_path.exists() and worktree_path.is_dir()
