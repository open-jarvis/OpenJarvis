"""Contract tests for the kiosk customer-display presentation session."""

from __future__ import annotations

import asyncio

import pytest

import openjarvis.kiosk.presentation as presentation_module
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import ToolResult
from openjarvis.kiosk.presentation import (
    PresentationSessionManager,
    PresentationUnavailableError,
    find_playwright_client,
)


class _FakeMCPClient:
    """Deterministic boundary double for the existing Playwright MCP client."""

    def __init__(self, *, server_name: str = "") -> None:
        self._server_name = server_name
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.tab_list_text = "0: http://127.0.0.1:5173/kiosk"
        self.failures: dict[tuple[str, str | None], Exception | str] = {}

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, arguments))
        action = arguments.get("action")
        failure = self.failures.get(
            (name, action if isinstance(action, str) else None)
        )
        if isinstance(failure, Exception):
            raise failure
        if failure == "is_error":
            return {"content": [], "isError": True}
        if name == "browser_tabs" and arguments == {"action": "list"}:
            return {"content": [{"type": "text", "text": self.tab_list_text}]}
        return {"content": []}


@pytest.fixture
def bus() -> EventBus:
    return EventBus(record_history=True)


def test_cancelled_worker_cannot_publish_a_late_display(bus):
    from openjarvis.agents._stubs import _RUN_WORKER_LEASE, AgentWorkerLease

    manager = PresentationSessionManager(bus, _FakeMCPClient(server_name="playwright"))
    session = manager.ensure("http://127.0.0.1:5173")
    lease = AgentWorkerLease()
    token = _RUN_WORKER_LEASE.set(lease)
    try:
        lease._signal_cancelled()
        with pytest.raises(asyncio.CancelledError):
            manager.publish({"view": "payment_qr", "text": "stale"})
    finally:
        _RUN_WORKER_LEASE.reset(token)
    assert session.last_payload == {"view": "none"}
    assert not any(e.event_type == EventType.DISPLAY_UPDATE for e in bus.history)


def test_ensure_navigates_the_display_tab_without_creating_a_blank_tab(
    bus: EventBus,
) -> None:
    """Would fail if the kiosk created a visible about:blank tab for customers."""
    client = _FakeMCPClient(server_name="playwright")
    client.tab_list_text = "0: (current) about:blank"
    manager = PresentationSessionManager(bus, client)

    first = manager.ensure("http://127.0.0.1:5173")
    client.tab_list_text = f"0: (current) {first.display_url}"
    second = manager.ensure("http://127.0.0.1:5173")

    assert second is first
    assert first.display_tab_index == 0
    assert client.calls == [
        ("browser_tabs", {"action": "list"}),
        ("browser_navigate", {"url": first.display_url}),
        ("browser_tabs", {"action": "select", "index": 0}),
        ("browser_tabs", {"action": "list"}),
        ("browser_tabs", {"action": "select", "index": 0}),
    ]


def test_initial_display_loads_once_and_cannot_overwrite_a_new_voice_turn(
    bus: EventBus,
) -> None:
    manager = PresentationSessionManager(bus, _FakeMCPClient(server_name="playwright"))
    session = manager.ensure("http://127.0.0.1:5173")
    calls: list[str] = []

    def load() -> ToolResult:
        calls.append("load")
        manager.publish({"view": "menu", "items": [{"id": "latte"}]})
        return ToolResult(tool_name="skill_menu", content="shown", success=True)

    manager.configure_initial_display(load)

    assert manager.preload_initial_display() is True
    assert manager.preload_initial_display() is False
    assert calls == ["load"]
    assert manager.replay(session.session_id)["view"] == "menu"

    manager.activate("voice-1")
    assert manager.preload_initial_display() is False


def test_active_session_reloads_the_initial_menu_after_reset(bus: EventBus) -> None:
    manager = PresentationSessionManager(bus, _FakeMCPClient(server_name="playwright"))
    session = manager.ensure("http://127.0.0.1:5173")
    calls: list[str] = []

    def load() -> ToolResult:
        calls.append("load")
        manager.publish(
            {
                "view": "menu",
                "items": [{"name": "Cà phê sữa"}],
                "result_complete": True,
                "projected_count": 1,
                "published_count": 1,
            }
        )
        return ToolResult(tool_name="skill_menu", content="shown", success=True)

    manager.configure_initial_display(load)
    assert manager.preload_initial_display() is True
    assert manager.reset(session.session_id) is True
    assert manager.activate("voice-1") is True

    assert manager.load_initial_display() is True
    assert calls == ["load", "load"]
    assert manager.replay(session.session_id)["view"] == "menu"


def test_initial_display_logs_a_recipe_failure(bus: EventBus, caplog) -> None:
    manager = PresentationSessionManager(bus, _FakeMCPClient(server_name="playwright"))
    manager.ensure("http://127.0.0.1:5173")
    manager.configure_initial_display(
        lambda: ToolResult(
            tool_name="skill_menu", content="recipe_stale", success=False
        )
    )

    assert manager.preload_initial_display() is False
    assert "Initial display recipe failed." in caplog.messages


def test_activate_restores_display_focus_after_browser_automation(
    bus: EventBus,
) -> None:
    """Would fail if a new Voice session left automation in the foreground."""
    client = _FakeMCPClient(server_name="playwright")
    manager = PresentationSessionManager(bus, client)
    session = manager.ensure("http://127.0.0.1:5173")
    client.calls.clear()

    assert manager.activate("voice-2") is True
    assert client.calls == [("browser_tabs", {"action": "select", "index": 0})]
    assert session.display_tab_index == 0


def test_ensure_reselects_the_live_tab_when_display_navigation_raises(
    bus: EventBus,
) -> None:
    """Would fail if a transient navigation error left the new tab selected."""
    client = _FakeMCPClient(server_name="playwright")
    client.tab_list_text = "3: (current) kiosk home"
    client.failures[("browser_navigate", None)] = RuntimeError("navigation failed")
    manager = PresentationSessionManager(bus, client)

    with pytest.raises(PresentationUnavailableError) as exc_info:
        manager.ensure("http://127.0.0.1:5173")

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert client.calls[-1] == ("browser_tabs", {"action": "select", "index": 3})


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
        [
            ("browser_tabs", {"action": "list"}),
            ("browser_navigate", {"url": "ignored"}),
            ("browser_tabs", {"action": "select", "index": 0}),
        ],
)
@pytest.mark.parametrize("failure", ["is_error", RuntimeError("transport failed")])
def test_ensure_rejects_each_mcp_lifecycle_failure_without_committing_a_session(
    bus: EventBus,
    tool_name: str,
    arguments: dict[str, object],
    failure: Exception | str,
) -> None:
    """Would fail if a failed bootstrap operation became an active session."""
    client = _FakeMCPClient(server_name="playwright")
    action = arguments.get("action")
    client.failures[(tool_name, action if isinstance(action, str) else None)] = failure
    manager = PresentationSessionManager(bus, client)

    with pytest.raises(PresentationUnavailableError):
        manager.ensure("http://127.0.0.1:5173")

    result = manager.publish({"view": "menu"})
    assert result.success is False
    assert result.content == "presentation_unavailable"
    if tool_name == "browser_tabs" and arguments == {"action": "list"}:
        assert client.calls == [("browser_tabs", {"action": "list"})]
    else:
        assert client.calls[-1] == ("browser_tabs", {"action": "select", "index": 0})


def test_find_playwright_client_uses_only_the_playwright_server_name() -> None:
    """Would fail if an unrelated MCP client could own the display tab."""
    other = _FakeMCPClient(server_name="maps")
    playwright = _FakeMCPClient(server_name="playwright")

    assert find_playwright_client([other, playwright]) is playwright
    assert find_playwright_client([other]) is None


def test_ensure_without_a_playwright_client_is_unavailable(bus: EventBus) -> None:
    """Would fail if browser work were attempted without the required client."""
    with pytest.raises(PresentationUnavailableError):
        PresentationSessionManager(bus, None).ensure("http://127.0.0.1:5173")


@pytest.mark.parametrize(
    "origin",
    ["ftp://127.0.0.1:5173", "http://127.0.0.1:5173/kiosk", "http:///display"],
)
def test_ensure_rejects_invalid_origins_before_browser_calls(
    bus: EventBus, origin: str
) -> None:
    """Would fail if invalid display URLs reached Playwright."""
    client = _FakeMCPClient(server_name="playwright")

    with pytest.raises(ValueError):
        PresentationSessionManager(bus, client).ensure(origin)

    assert client.calls == []


def test_publish_scopes_and_replays_only_the_active_session(bus: EventBus) -> None:
    """Would fail if replay lost the display payload's session boundary."""
    manager = PresentationSessionManager(bus, _FakeMCPClient(server_name="playwright"))
    session = manager.ensure("http://127.0.0.1:5173")

    result = manager.publish({"view": "menu", "items": [{"id": "latte"}]})

    assert result.success is True
    assert manager.replay(session.session_id) == {
        "view": "menu",
        "items": [{"id": "latte"}],
        "presentation_session_id": session.session_id,
    }
    assert bus.history[-1].event_type == EventType.DISPLAY_UPDATE
    assert bus.history[-1].data == manager.replay(session.session_id)


def test_publish_without_an_active_session_returns_unavailable(bus: EventBus) -> None:
    """Would fail if display events could leak without a customer session."""
    result = PresentationSessionManager(
        bus, _FakeMCPClient(server_name="playwright")
    ).publish({"view": "menu"})

    assert result.success is False
    assert result.content == "presentation_unavailable"
    assert bus.history == []


def test_voice_generation_can_activate_before_display_ensure(bus: EventBus) -> None:
    """Would fail if non-blocking Voice start outran presentation bootstrap."""
    manager = PresentationSessionManager(bus, _FakeMCPClient(server_name="playwright"))

    assert manager.activate("thread-1") is True
    session = manager.ensure("http://127.0.0.1:5173")
    with presentation_module.presentation_generation("thread-1"):
        result = manager.publish({"view": "menu", "items": [{"id": "latte"}]})

    assert result.success is True
    assert manager.active_generation(session.session_id) == "thread-1"


def test_reset_clears_previous_customer_state(bus: EventBus) -> None:
    """Would fail if a new customer could replay the previous customer's cart."""
    manager = PresentationSessionManager(bus, _FakeMCPClient(server_name="playwright"))
    session = manager.ensure("http://127.0.0.1:5173")
    manager.publish({"view": "cart", "lines": [], "total": 0})

    assert manager.reset(session.session_id) is True
    assert manager.replay(session.session_id)["view"] == "none"


def test_publish_recovers_a_disconnected_display_tab_and_keeps_it_selected(
    bus: EventBus,
) -> None:
    """Would fail if reconnect recovery returned focus to automation."""
    client = _FakeMCPClient(server_name="playwright")
    manager = PresentationSessionManager(bus, client)
    session = manager.ensure("http://127.0.0.1:5173")
    manager.mark_display_disconnected(session.session_id)
    client.tab_list_text = "0: http://127.0.0.1:5173/kiosk"
    calls_before_recovery = len(client.calls)

    manager.publish({"view": "menu"})

    assert client.calls[calls_before_recovery:] == [
        ("browser_tabs", {"action": "list"}),
        ("browser_navigate", {"url": session.display_url}),
        ("browser_tabs", {"action": "select", "index": 0}),
    ]


def test_ensure_recovers_a_disconnected_display_without_creating_another_tab(
    bus: EventBus,
) -> None:
    client = _FakeMCPClient(server_name="playwright")
    manager = PresentationSessionManager(bus, client)
    session = manager.ensure("http://127.0.0.1:5173")
    manager.mark_display_disconnected(session.session_id)
    client.tab_list_text = "0: (current) about:blank"
    calls_before_recovery = len(client.calls)

    recovered = manager.ensure("http://127.0.0.1:5173")

    assert recovered is session
    assert client.calls[calls_before_recovery:] == [
        ("browser_tabs", {"action": "list"}),
        ("browser_navigate", {"url": session.display_url}),
        ("browser_tabs", {"action": "select", "index": 0}),
    ]


def test_ensure_recovers_when_the_tab_closes_before_websocket_disconnect(
    bus: EventBus,
) -> None:
    client = _FakeMCPClient(server_name="playwright")
    manager = PresentationSessionManager(bus, client)
    session = manager.ensure("http://127.0.0.1:5173")
    client.tab_list_text = "0: (current) about:blank"
    calls_before_recovery = len(client.calls)

    recovered = manager.ensure("http://127.0.0.1:5173")

    assert recovered is session
    assert client.calls[calls_before_recovery:] == [
        ("browser_tabs", {"action": "list"}),
        ("browser_navigate", {"url": session.display_url}),
        ("browser_tabs", {"action": "select", "index": 0}),
    ]


def test_publish_fails_safely_when_recovery_tab_listing_is_an_mcp_error(
    bus: EventBus,
) -> None:
    """Would fail if a failed tab listing created a duplicate display tab."""
    client = _FakeMCPClient(server_name="playwright")
    manager = PresentationSessionManager(bus, client)
    session = manager.ensure("http://127.0.0.1:5173")
    manager.mark_display_disconnected(session.session_id)
    client.failures[("browser_tabs", "list")] = "is_error"
    calls_before_recovery = len(client.calls)

    with pytest.raises(PresentationUnavailableError, match="browser_tabs"):
        manager.publish({"view": "menu"})

    assert client.calls[calls_before_recovery:] == [
        ("browser_tabs", {"action": "list"}),
        ("browser_tabs", {"action": "select", "index": session.display_tab_index}),
    ]


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("browser_tabs", {"action": "list"}),
        ("browser_navigate", {"url": "ignored"}),
        ("browser_tabs", {"action": "select", "index": 0}),
    ],
)
@pytest.mark.parametrize("failure", ["is_error", RuntimeError("transport failed")])
def test_recovery_rejects_each_mcp_lifecycle_failure_without_publishing(
    bus: EventBus,
    tool_name: str,
    arguments: dict[str, object],
    failure: Exception | str,
) -> None:
    """Would fail if a failed recovery operation emitted a display update."""
    client = _FakeMCPClient(server_name="playwright")
    manager = PresentationSessionManager(bus, client)
    session = manager.ensure("http://127.0.0.1:5173")
    manager.mark_display_disconnected(session.session_id)
    action = arguments.get("action")
    client.failures[(tool_name, action if isinstance(action, str) else None)] = failure
    calls_before_recovery = len(client.calls)

    with pytest.raises(PresentationUnavailableError):
        manager.publish({"view": "menu"})

    assert bus.history == []
    assert manager.replay(session.session_id) == {
        "view": "none",
        "presentation_session_id": session.session_id,
    }
    if tool_name == "browser_tabs" and arguments == {"action": "list"}:
        assert client.calls[calls_before_recovery:] == [
            ("browser_tabs", {"action": "list"}),
            ("browser_tabs", {"action": "select", "index": session.display_tab_index}),
        ]
    else:
        assert client.calls[-1] == (
            "browser_tabs",
            {"action": "select", "index": session.display_tab_index},
        )


def test_mark_display_connected_skips_recovery_when_the_page_reconnects(
    bus: EventBus,
) -> None:
    """Would fail if a connected display caused needless browser tab churn."""
    client = _FakeMCPClient(server_name="playwright")
    manager = PresentationSessionManager(bus, client)
    session = manager.ensure("http://127.0.0.1:5173")
    manager.mark_display_disconnected(session.session_id)
    manager.mark_display_connected(session.session_id)
    calls_before_publish = len(client.calls)

    manager.publish({"view": "menu"})

    assert client.calls[calls_before_publish:] == []
