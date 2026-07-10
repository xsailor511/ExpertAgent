from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from coding_agent.core.cron import CronJob, CronScheduler, _parse_field, match_cron


class TestParseField:
    def test_star(self):
        assert _parse_field("*", 0, 59) == set(range(0, 60))

    def test_single(self):
        assert _parse_field("5", 0, 59) == {5}

    def test_range(self):
        assert _parse_field("1-5", 1, 31) == {1, 2, 3, 4, 5}

    def test_step(self):
        result = _parse_field("*/10", 0, 59)
        assert 0 in result
        assert 10 in result
        assert 50 in result

    def test_list(self):
        assert _parse_field("1,3,5", 1, 7) == {1, 3, 5}

    def test_out_of_range_excluded(self):
        result = _parse_field("1-100", 1, 31)
        assert max(result) == 31


class TestMatchCron:
    def test_every_minute(self):
        dt = datetime(2024, 1, 15, 10, 30, tzinfo=UTC)
        assert match_cron("* * * * *", dt)

    def test_specific_hour(self):
        dt = datetime(2024, 1, 15, 14, 0, tzinfo=UTC)
        assert match_cron("0 14 * * *", dt)

    def test_not_matching_hour(self):
        dt = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
        assert not match_cron("0 14 * * *", dt)

    def test_specific_day_of_week(self):
        # 2024-01-15 is a Monday (weekday()=0)
        dt = datetime(2024, 1, 15, 0, 0, tzinfo=UTC)
        assert match_cron("0 0 * * 1", dt)
        assert not match_cron("0 0 * * 0", dt)

    def test_invalid_expr_raises(self):
        with pytest.raises(ValueError):
            match_cron("* * *", datetime.now(UTC))


class TestCronJob:
    def test_should_fire_matches_time(self):
        dt = datetime(2024, 1, 15, 10, 30, tzinfo=UTC)
        job = CronJob(id="test1", expr="30 10 * * *", prompt="hello")
        assert job.should_fire(dt)

    def test_should_not_fire_disabled(self):
        dt = datetime(2024, 1, 15, 10, 30, tzinfo=UTC)
        job = CronJob(id="test2", expr="30 10 * * *", prompt="hello", enabled=False)
        assert not job.should_fire(dt)

    def test_should_not_fire_twice_within_30s(self):
        dt = datetime(2024, 1, 15, 10, 30, tzinfo=UTC)
        job = CronJob(id="test3", expr="30 10 * * *", prompt="hello")
        assert job.should_fire(dt)
        job.last_fired = dt.timestamp()
        assert not job.should_fire(dt)


class TestCronScheduler:
    def test_add_and_list(self, tmp_path: Path):
        cron_file = tmp_path / "tasks.json"
        sched = CronScheduler(cron_file=cron_file)
        job = CronJob(id="j1", expr="0 * * * *", prompt="hourly")
        sched.add(job)
        jobs = sched.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == "j1"

    def test_remove(self, tmp_path: Path):
        cron_file = tmp_path / "tasks.json"
        sched = CronScheduler(cron_file=cron_file)
        sched.add(CronJob(id="j1", expr="0 * * * *", prompt="hourly"))
        assert sched.remove("j1")
        assert not sched.remove("nonexistent")
        assert sched.list_jobs() == []

    def test_get(self, tmp_path: Path):
        cron_file = tmp_path / "tasks.json"
        sched = CronScheduler(cron_file=cron_file)
        sched.add(CronJob(id="j1", expr="* * * * *", prompt="every min"))
        assert sched.get("j1") is not None
        assert sched.get("none") is None

    def test_pop_fired_empty(self, tmp_path: Path):
        cron_file = tmp_path / "tasks.json"
        sched = CronScheduler(cron_file=cron_file)
        assert sched.pop_fired() == []

    def test_durable_persistence(self, tmp_path: Path):
        cron_file = tmp_path / "tasks.json"
        sched = CronScheduler(cron_file=cron_file)
        sched.add(CronJob(id="j1", expr="0 * * * *", prompt="hourly"))
        del sched

        sched2 = CronScheduler(cron_file=cron_file)
        jobs = sched2.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == "j1"

    def test_to_dict(self):
        job = CronJob(id="j1", expr="* * * * *", prompt="test")
        d = job.to_dict()
        assert d["id"] == "j1"
        assert d["expr"] == "* * * * *"
