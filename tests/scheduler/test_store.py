"""Tests for SchedulerStore — SQLite CRUD for scheduled tasks and run logs."""

from __future__ import annotations

import pytest

from openjarvis.scheduler.store import SchedulerStore


@pytest.fixture()
def store(tmp_path):
    """Create a SchedulerStore backed by a temporary SQLite database."""
    s = SchedulerStore(tmp_path / "scheduler_test.db")
    yield s
    s.close()


def _make_task(task_id: str = "t1", **overrides) -> dict:
    base = {
        "id": task_id,
        "prompt": "summarize the news",
        "schedule_type": "interval",
        "schedule_value": "3600",
        "context_mode": "isolated",
        "status": "active",
        "next_run": "2026-01-01T00:00:00+00:00",
        "last_run": None,
        "agent": "simple",
        "tools": "",
        "metadata": {},
    }
    base.update(overrides)
    return base


# -- Task CRUD ---------------------------------------------------------------


class TestTaskCRUD:
    def test_save_and_get(self, store):
        task = _make_task()
        store.save_task(task)
        got = store.get_task("t1")
        assert got is not None
        assert got["id"] == "t1"
        assert got["prompt"] == "summarize the news"
        assert got["schedule_type"] == "interval"
        assert got["schedule_value"] == "3600"

    def test_get_missing_returns_none(self, store):
        assert store.get_task("nonexistent") is None

    def test_list_tasks_all(self, store):
        store.save_task(_make_task("t1"))
        store.save_task(_make_task("t2", status="paused"))
        store.save_task(_make_task("t3", status="completed"))
        all_tasks = store.list_tasks()
        assert len(all_tasks) == 3

    def test_list_tasks_filtered(self, store):
        store.save_task(_make_task("t1", status="active"))
        store.save_task(_make_task("t2", status="paused"))
        store.save_task(_make_task("t3", status="active"))
        active = store.list_tasks(status="active")
        assert len(active) == 2
        paused = store.list_tasks(status="paused")
        assert len(paused) == 1

    def test_update_task(self, store):
        task = _make_task()
        store.save_task(task)
        task["status"] = "paused"
        store.update_task(task)
        got = store.get_task("t1")
        assert got["status"] == "paused"

    def test_delete_task(self, store):
        store.save_task(_make_task())
        store.delete_task("t1")
        assert store.get_task("t1") is None

    def test_metadata_serialized_as_json(self, store):
        task = _make_task(metadata={"key": "value", "count": 42})
        store.save_task(task)
        got = store.get_task("t1")
        assert got["metadata"] == {"key": "value", "count": 42}


# -- Due tasks ---------------------------------------------------------------


class TestDueTasks:
    def test_get_due_tasks(self, store):
        store.save_task(_make_task("t1", next_run="2026-01-01T00:00:00+00:00"))
        store.save_task(_make_task("t2", next_run="2026-06-01T00:00:00+00:00"))
        store.save_task(_make_task("t3", next_run="2026-03-01T00:00:00+00:00"))
        due = store.get_due_tasks("2026-03-15T00:00:00+00:00")
        ids = {d["id"] for d in due}
        assert "t1" in ids
        assert "t3" in ids
        assert "t2" not in ids

    def test_due_tasks_excludes_paused(self, store):
        store.save_task(
            _make_task("t1", next_run="2026-01-01T00:00:00+00:00", status="paused")
        )
        due = store.get_due_tasks("2026-06-01T00:00:00+00:00")
        assert len(due) == 0

    def test_due_tasks_excludes_null_next_run(self, store):
        store.save_task(_make_task("t1", next_run=None))
        due = store.get_due_tasks("2026-06-01T00:00:00+00:00")
        assert len(due) == 0


# -- Run logs ----------------------------------------------------------------


class TestRunLogs:
    def test_log_run_and_retrieve(self, store):
        store.save_task(_make_task())
        store.log_run(
            task_id="t1",
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:01:00+00:00",
            success=True,
            result="Done",
            error="",
        )
        logs = store.get_run_logs("t1")
        assert len(logs) == 1
        assert logs[0]["success"] == 1
        assert logs[0]["result"] == "Done"

    def test_log_run_failure(self, store):
        store.save_task(_make_task())
        store.log_run(
            task_id="t1",
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:01:00+00:00",
            success=False,
            result="",
            error="Connection timeout",
        )
        logs = store.get_run_logs("t1")
        assert len(logs) == 1
        assert logs[0]["success"] == 0
        assert logs[0]["error"] == "Connection timeout"

    def test_log_run_limit(self, store):
        store.save_task(_make_task())
        for i in range(20):
            store.log_run(
                task_id="t1",
                started_at=f"2026-01-{i + 1:02d}T00:00:00+00:00",
                finished_at=f"2026-01-{i + 1:02d}T00:01:00+00:00",
                success=True,
            )
        logs = store.get_run_logs("t1", limit=5)
        assert len(logs) == 5

    def test_get_run_logs_empty(self, store):
        logs = store.get_run_logs("nonexistent")
        assert logs == []
