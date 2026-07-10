from __future__ import annotations

import json
from pathlib import Path

from coding_agent.tasks.models import Task

TASKS_DIR = Path(".tasks")


class TaskStore:
    def __init__(self, tasks_dir: Path = TASKS_DIR):
        self.tasks_dir = tasks_dir
        self.tasks_dir.mkdir(exist_ok=True)

    def _path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.json"

    def save(self, task: Task) -> None:
        self._path(task.id).write_text(
            json.dumps(task.to_dict(), indent=2), encoding="utf-8"
        )

    def load(self, task_id: str) -> Task:
        return Task(**json.loads(self._path(task_id).read_text("utf-8")))

    def list_all(self) -> list[Task]:
        tasks = []
        for path in sorted(self.tasks_dir.glob("*.json")):
            tasks.append(Task(**json.loads(path.read_text("utf-8"))))
        return tasks

    def delete(self, task_id: str) -> None:
        self._path(task_id).unlink(missing_ok=True)
