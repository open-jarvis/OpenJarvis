"""Tests for TaskScheduler — scheduling logic, lifecycle, and execution."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Event
from unittest.mock import MagicMock

import pytest

from openjarvis.scheduler.scheduler import ScheduledTask, TaskScheduler
from openjarvis.scheduler.store import SchedulerStore


@pytest.fixture()
def store(tmp_path):
    s = SchedulerStore(tmp_path / "scheduler_test.db")
    yield s
    s.close()


@pytest.fixture()
def scheduler(store):
    sched = TaskScheduler(store, poll_interval=1)
    yield sched
    sched.stop()


# -- ScheduledTask dataclass -------------------------------------------------


class TestScheduledTask:
    def test_round_trip(self):
        task = ScheduledTask(
            id="abc123",
            prompt="hello",
            schedule_type="interval",
            schedule_value="60",
            agent="orchestrator",
            tools="calculator,think",
            metadata={"key": "value"},
        )
        d = task.to_dict()
        restored = ScheduledTask.from_dict(d)
        assert restored.id == "abc123"
        assert restored.prompt == "hello"
        assert restored.schedule_type == "interval"
        assert restored.agent == "orchestrator"
        assert restored.tools == "calculator,think"
        assert restored.metadata == {"key": "value"}

    def test_defaults(self):
        task = ScheduledTask(
            id="x",
            prompt="p",
            schedule_type="once",
            schedule_value="2026-01-01T00:00:00",
        )
        assert task.context_mode == "isolated"
        assert task.status == "active"
        assert task.agent == "simple"
        assert task.tools == ""
        assert task.metadata == {}


# -- TaskScheduler create/list -----------------------------------------------


class TestCreateAndList:
    def test_create_task(self, scheduler):
        task = scheduler.create_task(
            prompt="hello world",
            schedule_type="interval",
            schedule_value="3600",
        )
        assert task.id
        assert task.prompt == "hello world"
        assert task.schedule_type == "interval"
        assert task.next_run is not None
        assert task.status == "active"

    def test_create_task_with_agent_and_tools(self, scheduler):
        task = scheduler.create_task(
            prompt="hello",
            schedule_type="once",
            schedule_value="2099-01-01T00:00:00+00:00",
            agent="orchestrator",
            tools="calculator,think",
        )
        assert task.agent == "orchestrator"
        assert task.tools == "calculator,think"

    def test_list_tasks_empty(self, scheduler):
        assert scheduler.list_tasks() == []

    def test_list_tasks(self, scheduler):
        scheduler.create_task("a", "interval", "60")
        scheduler.create_task("b", "interval", "120")
        assert len(scheduler.list_tasks()) == 2

    def test_list_tasks_filter_status(self, scheduler):
        t1 = scheduler.create_task("a", "interval", "60")
        scheduler.create_task("b", "interval", "120")
        scheduler.pause_task(t1.id)
        active = scheduler.list_tasks(status="active")
        paused = scheduler.list_tasks(status="paused")
        assert len(active) == 1
        assert len(paused) == 1


# -- Pause / resume / cancel -------------------------------------------------


class TestPauseResumeCancel:
    def test_pause_task(self, scheduler):
        task = scheduler.create_task("test", "interval", "60")
        scheduler.pause_task(task.id)
        tasks = scheduler.list_tasks(status="paused")
        assert len(tasks) == 1
        assert tasks[0].status == "paused"

    def test_resume_task(self, scheduler):
        task = scheduler.create_task("test", "interval", "60")
        scheduler.pause_task(task.id)
        scheduler.resume_task(task.id)
        tasks = scheduler.list_tasks(status="active")
        assert len(tasks) == 1

    def test_cancel_task(self, scheduler):
        task = scheduler.create_task("test", "interval", "60")
        scheduler.cancel_task(task.id)
        tasks = scheduler.list_tasks(status="cancelled")
        assert len(tasks) == 1
        assert tasks[0].next_run is None

    def test_pause_nonexistent(self, scheduler):
        with pytest.raises(KeyError):
            scheduler.pause_task("nonexistent")

    def test_resume_nonexistent(self, scheduler):
        with pytest.raises(KeyError):
            scheduler.resume_task("nonexistent")

    def test_cancel_nonexistent(self, scheduler):
        with pytest.raises(KeyError):
            scheduler.cancel_task("nonexistent")


# -- _compute_next_run -------------------------------------------------------


class TestComputeNextRun:
    def test_interval(self, scheduler):
        task = ScheduledTask(
            id="t", prompt="p", schedule_type="interval", schedule_value="300"
        )
        next_run = scheduler._compute_next_run(task)
        assert next_run is not None
        # Should be roughly 300 seconds from now
        parsed = datetime.fromisoformat(next_run)
        diff = (parsed - datetime.now(timezone.utc)).total_seconds()
        assert 295 <= diff <= 310

    def test_once_not_yet_run(self, scheduler):
        target = "2099-06-15T12:00:00+00:00"
        task = ScheduledTask(
            id="t",
            prompt="p",
            schedule_type="once",
            schedule_value=target,
            last_run=None,
        )
        next_run = scheduler._compute_next_run(task)
        assert next_run == target

    @pytest.mark.parametrize(
        ("supplied", "expected"),
        [
            ("2099-01-02T00:30:00+01:00", "2099-01-01T23:30:00+00:00"),
            ("2099-01-01T23:30:00-05:00", "2099-01-02T04:30:00+00:00"),
            ("2099-01-01T23:30:00", "2099-01-01T23:30:00+00:00"),
        ],
    )
    def test_once_is_stored_in_utc(self, scheduler, supplied, expected):
        task = scheduler.create_task("test", "once", supplied)
        assert task.next_run == expected
        assert scheduler.list_tasks()[0].next_run == expected

    def test_once_already_run(self, scheduler):
        task = ScheduledTask(
            id="t",
            prompt="p",
            schedule_type="once",
            schedule_value="2099-06-15T12:00:00+00:00",
            last_run="2099-06-15T12:01:00+00:00",
        )
        next_run = scheduler._compute_next_run(task)
        assert next_run is None

    def test_cron_fallback(self, scheduler):
        task = ScheduledTask(
            id="t",
            prompt="p",
            schedule_type="cron",
            schedule_value="30 2 * * *",
        )
        next_run = scheduler._compute_next_run(task)
        assert next_run is not None

    def test_cron_honors_metadata_timezone(self, scheduler, monkeypatch):
        fixed_now = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)

        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now if tz is not None else fixed_now.replace(tzinfo=None)

        task = ScheduledTask(
            id="t",
            prompt="p",
            schedule_type="cron",
            schedule_value="0 5 * * *",
            metadata={"timezone": "America/Los_Angeles"},
        )
        monkeypatch.setattr("openjarvis.scheduler.scheduler.datetime", FixedDatetime)

        next_run = scheduler._compute_next_run(task)

        assert next_run == "2026-01-15T13:00:00+00:00"

    def test_cron_without_dependency_fails_loudly(self, scheduler, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def without_croniter(name, *args, **kwargs):
            if name == "croniter":
                raise ImportError("blocked for test")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", without_croniter)
        with pytest.raises(RuntimeError, match="croniter is required"):
            scheduler._compute_next_cron(
                "0 5 * * *",
                datetime(2026, 1, 15, tzinfo=timezone.utc),
            )

    def test_unknown_type(self, scheduler):
        task = ScheduledTask(
            id="t", prompt="p", schedule_type="unknown", schedule_value="x"
        )
        assert scheduler._compute_next_run(task) is None


# -- _execute_task -----------------------------------------------------------


class TestExecuteTask:
    def test_execute_with_system(self, store):
        mock_system = MagicMock()
        mock_system.ask.return_value = {"content": "result text", "usage": {}}
        sched = TaskScheduler(store, system=mock_system, poll_interval=1)

        task = sched.create_task("what is 2+2?", "once", "2026-01-01T00:00:00+00:00")
        sched._execute_task(task)

        mock_system.ask.assert_called_once()
        call_args = mock_system.ask.call_args
        assert call_args[0][0] == "what is 2+2?"

        # Check that a run log was recorded
        logs = store.get_run_logs(task.id)
        assert len(logs) == 1
        assert logs[0]["success"] == 1
        assert logs[0]["result"] == "result text"

    def test_execute_without_system(self, store):
        sched = TaskScheduler(store, poll_interval=1)
        task = sched.create_task("dry run", "once", "2026-01-01T00:00:00+00:00")
        with pytest.raises(RuntimeError, match="execution system"):
            sched.start()
        with pytest.raises(RuntimeError, match="execution system"):
            sched._execute_task(task)
        assert store.get_run_logs(task.id) == []
        assert store.get_task(task.id)["status"] == "active"
        assert store.get_task(task.id)["next_run"] == task.next_run

    def test_execute_with_error(self, store):
        mock_system = MagicMock()
        mock_system.ask.side_effect = RuntimeError("engine down")
        sched = TaskScheduler(store, system=mock_system, poll_interval=1)

        task = sched.create_task("fail", "once", "2026-01-01T00:00:00+00:00")
        sched._execute_task(task)

        logs = store.get_run_logs(task.id)
        assert len(logs) == 1
        assert logs[0]["success"] == 0
        assert "engine down" in logs[0]["error"]

    def test_execute_does_not_log_system_error_as_success(self, store):
        mock_system = MagicMock()
        mock_system.ask.return_value = {
            "content": "Unknown agent: missing",
            "error": True,
        }
        sched = TaskScheduler(store, system=mock_system)
        task = sched.create_task("hello", "once", "2026-01-01T00:00:00Z")
        sched._execute_task(task)

        log = store.get_run_logs(task.id)[0]
        assert log["success"] == 0
        assert log["error"] == "Unknown agent: missing"

    def test_execute_publishes_events(self, store):
        mock_bus = MagicMock()
        sched = TaskScheduler(store, system=MagicMock(), bus=mock_bus, poll_interval=1)
        task = sched.create_task("test", "once", "2026-01-01T00:00:00+00:00")
        sched._execute_task(task)

        assert mock_bus.publish.call_count == 2
        start_call = mock_bus.publish.call_args_list[0]
        end_call = mock_bus.publish.call_args_list[1]
        assert start_call[0][0] == "scheduler_task_start"
        assert end_call[0][0] == "scheduler_task_end"

    def test_execute_once_task_completed_after_run(self, store):
        sched = TaskScheduler(store, system=MagicMock(), poll_interval=1)
        task = sched.create_task("one-shot", "once", "2026-01-01T00:00:00+00:00")
        sched._execute_task(task)

        updated = store.get_task(task.id)
        assert updated["status"] == "completed"
        assert updated["next_run"] is None

    def test_execute_with_tools(self, store):
        mock_system = MagicMock()
        mock_system.ask.return_value = "4"
        sched = TaskScheduler(store, system=mock_system, poll_interval=1)

        task = sched.create_task(
            "what is 2+2?",
            "once",
            "2026-01-01T00:00:00+00:00",
            tools="calculator,think",
        )
        sched._execute_task(task)

        call_kwargs = mock_system.ask.call_args[1]
        assert call_kwargs["tools"] == ["calculator", "think"]


# -- Start / stop lifecycle ---------------------------------------------------


class TestLifecycle:
    def test_start_stop(self, store):
        scheduler = TaskScheduler(store, system=MagicMock(), poll_interval=1)
        scheduler.start()
        assert scheduler._thread is not None
        assert scheduler._thread.is_alive()
        scheduler.stop()
        assert not scheduler._thread

    def test_double_start(self, store):
        scheduler = TaskScheduler(store, system=MagicMock(), poll_interval=1)
        scheduler.start()
        t1 = scheduler._thread
        scheduler.start()  # Should not create a second thread
        assert scheduler._thread is t1
        scheduler.stop()

    def test_poll_loop_finds_due_tasks(self, store):
        system = MagicMock()
        ran = Event()
        system.ask.side_effect = lambda *args, **kwargs: ran.set() or "done"
        sched = TaskScheduler(store, system=system, poll_interval=1)
        task = sched.create_task("immediate", "once", "2020-01-01T00:00:00+00:00")
        sched.start()
        try:
            assert ran.wait(3)
        finally:
            assert sched.stop(timeout=3)
        assert store.get_run_logs(task.id)[0]["result"] == "done"

    def test_workers_do_not_share_a_database(self, tmp_path):
        first_store = SchedulerStore(tmp_path / "shared.db")
        second_store = SchedulerStore(tmp_path / "shared.db")
        first = TaskScheduler(first_store, system=MagicMock())
        second = TaskScheduler(second_store, system=MagicMock())
        first.start()
        try:
            with pytest.raises(RuntimeError, match="already running"):
                second.start()
            assert first.stop(timeout=3)
            second.start()
        finally:
            assert first.stop(timeout=3)
            assert second.stop(timeout=3)
            first_store.close()
            second_store.close()
