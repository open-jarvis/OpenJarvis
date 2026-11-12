"""MCP tools for scheduler operations — schedule, list, pause, resume, cancel."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


_DAY_NUMBERS = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}
_TIME_RE = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*$", re.IGNORECASE)


def _parse_time(text: str) -> tuple[int, int]:
    """'21:00', '9pm', '7:30 am' -> (hour, minute)."""
    m = _TIME_RE.match(text or "")
    if not m:
        raise ValueError(f"expected a time like '21:00', got {text!r}")
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    ampm = (m.group(3) or "").lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"time out of range: {text!r}")
    return hour, minute


def normalize_schedule(schedule_type: str, schedule_value: str) -> tuple[str, str]:
    """Map friendly schedule types onto the scheduler's cron/interval/once.

    Small local models reliably fill ``daily`` + ``21:00`` but often swap the
    fields of a raw cron expression, so the friendly forms are preferred.
    """
    kind = schedule_type.strip().lower()
    value = schedule_value.strip()
    if kind in ("daily", "weekdays"):
        hour, minute = _parse_time(value)
        days = "*" if kind == "daily" else "1-5"
        return "cron", f"{minute} {hour} * * {days}"
    if kind == "weekly":
        day_text, _, time_text = value.partition(" ")
        day = _DAY_NUMBERS.get(day_text.strip().lower()[:3])
        if day is None:
            raise ValueError(f"expected '<day> HH:MM' like 'mon 08:00', got {value!r}")
        hour, minute = _parse_time(time_text or "09:00")
        return "cron", f"{minute} {hour} * * {day}"
    if kind in ("every_minutes", "every_hours"):
        try:
            n = float(value)
        except ValueError as exc:
            raise ValueError(f"expected a number, got {value!r}") from exc
        if n <= 0:
            raise ValueError("the number must be positive")
        seconds = n * (60 if kind == "every_minutes" else 3600)
        return "interval", str(int(max(60, seconds)))
    if kind in ("cron", "interval", "once"):
        return kind, value
    raise ValueError(f"unknown schedule type {schedule_type!r}")


@ToolRegistry.register("schedule_task")
class ScheduleTaskTool(BaseTool):
    """Schedule a new task for future or recurring execution."""

    tool_id = "schedule_task"
    _scheduler: Optional[Any] = None

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="schedule_task",
            description=(
                "Schedule a task for future or recurring execution in the "
                "user's local time. Use this when the user asks for a "
                "recurring routine or a reminder. Prefer the simple types: "
                "daily='21:00', weekdays='09:30', weekly='mon 08:00', "
                "every_minutes='30', every_hours='2', once='2026-12-01T18:00'. "
                "'cron' (5-field, minute first) and 'interval' (seconds) are "
                "also accepted."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Short label for the routine, e.g. 'Morning briefing'.",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "The prompt/query to execute on schedule.",
                    },
                    "schedule_type": {
                        "type": "string",
                        "description": "How the task repeats.",
                        "enum": [
                            "daily",
                            "weekdays",
                            "weekly",
                            "every_minutes",
                            "every_hours",
                            "once",
                            "cron",
                            "interval",
                        ],
                    },
                    "schedule_value": {
                        "type": "string",
                        "description": (
                            "daily/weekdays: 24h time 'HH:MM'; weekly: "
                            "'<day> HH:MM' (e.g. 'fri 17:00'); every_minutes / "
                            "every_hours: a number; once: local ISO datetime; "
                            "cron: 5-field expression; interval: seconds."
                        ),
                    },
                    "agent": {
                        "type": "string",
                        "description": "Agent to use for execution (default: orchestrator, which can use tools).",
                    },
                    "tools": {
                        "type": "string",
                        "description": (
                            "Comma-separated tool names for agent "
                            "(e.g. 'calculator,think')."
                        ),
                    },
                },
                "required": ["prompt", "schedule_type", "schedule_value"],
            },
            category="scheduler",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._scheduler is None:
            return ToolResult(
                tool_name="schedule_task",
                content="Scheduler not available. Cannot schedule tasks.",
                success=False,
            )
        prompt = params.get("prompt", "")
        schedule_type = params.get("schedule_type", "")
        schedule_value = params.get("schedule_value", "")
        if not prompt or not schedule_type or not schedule_value:
            return ToolResult(
                tool_name="schedule_task",
                content=(
                    "Missing required parameters:"
                    " prompt, schedule_type, schedule_value."
                ),
                success=False,
            )
        try:
            schedule_type, schedule_value = normalize_schedule(
                str(schedule_type), str(schedule_value)
            )
        except ValueError as exc:
            return ToolResult(
                tool_name="schedule_task",
                content=f"Invalid schedule: {exc}",
                success=False,
            )
        metadata: dict = {}
        if params.get("name"):
            metadata["name"] = str(params["name"])[:80]
        if schedule_type == "cron":
            from openjarvis.scheduler.settings import get_default_timezone

            tz = get_default_timezone()
            if tz:
                metadata["timezone"] = tz
        try:
            task = self._scheduler.create_task(
                prompt=prompt,
                schedule_type=schedule_type,
                schedule_value=schedule_value,
                agent=params.get("agent") or "orchestrator",
                tools=params.get("tools", ""),
                metadata=metadata,
            )
            return ToolResult(
                tool_name="schedule_task",
                content=json.dumps(
                    {
                        "task_id": task.id,
                        "next_run": task.next_run,
                        "status": task.status,
                    }
                ),
                success=True,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="schedule_task",
                content=f"Failed to schedule task: {exc}",
                success=False,
            )


@ToolRegistry.register("list_scheduled_tasks")
class ListScheduledTasksTool(BaseTool):
    """List all scheduled tasks."""

    tool_id = "list_scheduled_tasks"
    _scheduler: Optional[Any] = None

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="list_scheduled_tasks",
            description="List all scheduled tasks, optionally filtered by status.",
            parameters={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": (
                            "Filter by status: 'active', 'paused', "
                            "'completed', 'cancelled'."
                        ),
                    },
                },
            },
            category="scheduler",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._scheduler is None:
            return ToolResult(
                tool_name="list_scheduled_tasks",
                content="Scheduler not available.",
                success=False,
            )
        try:
            status = params.get("status")
            tasks = self._scheduler.list_tasks(status=status)
            items = [t.to_dict() for t in tasks]
            return ToolResult(
                tool_name="list_scheduled_tasks",
                content=json.dumps(items, default=str),
                success=True,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="list_scheduled_tasks",
                content=f"Failed to list tasks: {exc}",
                success=False,
            )


@ToolRegistry.register("pause_scheduled_task")
class PauseScheduledTaskTool(BaseTool):
    """Pause a scheduled task."""

    tool_id = "pause_scheduled_task"
    _scheduler: Optional[Any] = None

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="pause_scheduled_task",
            description="Pause an active scheduled task.",
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "ID of the task to pause.",
                    },
                },
                "required": ["task_id"],
            },
            category="scheduler",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._scheduler is None:
            return ToolResult(
                tool_name="pause_scheduled_task",
                content="Scheduler not available.",
                success=False,
            )
        task_id = params.get("task_id", "")
        if not task_id:
            return ToolResult(
                tool_name="pause_scheduled_task",
                content="Missing required parameter: task_id.",
                success=False,
            )
        try:
            self._scheduler.pause_task(task_id)
            return ToolResult(
                tool_name="pause_scheduled_task",
                content=f"Task {task_id} paused.",
                success=True,
            )
        except KeyError:
            return ToolResult(
                tool_name="pause_scheduled_task",
                content=f"Task not found: {task_id}",
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="pause_scheduled_task",
                content=f"Failed to pause task: {exc}",
                success=False,
            )


@ToolRegistry.register("resume_scheduled_task")
class ResumeScheduledTaskTool(BaseTool):
    """Resume a paused scheduled task."""

    tool_id = "resume_scheduled_task"
    _scheduler: Optional[Any] = None

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="resume_scheduled_task",
            description="Resume a paused scheduled task.",
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "ID of the task to resume.",
                    },
                },
                "required": ["task_id"],
            },
            category="scheduler",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._scheduler is None:
            return ToolResult(
                tool_name="resume_scheduled_task",
                content="Scheduler not available.",
                success=False,
            )
        task_id = params.get("task_id", "")
        if not task_id:
            return ToolResult(
                tool_name="resume_scheduled_task",
                content="Missing required parameter: task_id.",
                success=False,
            )
        try:
            self._scheduler.resume_task(task_id)
            return ToolResult(
                tool_name="resume_scheduled_task",
                content=f"Task {task_id} resumed.",
                success=True,
            )
        except KeyError:
            return ToolResult(
                tool_name="resume_scheduled_task",
                content=f"Task not found: {task_id}",
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="resume_scheduled_task",
                content=f"Failed to resume task: {exc}",
                success=False,
            )


@ToolRegistry.register("cancel_scheduled_task")
class CancelScheduledTaskTool(BaseTool):
    """Cancel a scheduled task."""

    tool_id = "cancel_scheduled_task"
    _scheduler: Optional[Any] = None

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="cancel_scheduled_task",
            description="Cancel a scheduled task.",
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "ID of the task to cancel.",
                    },
                },
                "required": ["task_id"],
            },
            category="scheduler",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._scheduler is None:
            return ToolResult(
                tool_name="cancel_scheduled_task",
                content="Scheduler not available.",
                success=False,
            )
        task_id = params.get("task_id", "")
        if not task_id:
            return ToolResult(
                tool_name="cancel_scheduled_task",
                content="Missing required parameter: task_id.",
                success=False,
            )
        try:
            self._scheduler.cancel_task(task_id)
            return ToolResult(
                tool_name="cancel_scheduled_task",
                content=f"Task {task_id} cancelled.",
                success=True,
            )
        except KeyError:
            return ToolResult(
                tool_name="cancel_scheduled_task",
                content=f"Task not found: {task_id}",
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="cancel_scheduled_task",
                content=f"Failed to cancel task: {exc}",
                success=False,
            )


__all__ = [
    "CancelScheduledTaskTool",
    "ListScheduledTasksTool",
    "PauseScheduledTaskTool",
    "ResumeScheduledTaskTool",
    "ScheduleTaskTool",
]
