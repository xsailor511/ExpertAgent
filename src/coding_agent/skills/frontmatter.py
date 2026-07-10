from __future__ import annotations

from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, Any] = {}
    if yaml is not None:
        try:
            meta = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            meta = {}
    return meta, parts[2].strip()
