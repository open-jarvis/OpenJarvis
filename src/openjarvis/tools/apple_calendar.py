"""Executable tools for the local Apple Calendar connector."""

from __future__ import annotations

import sqlite3
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("calendar_upcoming")
class CalendarUpcomingTool(BaseTool):
    """Return upcoming events from the local Apple Calendar database."""

    tool_id = "calendar_upcoming"

    @property
    def spec(self) -> ToolSpec:
        # Keep connector imports lazy.  Connectors use ``ToolSpec`` from the
        # tools package, so importing the connector here at module load time
        # creates a connector -> tools -> connector cycle and can skip these
        # registry decorators depending on import order.
        from openjarvis.connectors.apple_calendar import AppleCalendarConnector

        return AppleCalendarConnector().mcp_tools()[0]

    def execute(self, **params: Any) -> ToolResult:
        from openjarvis.connectors.apple_calendar import AppleCalendarConnector

        days_ahead = max(0, int(params.get("days_ahead", 7)))
        connector = AppleCalendarConnector(days_ahead=days_ahead, days_behind=0)
        documents = list(connector.sync())
        return ToolResult(
            tool_name=self.tool_id,
            content="\n\n".join(document.content for document in documents)
            or "No upcoming Apple Calendar events found.",
            success=True,
            metadata={"count": len(documents)},
        )


@ToolRegistry.register("calendar_search")
class CalendarSearchTool(BaseTool):
    """Search event titles in the local Apple Calendar database."""

    tool_id = "calendar_search"

    @property
    def spec(self) -> ToolSpec:
        from openjarvis.connectors.apple_calendar import AppleCalendarConnector

        return AppleCalendarConnector().mcp_tools()[1]

    def execute(self, **params: Any) -> ToolResult:
        from openjarvis.connectors.apple_calendar import (
            _SEARCH_QUERY,
            AppleCalendarConnector,
            _open_db,
        )

        query = str(params.get("query", "")).strip()
        if not query:
            return ToolResult(
                tool_name=self.tool_id,
                content="A non-empty query is required.",
                success=False,
            )
        limit = max(1, min(int(params.get("max_results", 20)), 100))
        connector = AppleCalendarConnector()
        conn = _open_db(connector._db_path)
        if conn is None:
            return ToolResult(
                tool_name=self.tool_id,
                content="Apple Calendar database is unavailable.",
                success=False,
            )
        try:
            rows = conn.execute(_SEARCH_QUERY, (f"%{query}%", limit)).fetchall()
        except sqlite3.Error as exc:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Apple Calendar search failed: {exc}",
                success=False,
            )
        finally:
            conn.close()
        lines = [
            f"{row[1]} — "
            f"{connector._display_datetimes(row[3], row[4], row[6], bool(row[5]))[0]}"
            for row in rows
        ]
        return ToolResult(
            tool_name=self.tool_id,
            content="\n".join(lines) or f"No Apple Calendar events matched '{query}'.",
            success=True,
            metadata={"count": len(rows)},
        )
