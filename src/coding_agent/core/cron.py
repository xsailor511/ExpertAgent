"""Cron scheduler — 5-field cron expression parser with durable job scheduling."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

CRON_FILE = Path(".scheduled_tasks.json")


def _parse_field(value: str, min_v: int, max_v: int) -> set[int]:
    """Parse a single cron field (supports *, ranges, steps, lists)."""
    if value == "*":
        return set(range(min_v, max_v + 1))

    values: set[int] = set()
    parts = value.split(",")
    for part in parts:
        if "/" in part:
            base, step = part.split("/", 1)
            step = int(step)
            if base == "*":
                values.update(range(min_v, max_v + 1, step))
            else:
                r_min, r_max = (int(x) for x in base.split("-"))
                values.update(range(r_min, r_max + 1, step))
        elif "-" in part:
            a, b = (int(x) for x in part.split("-"))
            values.update(range(a, b + 1))
        else:
            values.add(int(part))

    return {v for v in values if min_v <= v <= max_v}


def match_cron(expr: str, dt: datetime | None = None) -> bool:
    """Check if a 5-field cron expression matches the given time (default: now local)."""
    dt = dt or datetime.now()
    fields = expr.strip().split()
    if len(fields) != 5:
        raise ValueError(f"Expected 5 fields, got {len(fields)}: {expr}")

    field_parsers = [
        (fields[0], 0, 59),  # minute
        (fields[1], 0, 23),  # hour
        (fields[2], 1, 31),  # day of month
        (fields[3], 1, 12),  # month
        (fields[4], 0, 6),   # day of week (0=Sun)
    ]

    # Python weekday(): 0=Mon..6=Sun → cron: 0=Sun..6=Sat
    cron_dow = (dt.weekday() + 1) % 7
    time_parts = [dt.minute, dt.hour, dt.day, dt.month, cron_dow]

    for idx, (field_str, min_v, max_v) in enumerate(field_parsers):
        if time_parts[idx] not in _parse_field(field_str, min_v, max_v):
            return False

    return True


@dataclass
class CronJob:
    id: str
    expr: str
    prompt: str
    enabled: bool = True
    last_fired: float | None = None

    def should_fire(self, dt: datetime | None = None) -> bool:
        if not self.enabled:
            return False
        dt = dt or datetime.now()
        now_ts = dt.timestamp()
        if self.last_fired is not None and now_ts - self.last_fired < 30:
            return False
        return match_cron(self.expr, dt)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "expr": self.expr,
            "prompt": self.prompt,
            "enabled": self.enabled,
            "last_fired": self.last_fired,
        }


class CronScheduler:
    """Daemon thread cron scheduler with durable persistence."""

    def __init__(self, cron_file: Path = CRON_FILE) -> None:
        self.cron_file = cron_file
        self._jobs: dict[str, CronJob] = {}
        self._fired: list[str] = []
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._load()

    # --- Public API ---

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def add(self, job: CronJob) -> None:
        with self._lock:
            self._jobs[job.id] = job
            self._save()

    def remove(self, job_id: str) -> bool:
        with self._lock:
            if job_id not in self._jobs:
                return False
            del self._jobs[job_id]
            self._save()
            return True

    def list_jobs(self) -> list[CronJob]:
        with self._lock:
            return list(self._jobs.values())

    def pop_fired(self) -> list[str]:
        with self._lock:
            fired = list(self._fired)
            self._fired.clear()
            return fired

    def get(self, job_id: str) -> CronJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    # --- Internal ---

    def _run_loop(self) -> None:
        while self._running:
            now = datetime.now()
            with self._lock:
                for job in self._jobs.values():
                    if job.should_fire(now):
                        job.last_fired = now.timestamp()
                        self._fired.append(f"[Cron {job.id}] {job.prompt}")
                        self._save()
            time.sleep(1)

    def _save(self) -> None:
        data = [job.to_dict() for job in self._jobs.values()]
        self.cron_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if not self.cron_file.exists():
            return
        try:
            data = json.loads(self.cron_file.read_text("utf-8"))
            for item in data:
                job = CronJob(**item)
                self._jobs[job.id] = job
        except (json.JSONDecodeError, KeyError):
            pass
