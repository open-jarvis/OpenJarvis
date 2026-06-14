"""Tests for openjarvis.server.osint_bridge — TOOL_CALL_END → OSINT store."""

from __future__ import annotations

from typing import Any

from openjarvis.core.events import EventBus, EventType
from openjarvis.server.osint_bridge import register_osint_tool_tracker


class _FakeStore:
    def __init__(self) -> None:
        self.scans: list[dict[str, Any]] = []
        self.actions: list[dict[str, Any]] = []

    def save_scan(self, user_id: str, target: str, modules: list[str], results: dict[str, Any], success: bool) -> str:
        self.scans.append({"user_id": user_id, "target": target, "modules": modules, "success": success})
        return "scan-1"

    def add_action(self, user_id: str, tool_name: str, params: dict[str, Any], output: dict[str, Any], success: bool) -> str:
        self.actions.append({"user_id": user_id, "tool_name": tool_name, "success": success})
        return "action-1"


def test_fbi_watchdog_tool_call_is_persisted(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr("openjarvis.server.osint_store.get_store", lambda: store)

    bus = EventBus()
    register_osint_tool_tracker(bus)

    bus.publish(
        EventType.TOOL_CALL_END,
        {
            "tool": "fbi_watchdog",
            "success": True,
            "metadata": {"arguments": {"target": "example.com", "modules": ["dns"]}},
            "agent_id": "security_assistant",
        },
    )

    assert len(store.scans) == 1
    assert store.scans[0]["target"] == "example.com"
    assert store.scans[0]["user_id"] == "security_assistant"


def test_osint_exec_tool_call_is_persisted(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr("openjarvis.server.osint_store.get_store", lambda: store)

    bus = EventBus()
    register_osint_tool_tracker(bus)

    bus.publish(
        EventType.TOOL_CALL_END,
        {
            "tool": "osint_exec",
            "success": True,
            "metadata": {"arguments": {"tool_name": "nmap", "target": "1.2.3.4"}},
            "agent_id": "security_assistant",
        },
    )

    assert len(store.actions) == 1
    assert store.actions[0]["tool_name"] == "nmap"
    assert store.actions[0]["user_id"] == "security_assistant"


def test_non_osint_tool_is_ignored(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr("openjarvis.server.osint_store.get_store", lambda: store)

    bus = EventBus()
    register_osint_tool_tracker(bus)

    bus.publish(
        EventType.TOOL_CALL_END,
        {
            "tool": "calculator",
            "success": True,
            "metadata": {"arguments": {"expression": "1+1"}},
        },
    )

    assert len(store.scans) == 0
    assert len(store.actions) == 0


def test_fbi_watchdog_without_target_is_skipped(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr("openjarvis.server.osint_store.get_store", lambda: store)

    bus = EventBus()
    register_osint_tool_tracker(bus)

    bus.publish(
        EventType.TOOL_CALL_END,
        {
            "tool": "fbi_watchdog",
            "success": False,
            "metadata": {"arguments": {}},
        },
    )

    assert len(store.scans) == 0
