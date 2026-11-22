"""Tests for scheduler MCP tools."""

from __future__ import annotations

from unittest.mock import MagicMock

from openjarvis.scheduler.scheduler import ScheduledTask
from openjarvis.scheduler.tools import (
    CancelScheduledTaskTool,
    ListScheduledTasksTool,
    PauseScheduledTaskTool,
    ResumeScheduledTaskTool,
    ScheduleTaskTool,
)

# -- Spec correctness --------------------------------------------------------


class TestToolSpecs:
    def test_schedule_task_spec(self):
        tool = ScheduleTaskTool()
        assert tool.spec.name == "schedule_task"
        assert "prompt" in tool.spec.parameters["properties"]
        assert "schedule_type" in tool.spec.parameters["properties"]

    def test_list_spec(self):
        tool = ListScheduledTasksTool()
        assert tool.spec.name == "list_scheduled_tasks"

    def test_pause_spec(self):
        tool = PauseScheduledTaskTool()
        assert tool.spec.name == "pause_scheduled_task"

    def test_resume_spec(self):
        tool = ResumeScheduledTaskTool()
        assert tool.spec.name == "resume_scheduled_task"

    def test_cancel_spec(self):
        tool = CancelScheduledTaskTool()
        assert tool.spec.name == "cancel_scheduled_task"

    def test_all_tools_have_scheduler_category(self):
        for cls in [
            ScheduleTaskTool,
            ListScheduledTasksTool,
            PauseScheduledTaskTool,
            ResumeScheduledTaskTool,
            CancelScheduledTaskTool,
        ]:
            assert cls().spec.category == "scheduler"


# -- Scheduler not available --------------------------------------------------


class TestNoScheduler:
    def test_schedule_task_no_scheduler(self):
        tool = ScheduleTaskTool()
        tool._scheduler = None
        result = tool.execute(
            prompt="hello", schedule_type="once", schedule_value="2026-01-01"
        )
        assert not result.success
        assert "not available" in result.content

    def test_list_no_scheduler(self):
        tool = ListScheduledTasksTool()
        tool._scheduler = None
        result = tool.execute()
        assert not result.success

    def test_pause_no_scheduler(self):
        tool = PauseScheduledTaskTool()
        tool._scheduler = None
        result = tool.execute(task_id="abc")
        assert not result.success

    def test_resume_no_scheduler(self):
        tool = ResumeScheduledTaskTool()
        tool._scheduler = None
        result = tool.execute(task_id="abc")
        assert not result.success

    def test_cancel_no_scheduler(self):
        tool = CancelScheduledTaskTool()
        tool._scheduler = None
        result = tool.execute(task_id="abc")
        assert not result.success


# -- With injected scheduler --------------------------------------------------


class TestWithScheduler:
    def test_schedule_task(self):
        mock_sched = MagicMock()
        mock_sched.create_task.return_value = ScheduledTask(
            id="t123",
            prompt="hello",
            schedule_type="once",
            schedule_value="2026-01-01T00:00:00",
            next_run="2026-01-01T00:00:00",
        )
        tool = ScheduleTaskTool()
        tool._scheduler = mock_sched
        result = tool.execute(
            prompt="hello", schedule_type="once", schedule_value="2026-01-01T00:00:00"
        )
        assert result.success
        assert "t123" in result.content
        mock_sched.create_task.assert_called_once_with(
            prompt="hello",
            schedule_type="once",
            schedule_value="2026-01-01T00:00:00",
            agent="simple",
            tools="",
            metadata={},
        )

    def test_schedule_task_cannot_request_execution_privileges(self):
        tool = ScheduleTaskTool()
        tool._scheduler = MagicMock()
        for overrides in ({"agent": "orchestrator"}, {"tools": "calculator"}):
            result = tool.execute(
                prompt="hello",
                schedule_type="interval",
                schedule_value="3600",
                **overrides,
            )
            assert not result.success
        tool._scheduler.create_task.assert_not_called()

    def test_schedule_task_passes_cron_timezone(self):
        tool = ScheduleTaskTool()
        tool._scheduler = MagicMock()
        tool._scheduler.create_task.return_value = ScheduledTask(
            id="t123", prompt="hello", schedule_type="cron", schedule_value="0 8 * * *"
        )
        result = tool.execute(
            prompt="hello",
            schedule_type="cron",
            schedule_value="0 8 * * *",
            timezone="Europe/Madrid",
        )
        assert result.success
        assert tool._scheduler.create_task.call_args.kwargs["metadata"] == {
            "timezone": "Europe/Madrid"
        }

    def test_list_scheduled_tasks(self):
        mock_sched = MagicMock()
        mock_sched.list_tasks.return_value = [
            ScheduledTask(
                id="t1", prompt="a", schedule_type="interval", schedule_value="60"
            ),
        ]
        tool = ListScheduledTasksTool()
        tool._scheduler = mock_sched
        result = tool.execute()
        assert result.success
        assert "t1" in result.content

    def test_schedule_task_missing_params(self):
        tool = ScheduleTaskTool()
        tool._scheduler = MagicMock()
        result = tool.execute(prompt="hello")  # missing schedule_type, schedule_value
        assert not result.success
        assert "Missing" in result.content

    def test_pause_missing_task_id(self):
        tool = PauseScheduledTaskTool()
        tool._scheduler = MagicMock()
        result = tool.execute()  # missing task_id
        assert not result.success
        assert "Missing" in result.content
