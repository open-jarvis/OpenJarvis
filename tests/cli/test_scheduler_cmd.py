"""CLI coverage for the task scheduler's database, worker, and timezone."""

from __future__ import annotations

import signal
from threading import Timer
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from openjarvis.cli.scheduler_cmd import scheduler
from openjarvis.core.config import JarvisConfig
from openjarvis.scheduler.scheduler import TaskScheduler
from openjarvis.scheduler.store import SchedulerStore
from openjarvis.system import SystemBuilder


@pytest.fixture
def config(tmp_path, monkeypatch):
    config = JarvisConfig()
    config.scheduler.db_path = str(tmp_path / "tasks.db")
    config.scheduler.poll_interval = 7
    monkeypatch.setattr("openjarvis.core.config.load_config", lambda: config)
    return config


def test_create_cron_with_timezone(config):
    result = CliRunner().invoke(
        scheduler,
        [
            "create",
            "hello",
            "--type",
            "cron",
            "--value",
            "0 8 * * *",
            "--timezone",
            "Europe/Madrid",
        ],
    )
    assert result.exit_code == 0, result.output
    store = SchedulerStore.from_config(config)
    try:
        assert store.list_tasks()[0]["metadata"] == {"timezone": "Europe/Madrid"}
    finally:
        store.close()


@pytest.mark.parametrize(
    ("schedule_type", "value", "timezone_name", "message"),
    [
        ("cron", "0 8 * * *", "Invalid/Timezone", "unknown IANA timezone"),
        ("interval", "60", "Europe/Madrid", "only valid for cron"),
    ],
)
def test_create_rejects_invalid_timezone(
    config,
    schedule_type,
    value,
    timezone_name,
    message,
):
    result = CliRunner().invoke(
        scheduler,
        [
            "create",
            "hello",
            "--type",
            schedule_type,
            "--value",
            value,
            "--timezone",
            timezone_name,
        ],
    )
    assert result.exit_code == 2
    assert message in result.output


def test_start_executes_tasks_through_system(config, monkeypatch):
    store = SchedulerStore.from_config(config)
    task = TaskScheduler(store).create_task("Hello", "once", "2020-01-01T00:00:00Z")
    system = MagicMock()

    def ask(*args, **kwargs):
        # Simulate the signal after this worker has entered the real run path.
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        return {"content": "scheduler result"}

    system.ask.side_effect = ask
    monkeypatch.setattr(SystemBuilder, "build", lambda self: system)

    def unblock_cli():
        handler = signal.getsignal(signal.SIGTERM)
        if callable(handler):
            handler(signal.SIGTERM, None)

    watchdog = Timer(5, unblock_cli)
    watchdog.start()
    try:
        result = CliRunner().invoke(scheduler, ["start"])
        assert result.exit_code == 0, result.output
        assert "poll every 7s" in result.output
        assert store.get_task(task.id)["status"] == "completed"
        assert store.get_run_logs(task.id)[0]["result"] == "scheduler result"
        system.close.assert_called_once()
    finally:
        watchdog.cancel()
        watchdog.join()
        store.close()
