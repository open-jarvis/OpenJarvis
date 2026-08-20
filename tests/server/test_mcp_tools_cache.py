"""Tests for _get_mcp_tools() caching in agent_manager_routes."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi", reason="fastapi required for server route tests")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeAppState:
    """Minimal app_state substitute with dynamic attributes."""

    pass


def _make_config(*, enabled: bool = True, servers_json: str = "[]") -> MagicMock:
    """Build a mock config with tools.mcp.enabled and tools.mcp.servers."""
    config = MagicMock()
    config.tools.mcp.enabled = enabled
    config.tools.mcp.servers = servers_json
    return config


def _make_tool_spec(name: str, description: str = "") -> MagicMock:
    spec = MagicMock()
    spec.name = name
    spec.description = description
    spec.parameters = {"type": "object", "properties": {}}
    return spec


def _make_adapter(name: str) -> MagicMock:
    adapter = MagicMock()
    adapter.spec = _make_tool_spec(name)
    return adapter


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch("openjarvis.core.config.load_config")
def test_returns_tools_from_mcp_server(mock_load_config: MagicMock):
    """With a mocked MCP server, discovered tools are returned."""
    from openjarvis.server.agent_manager_routes import _get_mcp_tools

    server_cfg = [{"name": "test-server", "url": "http://localhost:9999"}]
    mock_load_config.return_value = _make_config(
        servers_json=json.dumps(server_cfg),
    )

    mock_adapter = _make_adapter("get_weather")

    with (
        patch("openjarvis.mcp.transport.StreamableHTTPTransport"),
        patch("openjarvis.mcp.client.MCPClient"),
        patch("openjarvis.tools.mcp_adapter.MCPToolProvider") as MockProvider,
    ):
        MockProvider.return_value.discover.return_value = [mock_adapter]

        app_state = _FakeAppState()
        tools, adapters = _get_mcp_tools(app_state)

    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "get_weather"
    assert "get_weather" in adapters


@patch("openjarvis.core.config.load_config")
def test_returns_tools_from_external_mcp_file(
    mock_load_config: MagicMock, tmp_path: Path
):
    """Managed-agent discovery uses the same file-backed config semantics."""

    from openjarvis.server.agent_manager_routes import _get_mcp_tools

    server_file = tmp_path / "mcp-servers.json"
    server_file.write_text(
        '[{"name": "file-server", "url": "http://localhost:9999"}]',
        encoding="utf-8",
    )
    config = _make_config(servers_json=server_file.name)
    config._config_dir = tmp_path
    mock_load_config.return_value = config
    mock_adapter = _make_adapter("file_tool")

    with (
        patch("openjarvis.mcp.transport.StreamableHTTPTransport"),
        patch("openjarvis.mcp.client.MCPClient"),
        patch("openjarvis.tools.mcp_adapter.MCPToolProvider") as provider,
    ):
        provider.return_value.discover.return_value = [mock_adapter]
        tools, adapters = _get_mcp_tools(_FakeAppState())

    assert tools[0]["function"]["name"] == "file_tool"
    assert adapters == {"file_tool": mock_adapter}


@patch("openjarvis.core.config.load_config")
def test_caches_successful_discovery(mock_load_config: MagicMock):
    """Second call returns cached result without re-discovering."""
    from openjarvis.server.agent_manager_routes import _get_mcp_tools

    server_cfg = [{"name": "test-server", "url": "http://localhost:9999"}]
    mock_load_config.return_value = _make_config(
        servers_json=json.dumps(server_cfg),
    )

    mock_adapter = _make_adapter("cached_tool")

    with (
        patch("openjarvis.mcp.transport.StreamableHTTPTransport"),
        patch("openjarvis.mcp.client.MCPClient"),
        patch("openjarvis.tools.mcp_adapter.MCPToolProvider") as MockProvider,
    ):
        MockProvider.return_value.discover.return_value = [mock_adapter]

        app_state = _FakeAppState()

        # First call discovers
        tools1, _ = _get_mcp_tools(app_state)
        assert len(tools1) == 1

        # Second call should use cache (discover not called again)
        discover_call_count = MockProvider.return_value.discover.call_count
        tools2, _ = _get_mcp_tools(app_state)
        assert len(tools2) == 1
        assert MockProvider.return_value.discover.call_count == discover_call_count


@patch("openjarvis.core.config.load_config")
def test_does_not_cache_empty_results(mock_load_config: MagicMock):
    """Failed/empty discovery is not cached so it can be retried."""
    from openjarvis.server.agent_manager_routes import _get_mcp_tools

    server_cfg = [{"name": "failing-server", "url": "http://localhost:9999"}]
    mock_load_config.return_value = _make_config(
        servers_json=json.dumps(server_cfg),
    )

    with (
        patch("openjarvis.mcp.transport.StreamableHTTPTransport"),
        patch("openjarvis.mcp.client.MCPClient") as MockClient,
        patch("openjarvis.tools.mcp_adapter.MCPToolProvider") as MockProvider,
    ):
        # First call: discovery returns empty
        MockProvider.return_value.discover.return_value = []
        app_state = _FakeAppState()

        tools1, _ = _get_mcp_tools(app_state)
        assert len(tools1) == 0
        MockClient.return_value.close.assert_called_once_with()
        assert getattr(app_state, "_mcp_clients", []) == []

        # Verify no cache was set (empty result)
        assert getattr(app_state, "_mcp_tools_cache", None) is None

        # Second call: discovery now returns something
        mock_adapter = _make_adapter("retry_tool")
        MockProvider.return_value.discover.return_value = [mock_adapter]

        tools2, _ = _get_mcp_tools(app_state)
        assert len(tools2) == 1
        assert tools2[0]["function"]["name"] == "retry_tool"


@patch("openjarvis.core.config.load_config")
def test_handles_config_load_failure(mock_load_config: MagicMock):
    """Config load failure returns empty, no crash."""
    from openjarvis.server.agent_manager_routes import _get_mcp_tools

    mock_load_config.side_effect = RuntimeError("config broken")

    app_state = _FakeAppState()
    tools, adapters = _get_mcp_tools(app_state)

    assert tools == []
    assert adapters == {}


@patch("openjarvis.core.config.load_config")
def test_uses_preloaded_full_system_pool(mock_load_config: MagicMock):
    """Server and scheduled paths reuse one unfiltered MCP discovery."""

    from openjarvis.server.agent_manager_routes import _get_mcp_tools

    adapter = _make_adapter("preloaded_tool")
    app_state = _FakeAppState()
    app_state.mcp_tools = [adapter]

    tools, adapters = _get_mcp_tools(app_state)

    mock_load_config.assert_not_called()
    assert tools[0]["function"]["name"] == "preloaded_tool"
    assert adapters == {"preloaded_tool": adapter}


@patch("openjarvis.core.config.load_config")
def test_preloaded_duplicate_names_are_first_wins(mock_load_config: MagicMock):
    """SSE and executor paths choose the same adapter on name collisions."""

    from openjarvis.server.agent_manager_routes import _get_mcp_tools

    first = _make_adapter("duplicate")
    second = _make_adapter("duplicate")
    app_state = _FakeAppState()
    app_state.mcp_tools = [first, second]

    tools, adapters = _get_mcp_tools(app_state)

    mock_load_config.assert_not_called()
    assert len(tools) == 1
    assert adapters == {"duplicate": first}


def test_app_shutdown_stops_scheduler_before_closing_shared_mcp_clients() -> None:
    """Shutdown quiesces and drains every user of the shared MCP pool."""

    from fastapi.testclient import TestClient

    from openjarvis.core.config import JarvisConfig
    from openjarvis.server.agent_manager_routes import _start_managed_worker
    from openjarvis.server.app import create_app

    events: list[str] = []
    release_worker = threading.Event()
    worker_finished = threading.Event()

    class _Scheduler:
        def request_stop(self):
            events.append("scheduler-stop")

        def wait_stopped(self, timeout=10):
            events.append("scheduler-wait")
            return True

    scheduler = _Scheduler()
    mcp_client = MagicMock()
    memory_backend = MagicMock()
    channel_bridge = MagicMock()

    def _close_mcp():
        events.append("mcp")
        release_worker.set()

    mcp_client.close.side_effect = _close_mcp
    memory_backend.close.side_effect = lambda: events.append("memory")
    channel_bridge.disconnect.side_effect = lambda: events.append("channel")
    config = JarvisConfig()
    config.analytics.enabled = False
    config.traces.enabled = False

    app = create_app(
        MagicMock(),
        "test-model",
        config=config,
        channel_bridge=channel_bridge,
        agent_scheduler=scheduler,
        mcp_clients=[mcp_client],
        memory_backend=memory_backend,
        own_memory_backend=True,
    )

    def _worker():
        release_worker.wait(timeout=2)
        events.append("worker-finished")
        worker_finished.set()

    _start_managed_worker(app.state, _worker, name="test-managed-worker")

    with TestClient(app):
        pass

    mcp_client.close.assert_called_once_with()
    memory_backend.close.assert_called_once_with()
    channel_bridge.disconnect.assert_called_once_with()
    assert worker_finished.is_set()
    assert app.state.memory_backend is None
    assert app.state._owns_memory_backend is False
    assert app.state._managed_runtime_stopping is True
    assert app.state._managed_workers == set()
    assert events.index("channel") < events.index("mcp")
    assert events.index("scheduler-stop") < events.index("mcp")
    assert events.index("mcp") < events.index("worker-finished")
    assert events.index("worker-finished") < events.index("memory")
    with pytest.raises(RuntimeError, match="shutting down"):
        _start_managed_worker(app.state, lambda: None, name="too-late-worker")


def test_shutdown_interrupts_mcp_client_during_lazy_initialization() -> None:
    """A client is registered before initialize() can block on transport I/O."""

    from fastapi.testclient import TestClient

    from openjarvis.core.config import JarvisConfig
    from openjarvis.server.agent_manager_routes import (
        _get_mcp_tools,
        _start_managed_worker,
    )
    from openjarvis.server.app import create_app

    initialize_started = threading.Event()
    initialize_released = threading.Event()
    discovery_finished = threading.Event()

    class _BlockingClient:
        def __init__(self):
            self.closed = False
            self.close_calls = 0

        def initialize(self):
            initialize_started.set()
            initialize_released.wait(timeout=2)
            if self.closed:
                raise RuntimeError("transport closed during initialize")

        def close(self):
            self.close_calls += 1
            self.closed = True
            initialize_released.set()

    client = _BlockingClient()
    config = JarvisConfig()
    config.analytics.enabled = False
    config.traces.enabled = False
    app = create_app(MagicMock(), "test-model", config=config)
    mcp_config = _make_config(
        servers_json=json.dumps([{"name": "blocking", "url": "http://localhost:9999"}])
    )

    def _discover():
        try:
            _get_mcp_tools(app.state)
        finally:
            discovery_finished.set()

    with (
        patch("openjarvis.core.config.load_config", return_value=mcp_config),
        patch("openjarvis.mcp.transport.StreamableHTTPTransport"),
        patch("openjarvis.mcp.client.MCPClient", return_value=client),
    ):
        _start_managed_worker(
            app.state,
            _discover,
            name="blocking-mcp-discovery",
        )
        assert initialize_started.wait(timeout=2)
        with app.state._mcp_clients_lock:
            assert client in app.state._mcp_clients

        with TestClient(app):
            pass

    assert client.close_calls >= 1
    assert discovery_finished.is_set()
    assert app.state._managed_workers == set()
    assert getattr(app.state, "_mcp_tools_cache", None) is None


def test_app_shutdown_closes_lazily_created_memory_backend(monkeypatch) -> None:
    """A backend opened by a managed route is owned and closed by the app."""

    from fastapi.testclient import TestClient

    from openjarvis.core.config import JarvisConfig
    from openjarvis.server import agent_manager_routes as routes
    from openjarvis.server.app import create_app

    backend = MagicMock()
    monkeypatch.setattr(routes, "_resolve_memory_backend", lambda config: backend)
    config = JarvisConfig()
    config.analytics.enabled = False
    config.traces.enabled = False
    app = create_app(MagicMock(), "test-model", config=config)

    assert routes._get_or_create_memory_backend(app.state, config) is backend
    assert app.state._owns_memory_backend is True

    with TestClient(app):
        pass

    backend.close.assert_called_once_with()
    assert app.state.memory_backend is None


def test_app_shutdown_keeps_owned_memory_open_for_live_worker(monkeypatch) -> None:
    """A timed-out worker must never resume against a closed backend."""

    from fastapi.testclient import TestClient

    from openjarvis.core.config import JarvisConfig
    from openjarvis.server import app as app_module
    from openjarvis.server.agent_manager_routes import _start_managed_worker

    monkeypatch.setattr(app_module, "_MANAGED_SHUTDOWN_GRACE_SECONDS", 0.01)
    monkeypatch.setattr(app_module, "_MANAGED_SHUTDOWN_DRAIN_SECONDS", 0.01)

    release_worker = threading.Event()
    worker_holds_memory_lock = threading.Event()
    shutdown_finished = threading.Event()
    shutdown_errors: list[BaseException] = []
    backend = MagicMock()
    config = JarvisConfig()
    config.analytics.enabled = False
    config.traces.enabled = False
    app = app_module.create_app(
        MagicMock(),
        "test-model",
        config=config,
        memory_backend=backend,
        own_memory_backend=True,
    )

    def _hold_memory_lock():
        with app.state._memory_backend_lock:
            worker_holds_memory_lock.set()
            release_worker.wait(timeout=2)

    worker = _start_managed_worker(
        app.state,
        _hold_memory_lock,
        name="memory-using-straggler",
    )
    assert worker_holds_memory_lock.wait(timeout=2)

    def _shutdown_app():
        try:
            with TestClient(app):
                pass
        except BaseException as exc:
            shutdown_errors.append(exc)
        finally:
            shutdown_finished.set()

    shutdown_thread = threading.Thread(target=_shutdown_app, daemon=True)
    shutdown_thread.start()

    try:
        assert shutdown_finished.wait(timeout=1)
        assert shutdown_errors == []
        backend.close.assert_not_called()
        assert app.state.memory_backend is backend
        assert app.state._owns_memory_backend is True
    finally:
        release_worker.set()
        worker.join(timeout=2)
        shutdown_thread.join(timeout=2)


def test_app_shutdown_leaves_borrowed_memory_backend_open() -> None:
    """An injected backend remains owned by its caller unless opted in."""

    from fastapi.testclient import TestClient

    from openjarvis.core.config import JarvisConfig
    from openjarvis.server.app import create_app

    backend = MagicMock()
    config = JarvisConfig()
    config.analytics.enabled = False
    config.traces.enabled = False
    app = create_app(
        MagicMock(),
        "test-model",
        config=config,
        memory_backend=backend,
    )

    with TestClient(app):
        pass

    backend.close.assert_not_called()
    assert app.state.memory_backend is backend
