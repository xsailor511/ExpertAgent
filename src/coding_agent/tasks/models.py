from __future__ import annotations

import random
import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Task:
    id: str
    subject: str
    description: str = ""
    status: str = "pending"  # pending | in_progress | completed | cancelled
    owner: str | None = None
    blocked_by: list[str] = field(default_factory=list)
    worktree: str | None = None
    created_at: float = field(default_factory=time.time)

    @staticmethod
    def new_id() -> str:
        return f"task_{int(time.time())}_{random.randint(0, 9999):04d}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
