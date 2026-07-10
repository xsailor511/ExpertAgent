from __future__ import annotations

from coding_agent.tasks.models import Task
from coding_agent.tasks.store import TaskStore


class TaskGraph:
    def __init__(self, store: TaskStore):
        self.store = store

    def can_start(self, task: Task) -> bool:
        for dep_id in task.blocked_by:
            try:
                dep = self.store.load(dep_id)
                if dep.status != "completed":
                    return False
            except FileNotFoundError:
                return False
        return True

    def claimable(self) -> list[Task]:
        return [
            t for t in self.store.list_all()
            if t.status == "pending" and not t.owner and self.can_start(t)
        ]

    def unblocked_by(self, task_id: str) -> list[str]:
        try:
            completed = self.store.load(task_id)
        except FileNotFoundError:
            return []
        if completed.status != "completed":
            return []
        return [
            t.subject for t in self.store.list_all()
            if t.status == "pending"
            and task_id in t.blocked_by
            and self.can_start(t)
        ]
