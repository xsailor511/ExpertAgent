from __future__ import annotations

import time

from coding_agent.core.background import BackgroundTask, BackgroundTaskManager, is_slow


def test_is_slow_detects_keywords():
    assert is_slow("pip install requests")
    assert is_slow("npm run build")
    assert is_slow("cargo build --release")
    assert is_slow("make all")
    assert not is_slow("echo hello")
    assert not is_slow("ls -la")


def test_is_slow_empty():
    assert not is_slow("")


def test_background_task_create():
    task = BackgroundTask("bg_0001", "echo hello")
    assert task.task_id == "bg_0001"
    assert task.command == "echo hello"
    assert task._result is None
    assert task._error is None


def test_background_task_notification_completed():
    task = BackgroundTask("bg_0001", "echo hello")
    task._result = "hello\n"
    note = task.to_notification()
    assert "completed" in note
    assert "echo hello" in note
    assert "hello" in note


def test_background_task_notification_error():
    task = BackgroundTask("bg_0001", "bad_command")
    task._error = "command not found"
    note = task.to_notification()
    assert "FAILED" in note
    assert "command not found" in note


def test_manager_start_and_collect():
    mgr = BackgroundTaskManager()
    placeholder = mgr.start("echo hello", lambda: "hello")
    assert "bg_0001" in placeholder
    assert "started" in placeholder
    time.sleep(0.1)
    results = mgr.collect_results()
    assert len(results) >= 1
    assert "bg_0001" in results[0]


def test_collect_returns_empty_when_none():
    mgr = BackgroundTaskManager()
    assert mgr.collect_results() == []


def test_is_pending():
    mgr = BackgroundTaskManager()
    mgr.start("echo hi", lambda: "hi")
    assert mgr.is_pending("bg_0001")
    assert not mgr.is_pending("bg_9999")
