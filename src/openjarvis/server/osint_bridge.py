"""OSINT bridge — wire ToolExecutor events into the OSINT store.

Subscribes to ``TOOL_CALL_END`` on the global event bus and persists
``fbi_watchdog`` / ``osint_exec`` invocations so they appear in the
OSINT dashboard and history.
"""

from __future__ import annotations

from typing import Any

from openjarvis.core.events import EventBus, EventType


def register_osint_tool_tracker(bus: EventBus) -> None:
    """Subscribe *bus* so every OSINT tool call is written to the store."""

    def _on_tool_call_end(event: Any) -> None:
        tool_name = event.data.get("tool", "")
        if tool_name not in ("fbi_watchdog", "osint_exec"):
            return

        metadata = event.data.get("metadata", {})
        args = metadata.get("arguments", {})
        success = event.data.get("success", False)
        user_id = event.data.get("agent_id") or "system"

        from openjarvis.server.osint_store import get_store

        store = get_store()
        if tool_name == "fbi_watchdog":
            target = args.get("target", "")
            modules = args.get("modules", ["dns", "http", "whois", "ip"])
            if target:
                store.save_scan(
                    user_id,
                    target,
                    modules,
                    {"result": event.data.get("result", "")},
                    success,
                )
        elif tool_name == "osint_exec":
            exec_tool = args.get("tool_name", "")
            if exec_tool:
                store.add_action(
                    user_id,
                    exec_tool,
                    args,
                    {"result": event.data.get("result", "")},
                    success,
                )

    bus.subscribe(EventType.TOOL_CALL_END, _on_tool_call_end)
