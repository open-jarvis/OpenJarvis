"""Habit and journal tools, so the user can manage them by chat or voice.

* ``add_habit``       - track a new daily habit (optionally at a time)
* ``complete_habit``  - mark a habit done for today, by (part of) its name
* ``list_habits``     - today's habits and which are done
* ``write_journal``   - add a journal entry for today

They share the store behind the Jarvis home screen (``~/.openjarvis/life.db``).
"""

from __future__ import annotations

from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _store():
    from openjarvis.life.store import get_life_store

    return get_life_store()


def _result(name: str, content: str, success: bool = True) -> ToolResult:
    return ToolResult(tool_name=name, content=content, success=success)


@ToolRegistry.register("add_habit")
class AddHabitTool(BaseTool):
    tool_id = "add_habit"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="add_habit",
            description=(
                "Start tracking a daily habit on the user's home screen (e.g. "
                "'Workout', 'Read 20 pages'), optionally with a time of day."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short habit name."},
                    "time": {
                        "type": "string",
                        "description": "Optional 24-hour time like 06:30.",
                    },
                },
                "required": ["name"],
            },
            category="life",
            timeout_seconds=10.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            habit = _store().add_habit(
                str(params.get("name") or ""), time=str(params.get("time") or "")
            )
        except ValueError as exc:
            return _result("add_habit", str(exc), success=False)
        when = f" at {habit['time']}" if habit["time"] else ""
        return _result("add_habit", f"Now tracking '{habit['name']}'{when} daily.")


@ToolRegistry.register("complete_habit")
class CompleteHabitTool(BaseTool):
    tool_id = "complete_habit"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="complete_habit",
            description=(
                "Mark one of the user's habits as done for today, by its name "
                "or part of it (e.g. 'workout')."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "habit": {"type": "string", "description": "Habit name."},
                },
                "required": ["habit"],
            },
            category="life",
            timeout_seconds=10.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        store = _store()
        habit = store.find_habit(str(params.get("habit") or ""))
        if habit is None:
            names = ", ".join(h["name"] for h in store.list_habits()) or "none yet"
            return _result(
                "complete_habit",
                f"No habit matches that. The user's habits: {names}.",
                success=False,
            )
        store.set_done(habit["id"], None, True)
        return _result("complete_habit", f"Marked '{habit['name']}' done for today.")


@ToolRegistry.register("list_habits")
class ListHabitsTool(BaseTool):
    tool_id = "list_habits"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="list_habits",
            description="List the user's habits for today and which are done.",
            parameters={"type": "object", "properties": {}},
            category="life",
            timeout_seconds=10.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        habits = _store().list_habits()
        if not habits:
            return _result("list_habits", "No habits are being tracked yet.")
        lines = [
            f"[{'x' if h['done'] else ' '}] {h['name']}"
            + (f" ({h['time']})" if h["time"] else "")
            for h in habits
        ]
        return _result("list_habits", "\n".join(lines))


@ToolRegistry.register("write_journal")
class WriteJournalTool(BaseTool):
    tool_id = "write_journal"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="write_journal",
            description=(
                "Save a journal entry for today in the user's own words "
                "(when they ask to journal or note how their day went)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The entry."},
                },
                "required": ["text"],
            },
            category="life",
            timeout_seconds=10.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            _store().add_journal(str(params.get("text") or ""))
        except ValueError as exc:
            return _result("write_journal", str(exc), success=False)
        return _result("write_journal", "Saved to today's journal.")


__all__ = ["AddHabitTool", "CompleteHabitTool", "ListHabitsTool", "WriteJournalTool"]
