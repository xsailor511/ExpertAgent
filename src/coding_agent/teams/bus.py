from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MAILBOXES_DIR = Path(".mailboxes")


class MessageBus:
    """Append-only JSONL mailboxes. Each agent gets one file.

    send(recipient, msg) appends to recipient's mailbox.
    read(agent_id) returns all messages and clears the mailbox.
    """

    def __init__(self, mailboxes_dir: Path = MAILBOXES_DIR) -> None:
        self._dir = mailboxes_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, agent_id: str) -> Path:
        return self._dir / f"{agent_id}.jsonl"

    def send(self, recipient: str, msg: dict[str, Any]) -> None:
        """Append a message to the recipient's mailbox."""
        path = self._path(recipient)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    def read(self, agent_id: str) -> list[dict[str, Any]]:
        """Read all messages and clear the mailbox."""
        path = self._path(agent_id)
        if not path.exists():
            return []
        messages: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    try:
                        messages.append(json.loads(stripped))
                    except json.JSONDecodeError:
                        continue
        path.write_text("", encoding="utf-8")
        return messages

    def count(self, agent_id: str) -> int:
        """Count messages without consuming them."""
        path = self._path(agent_id)
        if not path.exists():
            return 0
        count = 0
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count
