"""Code search — wraps Indexer with scope-aware lookup."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from coding_agent.codebase.indexer import Indexer


class CodeSearch:
    """Higher-level code search with scope support."""

    def __init__(self, root: Path) -> None:
        self.indexer = Indexer(root)

    def ensure_indexed(self) -> None:
        """Run indexing if not already done."""
        self.indexer.index()

    def find_symbol(self, name: str, scope: str | None = None) -> list[dict[str, Any]]:
        """Find a symbol by exact name match."""
        q = name.lower()
        results = []
        for sym in self.indexer.symbols:
            if sym["name"].lower() == q:
                if scope and scope not in sym["file"]:
                    continue
                results.append(sym)
        return results

    def search(self, query: str, scope: str | None = None) -> list[dict[str, Any]]:
        """Search symbols by substring match."""
        return self.indexer.search(query, scope=scope)

    def file_symbols(self, file_path: str | Path) -> list[dict[str, Any]]:
        """List all indexed symbols in a file."""
        return self.indexer.file_summary(file_path)

    def stats(self) -> dict[str, Any]:
        """Get indexing stats."""
        syms = self.indexer.symbols
        files = {s["file"] for s in syms}
        types: dict[str, int] = {}
        for s in syms:
            t = s.get("type", "unknown")
            types[t] = types.get(t, 0) + 1
        return {
            "total_symbols": len(syms),
            "total_files": len(files),
            "by_type": types,
        }
