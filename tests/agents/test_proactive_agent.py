"""Regression tests for proactive scheduling and notification setup."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openjarvis.agents.proactive_agent import (
    _PROACTIVE_CRON_PROMPT,
    _build_notification_channel,
    register_cron,
)
from openjarvis.core.registry import ChannelRegistry
from openjarvis.scheduler.scheduler import TaskScheduler
from openjarvis.scheduler.store import SchedulerStore


@pytest.fixture()
def scheduler(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.db")
    scheduler = TaskScheduler(store)
    yield scheduler
    scheduler.stop()
    store.close()


def _register(scheduler, *, schedule="0 5 * * *", channel="telegram:123"):
    return register_cron(
        scheduler,
        notification_channel_id=channel,
        cron_expr=schedule,
        hours_back=24,
        timezone="UTC",
    )


class TestRegisterCron:
    def test_reuses_exact_task_and_cancels_duplicates(self, scheduler):
        first = _register(scheduler)
        duplicate = scheduler.create_task(
            _PROACTIVE_CRON_PROMPT,
            "cron",
            "0 5 * * *",
            agent="proactive",
            metadata=first.metadata,
        )

        returned = _register(scheduler)

        assert returned.id in {first.id, duplicate.id}
        assert [task.id for task in scheduler.list_tasks(status="active")] == [
            returned.id
        ]
        cancelled_id = scheduler.list_tasks(status="cancelled")[0].id
        assert cancelled_id == ({first.id, duplicate.id} - {returned.id}).pop()

    def test_replaces_task_when_configuration_changes(self, scheduler):
        old = _register(scheduler, schedule="0 5 * * *", channel="telegram:old")

        new = _register(scheduler, schedule="0 7 * * *", channel="telegram:new")

        assert new.id != old.id
        assert new.schedule_value == "0 7 * * *"
        assert new.metadata["notification_channel_id"] == "telegram:new"
        assert scheduler.list_tasks(status="cancelled")[0].id == old.id

    def test_preserves_pause_across_restart(self, scheduler):
        paused = _register(scheduler)
        scheduler.pause_task(paused.id)

        returned = _register(scheduler, schedule="0 7 * * *")

        assert returned.id == paused.id
        assert returned.status == "paused"
        assert scheduler.list_tasks(status="active") == []

    def test_migrates_legacy_tasks_without_stable_key(self, scheduler):
        legacy = scheduler.create_task(
            _PROACTIVE_CRON_PROMPT,
            "cron",
            "0 5 * * *",
            agent="proactive",
            metadata={
                "notification_channel_id": "telegram:123",
                "hours_back": 24,
                "timezone": "UTC",
            },
        )

        current = _register(scheduler)

        assert current.id != legacy.id
        assert current.metadata["openjarvis_task_key"] == "proactive-daily"
        assert scheduler.list_tasks(status="cancelled")[0].id == legacy.id


class TestNotificationChannel:
    def test_telegram_is_configured_without_starting_polling(self):
        class FakeTelegram:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.connect = MagicMock()

        config = MagicMock()
        with (
            patch.object(ChannelRegistry, "contains", return_value=True),
            patch.object(ChannelRegistry, "get", return_value=FakeTelegram),
            patch("openjarvis.core.config.load_config", return_value=config),
            patch(
                "openjarvis.system._channel_kwargs.build_channel_kwargs",
                return_value={"bot_token": "configured-token"},
            ),
        ):
            channel = _build_notification_channel("telegram:123")

        assert channel.kwargs == {"bot_token": "configured-token"}
        channel.connect.assert_not_called()

    def test_non_telegram_channel_keeps_connect_lifecycle(self):
        class FakeChannel:
            def __init__(self, **kwargs):
                self.connect = MagicMock()

        with (
            patch.object(ChannelRegistry, "contains", return_value=True),
            patch.object(ChannelRegistry, "get", return_value=FakeChannel),
        ):
            channel = _build_notification_channel("twilio:15551234567")

        channel.connect.assert_called_once_with()
