"""Tree-sitter-based codebase indexer."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    from tree_sitter_languages import get_language, get_parser
    HAS_TS = True
except ImportError:
    HAS_TS = False


LANG_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".jsx": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "c_sharp",
}

# Simple fallback regex for when tree-sitter isn't available
FALLBACK_PATTERNS: dict[str, list[re.Pattern]] = {
    ".py": [
        re.compile(r"^class\s+(\w+)"),
        re.compile(r"^(?:async\s+)?def\s+(\w+)"),
    ],
    ".js": [
        re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)"),
        re.compile(r"^(?:export\s+)?class\s+(\w+)"),
        re.compile(r"^\s*(?:const|let|var)\s+(\w+)\s*="),
    ],
    ".ts": [
        re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)"),
        re.compile(r"^(?:export\s+)?class\s+(\w+)"),
        re.compile(r"^(?:export\s+)?interface\s+(\w+)"),
        re.compile(r"^(?:export\s+)?type\s+(\w+)"),
    ],
    ".rs": [
        re.compile(r"^pub\s+(?:unsafe\s+)?fn\s+(\w+)"),
        re.compile(r"^pub\s+(?:unsafe\s+)?trait\s+(\w+)"),
        re.compile(r"^pub\s+struct\s+(\w+)"),
        re.compile(r"^pub\s+enum\s+(\w+)"),
    ],
}


def _extract_fallback(file_path: Path, content: str) -> list[dict[str, Any]]:
    """Extract symbols using regex fallback."""
    ext = file_path.suffix.lower()
    patterns = FALLBACK_PATTERNS.get(ext, [])
    symbols: list[dict[str, Any]] = []
    for i, line in enumerate(content.split("\n"), 1):
        stripped = line.strip()
        for pat in patterns:
            m = pat.match(stripped)
            if m:
                symbols.append({
                    "name": m.group(1),
                    "type": "symbol",
                    "line": i,
                    "file": str(file_path),
                })
                break
    return symbols


class Indexer:
    """Codebase indexer using tree-sitter for accurate symbol extraction."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._symbols: list[dict[str, Any]] = []
        self._dirty = True

    def index(self) -> None:
        """Index all supported source files under root."""
        self._symbols = []
        for file_path in sorted(self.root.rglob("*")):
            if not file_path.is_file():
                continue
            ext = file_path.suffix.lower()
            if ext not in LANG_MAP:
                continue
            try:
                content = file_path.read_text("utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue
            symbols = self._index_file(file_path, content)
            self._symbols.extend(symbols)
        self._dirty = False

    def _index_file(self, file_path: Path, content: str) -> list[dict[str, Any]]:
        """Index a single file using tree-sitter or regex fallback."""
        ext = file_path.suffix.lower()
        lang_name = LANG_MAP.get(ext)
        if not lang_name:
            return []

        if HAS_TS:
            try:
                return self._index_ts(file_path, content, lang_name)
            except Exception:
                pass  # Fall through to regex

        return _extract_fallback(file_path, content)

    def _index_ts(
        self, file_path: Path, content: str, lang_name: str
    ) -> list[dict[str, Any]]:
        """Index a file using tree-sitter."""
        try:
            language = get_language(lang_name)
            parser = get_parser(lang_name)
        except Exception:
            return _extract_fallback(file_path, content)

        tree = parser.parse(bytes(content, "utf-8"))

        # Define query patterns for common symbol types
        # These are simple structural queries, not exhaustive
        query_strings: list[tuple[str, str]] = [
            ("function_definition", "function"),
            ("method_definition", "method"),
            ("class_definition", "class"),
            ("interface_declaration", "interface"),
        ]

        symbols: list[dict[str, Any]] = []
        for query_name, symbol_type in query_strings:
            try:
                # Build a simple query to find nodes by type
                qs = f"([{query_name}] @{query_name})"
                query = language.query(qs)
                captures = query.captures(tree.root_node)

                for node, _tag in captures.get(query_name, []):
                    name_node = _find_name_node(node)
                    name = (
                        content[node.start_byte:node.end_byte]
                        if name_node is None
                        else content[name_node.start_byte:name_node.end_byte]
                    )
                    symbols.append({
                        "name": name,
                        "type": symbol_type,
                        "line": node.start_point[0] + 1,
                        "file": str(file_path),
                    })
            except Exception:
                continue

        return symbols

    @property
    def symbols(self) -> list[dict[str, Any]]:
        if self._dirty:
            self.index()
        return self._symbols

    def search(self, query: str, scope: str | None = None) -> list[dict[str, Any]]:
        """Search indexed symbols by name (substring match)."""
        q = query.lower()
        results = []
        for sym in self.symbols:
            if q in sym["name"].lower():
                if scope and scope not in sym["file"]:
                    continue
                results.append(sym)
        return results

    def file_summary(self, file_path: str | Path) -> list[dict[str, Any]]:
        """Get all indexed symbols from a specific file."""
        file_str = str(file_path).replace("\\", "/")
        return [
            sym for sym in self.symbols
            if sym["file"].replace("\\", "/") == file_str
        ]


def _find_name_node(node: Any) -> Any | None:
    """Find the 'name' child of a syntax node."""
    for child in node.children:
        if child.type == "identifier":
            return child
        if child.type == "name":
            return child
    return None
